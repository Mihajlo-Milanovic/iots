# Projekat 1 — Dokumentacija

## 1. Namena projekta

Sistem prihvata, čuva i analizira **vremensku seriju očitavanja sa IoT senzora**.
Sastoji se iz dva mikroservisa napisana u **dve različite tehnologije** (zahtev postavke) i
jednostavne aplikacije koja simulira senzore:

- **Gateway** (Java / Spring Boot) — REST API sa OpenAPI specifikacijom; radi CRUD operacije nad
  očitavanjima i agregacije (min, max, avg, sum) u zadatom vremenskom periodu. Sam ne pristupa
  bazi — sve prosleđuje DataManager-u preko gRPC-a.
- **DataManager** (Python / grpcio) — gRPC API sa Protobuf specifikacijom; jedini pristupa
  PostgreSQL bazi.
- **SensorGenerator** (Python) — čita CSV sa stvarnim podacima senzora i šalje ih Gateway-u
  preko REST-a, simulirajući akviziciju u realnom vremenu.

```
SensorGenerator ──REST──> Gateway ──gRPC──> DataManager ──SQL──> PostgreSQL
   (Python)          (Java / Spring Boot)   (Python / grpcio)
```

**Zašto ovakva podela:** Gateway je „javno lice" sistema i ne zna ništa o bazi; DataManager je
jedini vlasnik podataka. Time se baza može zameniti bez diranja REST sloja, a REST se može
zameniti bez diranja pristupa podacima.

## 2. Tehnologije i portovi

| Komponenta | Tehnologija | Port (host) |
|---|---|---|
| Gateway | Java 21, Spring Boot 3.3, springdoc-openapi | **8080** |
| DataManager | Python 3.12, grpcio, SQLAlchemy | **50051** |
| PostgreSQL | postgres:16-alpine | **5433** (u kontejneru 5432) |
| SensorGenerator | Python 3.12, requests | — |

## 3. Struktura foldera

```
project-1/
├── proto/reading.proto        # Protobuf specifikacija - JEDINI izvor za oba servisa
├── openapi.yaml               # OpenAPI specifikacija (generisana iz pokrenutog Gateway-a)
├── gateway/                   # Spring Boot REST servis
├── datamanager/               # Python gRPC servis
├── sensor-generator/          # simulacija senzora + CSV sa podacima
├── postman/                   # kolekcija za testiranje REST API-ja
├── docs/run-docker-run.md     # pokretanje pojedinačnim `docker run` komandama
├── docker-compose.yml         # pokretanje celog sistema
├── README.md                  # kratak pregled
├── PLAN.md                    # plan implementacije i obrazloženje odluka
└── DOCUMENTATION.md           # ovaj dokument
```

### Gateway (`gateway/`)

| Fajl | Uloga |
|---|---|
| `pom.xml` | Maven build; `protobuf-maven-plugin` generiše gRPC klase iz `../proto` |
| `src/main/java/rs/iots/gateway/GatewayApplication.java` | ulazna tačka, OpenAPI opis |
| `…/client/GrpcConfig.java` | kreira gRPC kanal i stubove ka DataManager-u |
| `…/controller/ReadingController.java` | svi REST endpointi |
| `…/dto/*.java` | ulazni/izlazni objekti (`ReadingDto`, `PageDto`, `AggregateDto`, …) |
| `…/mapper/ReadingMapper.java` | konverzija DTO ↔ Protobuf |
| `…/error/RestExceptionHandler.java` | mapiranje gRPC statusa u HTTP kodove |
| `src/main/resources/application.yml` | portovi, adresa DataManager-a, springdoc |

### DataManager (`datamanager/`)

| Fajl | Uloga |
|---|---|
| `server.py` | gRPC servis: implementacija svih RPC metoda, health check, reflection |
| `repository.py` | SQL upiti (CRUD + agregacije `MIN/MAX/AVG/SUM`) |
| `db.py` | SQLAlchemy model tabele `readings`, konekcija na bazu |
| `Dockerfile` | u toku build-a generiše Python stubove iz `proto/` (nije potreban lokalni `protoc`) |

