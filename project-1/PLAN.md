# Projekat 1 — Plan implementacije

## 0. Izbor tehnologija (zahtev 4: dva različita stack-a)

| Komponenta | Tehnologija | Razlog |
|---|---|---|
| **Gateway** (REST + OpenAPI) | Java 21 / Spring Boot 3 | springdoc-openapi generiše OpenAPI spec automatski; grpc-client je zreo |
| **DataManager** (gRPC + PostgreSQL) | Python 3.12 + grpcio + SQLAlchemy | čist gRPC servis, bez REST sloja; brz za CRUD nad Postgresom |
| **SensorGenerator** | Python 3.12 (requests) | čita CSV, šalje na Gateway REST |
| **Baza** | PostgreSQL 16 (Docker) | |
| **Orkestracija** | Docker run (bridge net) + Docker Compose | zahtev 5a i 5b |

## 1. Dataset (zahtev 1)
- Izabrati vremensku seriju sa senzora sa Kaggle/UCI koja **nije** korišćena u ranijim projektima.
- Predlog: "Environmental Sensor Telemetry Data" (Kaggle) — kolone: `ts, device, co, humidity, light, lpg, motion, smoke, temp`.
- Skinuti CSV u `data/sensor_data.csv`, zadržati ~10–50k redova.
- Model podatka (tabela `readings`):
  `id BIGSERIAL PK, device_id TEXT, ts TIMESTAMPTZ, temperature DOUBLE, humidity DOUBLE, co DOUBLE, smoke DOUBLE, lat DOUBLE NULL, lon DOUBLE NULL`
  Indeksi: `(device_id, ts)`, `(ts)`.

## 2. Struktura repozitorijuma
```
project-1/
  proto/reading.proto            # Protobuf spec (deljena)
  gateway/                       # Spring Boot
    src/main/java/... controller, dto, grpc client, mapper
    src/main/resources/openapi.yaml   # ili generisan /v3/api-docs
    Dockerfile
  datamanager/                   # Python gRPC
    server.py, db.py, models.py, repository.py
    generated/                   # iz protoc
    Dockerfile
  sensor-generator/
    generator.py, data/sensor_data.csv, Dockerfile
  docker-compose.yml
  postman/IoTS-P1.postman_collection.json
  docs/run-docker-run.md         # komande za 5a
  README.md
```

## 3. Protobuf specifikacija (zahtev 3)
`proto/reading.proto`, paket `iots.datamanager.v1`:

```
message Reading { 
	int64 id; 
	string device_id; 
	google.protobuf.Timestamp ts; 
	double temperature;
	double humidity; 
	double co; 
	double smoke;
	optional double lat;
	optional double lon; 
}
```

- Servis `ReadingService`:
  - `Create(CreateRequest) → Reading`
  - `Get(GetRequest{id}) → Reading`
  - `List(ListRequest{device_id, from, to, page, page_size}) → ListResponse{readings, total}`
  - `Update(UpdateRequest{id, reading, field_mask}) → Reading`
  - `Delete(DeleteRequest{id}) → DeleteResponse{deleted}`
  - `Aggregate(AggregateRequest{device_id, field, from, to}) → AggregateResponse{min, max, avg, sum, count}`
  - `BatchCreate(stream Reading) → BatchResponse` (za brz upis iz generatora)

## 4. DataManager (gRPC servis)
1. `protoc` generisanje Python stubova u `generated/`.
2. SQLAlchemy model + Alembic (ili prost `init.sql` montiran u Postgres kontejner).
3. Implementacija svih RPC metoda; agregacije kao SQL `MIN/MAX/AVG/SUM` sa `WHERE ts BETWEEN`.
4. Mapiranje grešaka: not found → `NOT_FOUND`, validacija → `INVALID_ARGUMENT`.
5. Health check (`grpc_health_v1`) za Compose `depends_on`.
6. Sluša na `0.0.0.0:50051`.

## 5. Gateway (REST + OpenAPI, zahtev 2)
gRPC klijent ka DataManageru; REST endpointi:

| Metod | Putanja | Opis |
|---|---|---|
| POST | `/api/v1/readings` | dodavanje jednog očitavanja |
| POST | `/api/v1/readings/batch` | bulk unos (generator) |
| GET | `/api/v1/readings/{id}` | dohvatanje |
| GET | `/api/v1/readings?deviceId=&from=&to=&page=&size=` | pretraga/filtriranje |
| PUT | `/api/v1/readings/{id}` | ažuriranje |
| DELETE | `/api/v1/readings/{id}` | brisanje |
| GET | `/api/v1/readings/aggregate?deviceId=&field=temperature&from=&to=` | min, max, avg, sum |

- DTO ↔ protobuf maperi, `@Valid` validacija, `@RestControllerAdvice` za greške (400/404/502).
- springdoc: `/swagger-ui.html`, spec eksportovati u `openapi.yaml` i commit-ovati (zahtev 8).
- Konfiguracija adrese preko `DATAMANAGER_HOST/PORT` env varijabli.

## 6. SensorGenerator (zahtev 6)
- Čita CSV red po red, mapira u JSON.
- Argumenti: `--file`, `--gateway-url`, `--rate` (očitavanja/s), `--batch`, `--loop`.
- Simulira realno vreme (`sleep` između slanja), loguje status i retry uz backoff.

## 7. Docker (zahtev 5)
**a) docker run:**
```
docker network create iots-net
docker run -d --name iots-db --network iots-net -e POSTGRES_... -v pgdata:/var/lib/postgresql/data postgres:16
docker run -d --name datamanager --network iots-net -e DB_HOST=iots-db iots/datamanager
docker run -d --name gateway --network iots-net -p 8080:8080 -e DATAMANAGER_HOST=datamanager iots/gateway
docker run --rm --network iots-net -e GATEWAY_URL=http://gateway:8080 iots/sensor-generator
```
**b) docker-compose.yml:** servisi `db`, `datamanager`, `gateway`, `generator` (profil `tools`), `healthcheck` + `depends_on: condition: service_healthy`, imenovan volume za Postgres.
- Multi-stage Dockerfile za Gateway (maven build → JRE slim), slim-python za ostale.

## 8. Testiranje (zahtev 7)
- Postman kolekcija: svih 7 REST endpointa + negativni slučajevi (404, 400), environment sa `baseUrl`.
- gRPC: Postman gRPC request ili `grpcurl` uz reflection (uključiti gRPC reflection na serveru).
- Screenshotovi/exportovana kolekcija u `postman/`.

## 9. GitHub isporuka (zahtev 8)
- Push izvornog koda, `proto/reading.proto`, `openapi.yaml`.
- README: opis REST endpointa i gRPC metoda, dataset izvor, uputstvo za pokretanje (oba načina), primeri poziva.

## Redosled rada
1. Dataset + šema baze → 2. `.proto` → 3. DataManager + Postgres u Dockeru → 4. Gateway + OpenAPI → 5. SensorGenerator → 6. docker run skripte → 7. Compose → 8. Postman → 9. README + push.
