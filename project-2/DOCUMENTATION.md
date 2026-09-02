# Projekat 2 — Dokumentacija

## 1. Namena projekta

Projekat 2 nadograđuje Projekat 1 **asinhronom komunikacijom preko MQTT-a** i detekcijom događaja:

1. **DataManager** pored upisa u bazu objavljuje svako očitavanje na MQTT topic.
2. Novi **EventManager** se pretplaćuje na taj topic, proverava vrednosti u odnosu na
   predefinisane pragove i, kada je prag prekoračen, objavljuje **događaj** na drugi topic.
3. **MqttClient** web aplikacija se pretplaćuje na topic sa događajima i prikazuje ih uživo.

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

Sve iz Projekta 1 (REST, gRPC, baza, agregacije) radi nepromenjeno.

## 2. Tehnologije i portovi

| Komponenta | Tehnologija | Port (host) |
|---|---|---|
| Mosquitto | eclipse-mosquitto:2 | **1883** (TCP), **9001** (WebSocket) |
| Gateway | Java 21 / Spring Boot 3.3 | **8080** |
| DataManager | Python 3.12 / grpcio + SQLAlchemy + **paho-mqtt** | **50051** |
| **EventManager** | **Python 3.12 / paho-mqtt** | **8000** (health) |
| **MqttClient** | **HTML/JS + MQTT.js, nginx** | **8081** |
| PostgreSQL | postgres:16-alpine | **5433** |

> WebSocket listener (9001) postoji jer se **iz pregledača ne može otvoriti sirov TCP MQTT**.

## 3. Struktura foldera

```
project-2/
├── asyncapi/
│   ├── datamanager.yaml       # NOVO - specifikacija kanala sa očitavanjima
│   └── eventmanager.yaml      # NOVO - kanali: ulaz očitavanja, izlaz događaji
├── mosquitto/config/
│   └── mosquitto.conf         # NOVO - TCP + WebSocket listener
├── datamanager/
│   └── mqtt_publisher.py      # NOVO - MQTT klijent i objavljivanje
├── eventmanager/              # NOVO mikroservis
│   ├── main.py                # pretplata, građenje i objava događaja
│   ├── rules.py               # pragovi, cooldown, severity
│   ├── health.py              # HTTP /health za Docker healthcheck
│   └── thresholds.json        # konfiguracija pragova
├── mqtt-client/               # NOVO - web aplikacija
│   ├── index.html, app.js, style.css, nginx.conf
├── gateway/, proto/, openapi.yaml, postman/    # nepromenjeno iz Projekta 1
├── sensor-generator/          # + koordinate po uređaju, opcija --offset
├── docker-compose.yml         # 6 servisa
├── README.md, PLAN.md, DOCUMENTATION.md
└── docs/run-docker-run.md
```

## 4. MQTT topic-i i format poruka

| Topic | Publikuje | Konzumira | QoS | Retain |
|---|---|---|---|---|
| `iots/readings/{deviceId}` | DataManager | EventManager (`iots/readings/+`) | 1 | ne |
| `iots/events/{deviceId}/{field}` | EventManager | MqttClient (`iots/events/#`) | 1 | ne |

**Očitavanje:**
```json
{ "id": 12345, "deviceId": "b8:27:eb:bf:9d:51", "ts": "2020-07-12T00:01:34Z",
  "temperature": 22.7, "humidity": 51.0, "co": 0.0049, "smoke": 0.0204,
  "location": { "lat": 44.8125, "lon": 20.4612 } }
```

**Događaj** (nosi tip, vrednosti, lokaciju i vreme):
```json
{ "eventId": "1c:bf:ce:15:ec:4d-temperature-4", "type": "THRESHOLD_EXCEEDED",
  "severity": "CRITICAL", "deviceId": "1c:bf:ce:15:ec:4d", "field": "temperature",
  "value": 30.4, "unit": "C", "threshold": 29.0, "operator": "gt", "exceededBy": 1.4,
  "readingId": 4, "readingTs": "2020-07-12T00:01:34Z",
  "detectedAt": "2026-09-02T07:01:35Z", "location": { "lat": 44.8125, "lon": 20.4612 } }
```

Specifikacije: [`asyncapi/datamanager.yaml`](asyncapi/datamanager.yaml) i
[`asyncapi/eventmanager.yaml`](asyncapi/eventmanager.yaml) (AsyncAPI 3.1.0).

## 5. Kako radi DataManager posle izmene

- Objavljuje **tek nakon uspešnog commit-a** u bazu (baza je izvor istine).
- Greška u objavljivanju se **loguje i ne obara gRPC poziv** — ako broker padne, upis u bazu i
  dalje uspeva.
- Objavljuje i iz `Create` i iz `BatchCreate`.
- Podešavanje: `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX`, `MQTT_QOS`,
  `MQTT_PUBLISH_ENABLED`, `MQTT_MAX_RATE`.

## 6. Kako radi EventManager

Pretplata na `iots/readings/+` (QoS 1, trajna sesija), primena pravila, objava događaja.

### Pragovi

Konfiguracija: [`eventmanager/thresholds.json`](eventmanager/thresholds.json).
Vrednosti su izvedene iz **stvarnog dataset-a** (405.184 očitavanja):

| polje | p50 | p99 | max | prag | critical |
|---|---|---|---|---|---|
| temperature | 22,20 | 29,60 | 30,60 | 29,0 | 30,0 |
| humidity | 54,90 | 80,10 | 99,90 | 85,0 | 95,0 |
| co | 0,0048 | 0,0075 | 0,0144 | 0,0090 | 0,0120 |
| smoke | 0,0200 | 0,0282 | 0,0466 | 0,0300 | 0,0400 |