### SensorGenerator (`sensor-generator/`)

`generator.py` čita CSV, prepoznaje uobičajene nazive kolona (`device/device_id/mac`,
`ts/timestamp/time`, `temp/temperature`, …) i podržava i Unix epoch i ISO-8601 vremenske oznake,
pa se dataset može zameniti bez izmene koda. Ima retry sa eksponencijalnim backoff-om.

## 4. Model podataka

Tabela `readings`:

| kolona | tip | napomena |
|---|---|---|
| `id` | `BIGSERIAL` | primarni ključ |
| `device_id` | `VARCHAR(128)` | identifikator uređaja, NOT NULL |
| `ts` | `TIMESTAMPTZ` | vreme očitavanja, NOT NULL |
| `temperature`, `humidity`, `co`, `smoke` | `DOUBLE PRECISION` | izmerene vrednosti |
| `lat`, `lon` | `DOUBLE PRECISION` | opcione koordinate |

Indeksi: `(device_id, ts)` i `(ts)` — pokrivaju pretragu po uređaju i periodu, i agregacije.

## 5. API

### REST (Gateway), bazna putanja `/api/v1/readings`

| Metod | Putanja | Opis | Uspeh |
|---|---|---|---|
| `POST` | `/api/v1/readings` | dodavanje očitavanja | 201 |
| `POST` | `/api/v1/readings/batch` | grupni unos (koristi SensorGenerator) | 200 |
| `GET` | `/api/v1/readings/{id}` | dohvatanje po id-u | 200 / 404 |
| `GET` | `/api/v1/readings?deviceId=&from=&to=&page=&size=` | pretraga i paginacija | 200 |
| `PUT` | `/api/v1/readings/{id}` | ažuriranje | 200 / 404 |
| `DELETE` | `/api/v1/readings/{id}` | brisanje | 204 / 404 |
| `GET` | `/api/v1/readings/aggregate?deviceId=&field=&from=&to=` | min, max, avg, sum, count | 200 |

Greške se vraćaju u jedinstvenom formatu; gRPC statusi se mapiraju u HTTP:
`NOT_FOUND`→404, `INVALID_ARGUMENT`→400, `UNAVAILABLE`→503, ostalo→502.

### gRPC (DataManager), paket `iots.datamanager.v1`

`Create`, `Get`, `List`, `Update` (uz `fields` masku za delimičnu izmenu), `Delete`,
`Aggregate`, `BatchCreate` (klijentski streaming). Uključeni su i **health checking** i
**server reflection**, pa se servis može testirati bez ručnog učitavanja `.proto` fajla.

## 6. Pokretanje

### A) Docker Compose (preporučeno)

```bash
cd project-1
docker compose up --build -d
```
Prvi build traje nekoliko minuta jer se Gateway kompajlira u kontejneru (Maven povlači zavisnosti).

Provera da je sve podignuto:
```bash
docker compose ps
```
Očekivano: `iots-db`, `iots-datamanager`, `iots-gateway` — svi `(healthy)`.

Punjenje baze podacima:
```bash
docker compose --profile tools run --rm generator
```

Korisni linkovi:
- Swagger UI: <http://localhost:8080/swagger-ui.html>
- OpenAPI JSON: <http://localhost:8080/v3/api-docs>

Gašenje (`-v` briše i podatke iz baze):
```bash
docker compose down -v
```

### B) Pojedinačne `docker run` komande

Ceo redosled (kreiranje `iots-net` bridge mreže, pa kontejneri jedan po jedan) je u
[`docs/run-docker-run.md`](docs/run-docker-run.md).

## 7. Testiranje

### 7.1 Postman

Uvezite [`postman/IoTS-P1.postman_collection.json`](postman/IoTS-P1.postman_collection.json).
Kolekcija ima 10 zahteva: svih 7 endpointa plus negativni slučajevi (404, validacija 400,
nepostojeće polje agregacije). Promenljiva `baseUrl` je `http://localhost:8080`.

