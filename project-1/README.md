# IoTS — Projekat 1: Gateway (REST) + DataManager (gRPC) + SensorGenerator

Mikroservisni sistem za pribavljanje, čuvanje i analizu vremenske serije očitavanja sa IoT senzora.

```
SensorGenerator  ──REST──>  Gateway  ──gRPC──>  DataManager  ──SQL──> PostgreSQL
   (Python)            (Java/Spring Boot)     (Python / grpcio)
```

| Komponenta      | Tehnologija                                         | Port                                 |
| --------------- | --------------------------------------------------- | ------------------------------------ |
| Gateway         | Java 21 / Spring Boot 3.3 (REST + OpenAPI)          | 8080                                 |
| DataManager     | Python 3.12 / grpcio + SQLAlchemy (gRPC + Protobuf) | 50051                                |
| PostgreSQL      | postgres:16-alpine                                  | 5432 u kontejneru, **5433 na hostu** |
| SensorGenerator | Python 3.12 (requests)                              | —                                    |
## Podaci

Korišćen je dataset **Environmental Sensor Telemetry Data** (Kaggle) — vremenska serija očitavanja
Tri senzorska uređaja: 
- `ts` (Unix epoch), 
- `device` (MAC adresa),
- `co`,
- `humidity`,
- `light`,
- `lpg`,
- `motion`,
- `smoke`,
- `temp`. 

Datoteka: [`sensor-generator/data/sensor_data.csv`](sensor-generator/data/sensor_data.csv) (~405.000 očitavanja, uređaji `b8:27:eb:bf:9d:51`, `00:0f:00:70:91:0a`, `1c:bf:ce:15:ec:4d`, period 12.07.2020 – 20.07.2020).

U bazu se upisuju `device_id`, `ts`, `temperature`, `humidity`, `co`, `smoke` i opcione koordinate (`lat`, `lon`). Logičke kolone `light`, `motion`, `lpg` se ne koriste u ovom projektu.

Generator prepoznaje uobičajene nazive kolona (`device/device_id/mac`, `ts/timestamp/time`, `temp/temperature`, `humidity`, `co`, `smoke`, `lat`, `lon`) i podržava i Unix epoch (sekunde ili milisekunde) i ISO-8601 vremenske oznake, pa se dataset može zameniti bez izmene koda.

## Pokretanje

### Docker Compose
```bash
cd project-1
docker compose up --build -d          # db + datamanager + gateway
docker compose --profile tools run --rm generator   # napuni bazu podacima
```

Swagger UI: <http://localhost:8080/swagger-ui.html>
### Pojedinačne `docker run` komande

Vidi [`docs/run-docker-run.md`](docs/run-docker-run.md) — kreiranje `iots-net` bridge mreže i
povezivanje kontejnera preko nje.

## REST API (Gateway)

Bazna putanja `/api/v1/readings`. Puna specifikacija: [`openapi.yaml`](openapi.yaml),
uživo na `/v3/api-docs` odnosno `/swagger-ui.html`.

| Metod | Putanja | Opis |
|---|---|---|
| `POST` | `/api/v1/readings` | Dodavanje novog očitavanja → `201` |
| `POST` | `/api/v1/readings/batch` | Grupni unos (koristi SensorGenerator) |
| `GET` | `/api/v1/readings/{id}` | Dohvatanje po identifikatoru → `200` / `404` |
| `GET` | `/api/v1/readings?deviceId=&from=&to=&page=&size=` | Pretraga po uređaju i periodu, sa paginacijom |
| `PUT` | `/api/v1/readings/{id}` | Ažuriranje |
| `DELETE` | `/api/v1/readings/{id}` | Brisanje → `204` / `404` |
| `GET` | `/api/v1/readings/aggregate?deviceId=&field=&from=&to=` | **min, max, avg, sum** i broj očitavanja u periodu |

Primeri:
```bash
curl -X POST http://localhost:8080/api/v1/readings \
  -H 'Content-Type: application/json' \
  -d '{
  "deviceId":"b8:27:eb:bf:9d:51",
  "ts":"2020-07-12T00:01:34Z",
  "temperature":22.7,
  "humidity":51,
  "co":0.0049,
  "smoke":0.0204
  }'

curl "http://localhost:8080/api/v1/readings?deviceId=b8:27:eb:bf:9d:51&from=2020-07-12T00:00:00Z&to=2020-07-13T00:00:00Z&size=10"

curl "http://localhost:8080/api/v1/readings/aggregate?field=temperature&from=2020-07-12T00:00:00Z&to=2020-07-13T00:00:00Z"
```

