# IoTS — Projekat 2: MQTT, EventManager i detekcija događaja

Nadogradnja Projekta 1. DataManager pored upisa u bazu **objavljuje očitavanja na MQTT topic**,
**EventManager** ih konzumira i pri prekoračenju pragova objavljuje **događaje** na drugi topic,
a **MqttClient** web aplikacija ih prikazuje uživo.

```
SensorGenerator ─REST→ Gateway ─gRPC→ DataManager ─SQL→ PostgreSQL
                                          │
                                          └─publish→ iots/readings/{deviceId}
                                                          │
                                                   Mosquitto broker
                                                          │
                                    EventManager ─subscribe┘
                                          │
                                          └─publish→ iots/events/{deviceId}/{field}
                                                          │
                                              MqttClient (web, WebSocket)
```

| Komponenta | Tehnologija | Port |
|---|---|---|
| Mosquitto | eclipse-mosquitto:2 | 1883 (TCP), 9001 (WebSocket) |
| Gateway | Java 21 / Spring Boot 3.3 (REST + OpenAPI) | 8080 |
| DataManager | Python 3.12 / grpcio + SQLAlchemy + paho-mqtt | 50051 |
| **EventManager** | **Python 3.12 / paho-mqtt** | **8000 (health)** |
| **MqttClient** | **HTML/JS + MQTT.js, nginx** | **8081** |
| PostgreSQL | postgres:16-alpine | 5432 u kontejneru, **5433 na hostu** |
| SensorGenerator | Python 3.12 (requests) | — |

## Pokretanje

```bash
cd project-2
docker compose up --build -d                          # svih 6 servisa
docker compose --profile tools run --rm generator     # replay podataka
```

- MqttClient: <http://localhost:8081>
- Swagger UI: <http://localhost:8080/swagger-ui.html>
- EventManager health: <http://localhost:8000/health>

## MQTT topic-i

| Topic | Publikuje | Konzumira | QoS | Retain |
|---|---|---|---|---|
| `iots/readings/{deviceId}` | DataManager | EventManager (`iots/readings/+`) | 1 | ne |
| `iots/events/{deviceId}/{field}` | EventManager | MqttClient (`iots/events/#`) | 1 | ne |

**Poruka očitavanja:**
```json
{ "id": 12345, "deviceId": "b8:27:eb:bf:9d:51", "ts": "2020-07-12T00:01:34Z",
  "temperature": 22.7, "humidity": 51.0, "co": 0.0049, "smoke": 0.0204,
  "location": { "lat": 44.8125, "lon": 20.4612 } }
```

**Poruka događaja** (sadrži tip, vrednosti, lokaciju i vreme):
```json
{ "eventId": "1c:bf:ce:15:ec:4d-temperature-4", "type": "THRESHOLD_EXCEEDED",
  "severity": "CRITICAL", "deviceId": "1c:bf:ce:15:ec:4d", "field": "temperature",
  "value": 30.4, "unit": "C", "threshold": 29.0, "operator": "gt", "exceededBy": 1.4,
  "readingId": 4, "readingTs": "2020-07-12T00:01:34Z", "detectedAt": "2026-09-02T07:01:35Z",
  "location": { "lat": 44.8125, "lon": 20.4612 } }
```

Specifikacije: [`asyncapi/datamanager.yaml`](asyncapi/datamanager.yaml) i
[`asyncapi/eventmanager.yaml`](asyncapi/eventmanager.yaml) (AsyncAPI 3.1.0, oba prolaze
`npx @asyncapi/cli validate` bez grešaka).

## DataManager — izmene u odnosu na Projekat 1

- Novi modul [`datamanager/mqtt_publisher.py`](datamanager/mqtt_publisher.py).
- Publikovanje **tek nakon uspešnog commit-a** u bazu, iz `Create` i `BatchCreate`.
- Greška u publikovanju se loguje i **ne obara gRPC poziv** — baza je izvor istine.
- Env: `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX`, `MQTT_QOS`, `MQTT_PUBLISH_ENABLED`, `MQTT_MAX_RATE`.

## EventManager

Pretplata na `iots/readings/+` (QoS 1, trajna sesija), primena pragova, objava događaja.

**Pragovi** ([`eventmanager/thresholds.json`](eventmanager/thresholds.json)) izvedeni su iz
stvarnog dataset-a (405.184 očitavanja):