Zahteve pokrenuti **redom** — prvi (`01 Create reading`) upisuje `id` u promenljivu
`readingId`, koju koriste kasniji zahtevi.

Iz komandne linije:
```bash
newman run postman/IoTS-P1.postman_collection.json
```

### 7.2 Provera REST-a iz komandne linije

```bash
# 1. dodavanje  -> ocekivano HTTP 201 i telo sa "id"
curl -i -X POST http://localhost:8080/api/v1/readings \
  -H 'Content-Type: application/json' \
  -d '{"deviceId":"b8:27:eb:bf:9d:51","ts":"2020-07-12T00:01:34Z",
       "temperature":22.7,"humidity":51,"co":0.0049,"smoke":0.0204,
       "lat":44.8125,"lon":20.4612}'

# 2. pretraga po uredjaju i periodu -> HTTP 200, {"items":[...],"total":N}
curl "http://localhost:8080/api/v1/readings?deviceId=b8:27:eb:bf:9d:51\
&from=2020-07-12T00:00:00Z&to=2020-07-13T00:00:00Z&size=5"

# 3. agregacije -> HTTP 200, {"min":..,"max":..,"avg":..,"sum":..,"count":..}
curl "http://localhost:8080/api/v1/readings/aggregate?field=temperature\
&from=2020-07-12T00:00:00Z&to=2020-07-21T00:00:00Z"

# 4. negativni slucajevi
curl -o /dev/null -w "%{http_code}\n" http://localhost:8080/api/v1/readings/999999999   # 404
curl -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/api/v1/readings \
  -H 'Content-Type: application/json' -d '{"deviceId":"","temperature":22}'             # 400
curl -o /dev/null -w "%{http_code}\n" \
  "http://localhost:8080/api/v1/readings/aggregate?field=nepostojece"                   # 400
```

### 7.3 Provera gRPC-a

DataManager ima uključen **reflection**, pa `grpcurl` ne traži `.proto` fajl:
```bash
grpcurl -plaintext localhost:50051 list
grpcurl -plaintext -d '{"id":1}' localhost:50051 iots.datamanager.v1.ReadingService/Get
```
Isto se može uraditi i gRPC zahtevom u Postman-u (`localhost:50051`, „Use server reflection").

### 7.4 Provera da agregacije odgovaraju bazi

Rezultat REST agregacije se može uporediti sa direktnim SQL upitom:
```bash
docker exec iots-db psql -U iots -d iots -c \
  "select device_id, min(temperature), max(temperature), avg(temperature), count(*)
   from readings group by device_id order by device_id;"
```

### 7.5 Provera šeme baze

```bash
docker exec iots-db psql -U iots -d iots -c "\d readings"
```
Očekivano: `id` je `bigint ... default nextval('readings_id_seq')` (BIGSERIAL),
`ts` je `timestamp with time zone`, i postoje indeksi `ix_readings_device_ts` i `ix_readings_ts`.

## 8. Napomene i česti problemi

**Port 5432 je zauzet.** PostgreSQL je namerno izložen na **5433** na hostu. Ako je i 5433
zauzet, promenite mapiranje u `docker-compose.yml` (`"5433:5432"`); servisi se međusobno
povezuju preko mreže na port 5432 i to se ne menja.

**Prvi build Gateway-a je spor.** Maven u kontejneru povlači ceo dependency tree. Naredni
build-ovi koriste Docker cache i znatno su brži.

**Zajednički `.proto`.** `proto/reading.proto` je jedini izvor Protobuf definicije: Gateway ga
kompajlira `protobuf-maven-plugin`-om (`protoSourceRoot` pokazuje na `../proto`), a DataManager
`grpc_tools.protoc`-om u toku Docker build-a. Zato se oba image-a grade **iz korena `project-1/`**,
a ne iz svojih podfoldera. Nije potrebno lokalno instalirati `protoc` ni Maven.

**Generator ne šalje ništa.** Proverite putanju do CSV-a (`--file`) — podrazumevana vrednost je
relativna (`data/sensor_data.csv`), pa iz korena projekta treba
`--file sensor-generator/data/sensor_data.csv`.