Greške se vraćaju u jedinstvenom `ErrorDto` formatu; gRPC statusi se mapiraju u HTTP
(`NOT_FOUND`→404, `INVALID_ARGUMENT`→400, `UNAVAILABLE`→503, ostalo→502).

## gRPC API (DataManager)

Specifikacija: [`proto/reading.proto`](proto/reading.proto), paket `iots.datamanager.v1`.

|      RPC      | Zahtev → Odgovor                         | Opis                                                            |
| :-----------: | :--------------------------------------- | --------------------------------------------------------------- |
|   `Create`    | `CreateRequest` → `Reading`              | Upis jednog očitavanja                                          |
|     `Get`     | `GetRequest` → `Reading`                 | Dohvatanje po `id`, `NOT_FOUND` ako ne postoji                  |
|    `List`     | `ListRequest` → `ListResponse`           | Filtriranje po `device_id` i periodu, paginacija (max 500)      |
|   `Update`    | `UpdateRequest` → `Reading`              | Puna ili delimična izmena (`fields`)                            |
|   `Delete`    | `DeleteRequest` → `DeleteResponse`       | Brisanje                                                        |
|  `Aggregate`  | `AggregateRequest` → `AggregateResponse` | SQL `MIN/MAX/AVG/SUM/COUNT` nad `temperature｜humidity｜co｜smoke` |
| `BatchCreate` | `stream Reading` → `BatchResponse`       | Klijentski streaming, upis u serijama po 500                    |

Uključeni su i **gRPC health checking** (koristi ga Compose `depends_on`) i **server reflection**,
pa se servis može testirati bez ručnog učitavanja `.proto` datoteke:
```bash
grpcurl -plaintext localhost:50051 list
grpcurl -plaintext -d '{"id":1}' localhost:50051 iots.datamanager.v1.ReadingService/Get
```

## SensorGenerator

```bash
python sensor-generator/generator.py \
  --file sensor-generator/data/sensor_data.csv \
  --gateway-url http://localhost:8080 \
  --rate 50 --batch 100 --limit 5000
```

| Opcija | Env | Opis |
|---|---|---|
| `--file` | `CSV_FILE` | ulazni CSV |
| `--gateway-url` | `GATEWAY_URL` | adresa Gateway-a |
| `--rate` | `RATE` | očitavanja u sekundi (0 = bez pauze) |
| `--batch` | `BATCH` | očitavanja po zahtevu (1 = pojedinačni `POST`) |
| `--limit` | `LIMIT` | ukupan broj poslatih očitavanja (0 = svi) |
| `--loop` | `LOOP` | ponavljanje datoteke u krug |

Ima retry sa eksponencijalnim backoff-om, pa preživljava sporo podizanje Gateway-a.

## Testiranje

Postman kolekcija: [`postman/IoTS-P1.postman_collection.json`](postman/IoTS-P1.postman_collection.json) 
— 7 REST endpointa + negativni slučajevi (404, validacija 400, nepostojeće polje agregacije).
gRPC se testira Postman gRPC zahtevom ili `grpcurl`-om preko reflection-a.

```bash
npx -y newman run postman/IoTS-P1.postman_collection.json
```

## Struktura
```
project-1/
├── proto/reading.proto              # Protobuf specifikacija
├── openapi.yaml                     # OpenAPI specifikacija
├── gateway/                         # Spring Boot REST servis + gRPC klijent
├── datamanager/                     # Python gRPC servis nad PostgreSQL-om
├── sensor-generator/                # simulacija akvizicije sa senzora
├── postman/                         # kolekcija za testiranje
├── docs/run-docker-run.md           # pojedinacne docker-run komande  
└── docker-compose.yml
```

## Napomene o izgradnji

`proto/reading.proto` je **jedini izvor** Protobuf definicije za oba servisa:
 - Gateway stubove generiše `protobuf-maven-plugin` (`protoSourceRoot` pokazuje na `../proto`),
 - DataManager `grpc_tools.protoc` u toku Docker build-a. 
 Zato se oba image-a grade iz korena `project-1/`. Nije potrebno imati lokalno instaliran `protoc`.