**Override po uređaju.** Uređaji imaju bitno različite opsege: `b8:27:eb:bf:9d:51` radi na
21–24 °C i **nikad** ne bi dostigao globalni prag, dok `1c:bf:ce:15:ec:4d` daje većinu događaja.
Zato taj uređaj ima spuštene pragove (23,5 °C / 60 % vlažnosti) da bi i on generisao događaje.

**Severity:** `WARNING` pri prekoračenju praga, `CRITICAL` pri prekoračenju `critical` vrednosti.

**Cooldown** (podrazumevano 60 s po kombinaciji uređaj + polje) sprečava poplavu identičnih
događaja — pri replay-u od 200 poruka/s isti senzor bi inače proizveo hiljade poruka u sekundi.
Menja se preko `COOLDOWN_SECONDS`.

## 7. MqttClient

Statička web aplikacija (MQTT.js preko WebSocket-a), koju servira nginx: lista događaja uživo,
brojači (ukupno / critical / warning / uređaja), filter po tekstu i po severity-ju, pauza,
čišćenje i indikator stanja veze sa automatskim reconnect-om.

Broker se može promeniti preko query parametara:
```
http://localhost:8081/?host=localhost&port=9001&topic=iots/events/%23
```

## 8. Pokretanje

```bash
cd project-2
docker compose up --build -d
docker compose ps                 # svih 6 servisa treba da bude (healthy)
```

Replay podataka (puni bazu, pokreće događaje):
```bash
docker compose --profile tools run --rm generator
```

Linkovi:
- MqttClient: <http://localhost:8081>
- Swagger UI: <http://localhost:8080/swagger-ui.html>
- EventManager health: <http://localhost:8000/health>

Gašenje:
```bash
docker compose --profile tools down -v
```

Pojedinačne `docker run` komande: [`docs/run-docker-run.md`](docs/run-docker-run.md).

## 9. Testiranje

### 9.1 Očitavanja stižu na broker
```bash
docker exec iots2-mosquitto mosquitto_sub -h localhost -t 'iots/readings/#' -C 5 -v
```
U drugom terminalu pošaljite očitavanje (vidi 9.3). Očekivano: 5 poruka sa `iots/readings/…`.

### 9.2 Događaji se generišu
```bash
docker exec iots2-mosquitto mosquitto_sub -h localhost -t 'iots/events/#' -v
```

### 9.3 Ručno okidanje događaja
```bash
# CRITICAL: temperatura 30.8 > critical prag 30.0
curl -X POST http://localhost:8080/api/v1/readings -H 'Content-Type: application/json' \
  -d '{"deviceId":"1c:bf:ce:15:ec:4d","ts":"2020-07-12T10:00:00Z","temperature":30.8,
       "humidity":50,"co":0.005,"smoke":0.02,"lat":43.3209,"lon":21.8958}'
```
Očekivano: u roku od sekunde događaj na `iots/events/1c:bf:ce:15:ec:4d/temperature`
i novi red u MqttClient-u.

### 9.4 Provera cooldown-a
Pošaljite isti zahtev **dva puta zaredom**. Očekivano: **samo jedan** događaj — drugi je
blokiran cooldown-om (60 s po kombinaciji uređaj + polje).

### 9.5 Provera per-device override-a
```bash
# 23.8 > 23.5 (prag samo za ovaj uredjaj); na globalnim pragovima ne bi okinulo
curl -X POST http://localhost:8080/api/v1/readings -H 'Content-Type: application/json' \
  -d '{"deviceId":"b8:27:eb:bf:9d:51","ts":"2020-07-12T10:00:10Z","temperature":23.8,
       "humidity":50,"co":0.005,"smoke":0.02,"lat":44.8125,"lon":20.4612}'
```

### 9.6 Statistika EventManager-a
```bash
curl -s http://localhost:8000/health
```
Vraća `readings_seen` i `events_published` — koristi se da se vidi da li servis uopšte prima poruke.

### 9.7 Validacija AsyncAPI specifikacija
```bash
npx @asyncapi/cli validate asyncapi/datamanager.yaml
npx @asyncapi/cli validate asyncapi/eventmanager.yaml
```
Očekivano: `is valid!` bez grešaka.

### 9.8 Regresija Projekta 1
REST i gRPC deo nije menjan — Postman kolekcija u [`postman/`](postman/) i dalje važi
(vidi `DOCUMENTATION.md` Projekta 1, odeljak 7).

## 10. Napomene i česti problemi

**Replay ne proizvodi nijedan događaj.** To je očekivano ako se kreće od početka datoteke:
prekoračenja u dataset-u su **grupisana**, prvih 47.232 očitavanja nemaju **nijedno**
prekoračenje, dok pojedini delovi imaju preko 70 %. Zato generator ima opciju `--offset`
(env `OFFSET`), a Compose je podešen na `OFFSET=194000` — najgušći deo datoteke.
Replay od početka je ispravan, samo „tih".

**Mali broj događaja pri replay-u.** Pri 4000 očitavanja tipično se vidi svega nekoliko
događaja — to je **cooldown**, ne greška: najviše jedan događaj po kombinaciji uređaj + polje
u 60 s.

**MqttClient piše „nije povezan".** Proverite da je Mosquitto podignut i da je port 9001 mapiran
(`docker compose ps`). Iz pregledača se koristi **WebSocket** (9001), ne 1883.

**Sudar imena kontejnera.** Kontejneri su `iots2-*`, a image-i `:2.0.0`, da ne bi došlo do
sudara sa Projektom 1. Ipak, portovi su isti, pa ne treba pokretati oba projekta istovremeno.