| polje | p50 | p99 | max | prag | critical |
|---|---|---|---|---|---|
| temperature | 22.20 | 29.60 | 30.60 | 29.0 | 30.0 |
| humidity | 54.90 | 80.10 | 99.90 | 85.0 | 95.0 |
| co | 0.0048 | 0.0075 | 0.0144 | 0.0090 | 0.0120 |
| smoke | 0.0200 | 0.0282 | 0.0466 | 0.0300 | 0.0400 |

Uređaji imaju bitno različite opsege, pa postoji i **override po uređaju**: `b8:27:eb:bf:9d:51`
radi u opsegu 21–24 °C i nikada ne bi dostigao globalni prag, pa su mu pragovi spušteni
(23.5 °C / 60 % vlažnosti) da i on generiše događaje.

**Cooldown** (podrazumevano 60 s po kombinaciji uređaj + polje) sprečava poplavu identičnih
događaja: pri replay-u od 200 poruka/s isti senzor bi inače proizveo hiljade poruka u sekundi.
Podešava se preko `COOLDOWN_SECONDS`.

**Severity**: `WARNING` pri prekoračenju praga, `CRITICAL` pri prekoračenju `critical` vrednosti.

## MqttClient

Statička web aplikacija (MQTT.js preko WebSocket-a na 9001) koju servira nginx:
lista događaja uživo, brojači (ukupno / critical / warning / uređaja), filter po tekstu i
severity-ju, pauza i čišćenje, indikator stanja veze sa automatskim reconnect-om.

Broker se može promeniti preko query parametara:
`http://localhost:8081/?host=localhost&port=9001&topic=iots/events/%23`

## Napomena o dataset-u i demonstraciji

Prekoračenja pragova u dataset-u su **grupisana**, nisu ravnomerno raspoređena:
prvih 47.232 očitavanja nemaju **nijedno** prekoračenje, dok pojedini delovi datoteke imaju
preko 70 %. Zato SensorGenerator ima opciju `--offset` (env `OFFSET`), a Compose je podešen na
`OFFSET=194000` — najgušći deo datoteke — da bi demo odmah proizveo događaje.
Replay od početka datoteke je potpuno ispravan, ali ne generiše nijedan događaj.

## Testiranje

```bash
# očitavanja stižu na broker
docker exec iots2-mosquitto mosquitto_sub -h localhost -t 'iots/readings/#' -C 5 -v

# događaji
docker exec iots2-mosquitto mosquitto_sub -h localhost -t 'iots/events/#' -v

# ručno okidanje događaja preko REST-a
curl -X POST http://localhost:8080/api/v1/readings -H 'Content-Type: application/json' \
  -d '{"deviceId":"1c:bf:ce:15:ec:4d","ts":"2020-07-12T10:00:00Z","temperature":30.8,
       "humidity":50,"co":0.005,"smoke":0.02,"lat":43.3209,"lon":21.8958}'

# validacija AsyncAPI specifikacija
npx @asyncapi/cli validate asyncapi/datamanager.yaml
npx @asyncapi/cli validate asyncapi/eventmanager.yaml
```

REST/gRPC deo (Gateway, DataManager CRUD, agregacije) nepromenjen je u odnosu na Projekat 1 —
Postman kolekcija u [`postman/`](postman/) i dalje važi, kao i [`openapi.yaml`](openapi.yaml)
i [`proto/reading.proto`](proto/reading.proto).

## Struktura

```
project-2/
├── asyncapi/                     # AsyncAPI 3.1.0 specifikacije (zahtevi 1, 2, 5)
├── mosquitto/config/             # konfiguracija brokera (TCP + WebSocket)
├── datamanager/                  # + mqtt_publisher.py (zahtev 1)
├── eventmanager/                 # NOVO (zahtev 2)
├── mqtt-client/                  # NOVO — web aplikacija (zahtev 4)
├── gateway/, proto/, openapi.yaml, postman/   # nepromenjeno iz Projekta 1
├── sensor-generator/             # + koordinate po uređaju, --offset
└── docker-compose.yml            # svih 6 servisa (zahtev 3)
```

> Kontejneri su imenovani `iots2-*`, a image-i su tagovani `:2.0.0`, da bi Projekat 1 i
> Projekat 2 mogli da postoje jedan pored drugog bez sudara imena.
