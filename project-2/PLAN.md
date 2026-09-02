# Projekat 2 — Plan implementacije

Nadogradnja na Projekat 1: DataManager pored upisa u bazu **publikuje očitavanja na MQTT topic**,
novi **EventManager** ih konzumira, detektuje prekoračenja pragova i objavljuje **događaje** na drugi
topic, a **MqttClient** ih prikazuje.

```
SensorGenerator ─REST→ Gateway ─gRPC→ DataManager ─SQL→ PostgreSQL
                                          │
                                          └─MQTT publish→ iots/readings/{deviceId}
                                                                │
                                                        Mosquitto broker
                                                                │
                                          EventManager ─subscribe┘
                                                │
                                                └─MQTT publish→ iots/events/{deviceId}/{field}
                                                                        │
                                                            MqttClient (web, WebSocket)
```

## 0. Polazna tačka i struktura

`project-1/` se **kopira** u `project-2/` i proširuje (Projekat 1 ostaje zamrznut kakav je predat).

```
project-2/
├── proto/reading.proto              # nepromenjeno
├── openapi.yaml                     # nepromenjeno
├── asyncapi/
│   ├── datamanager.yaml             # NOVO — publikuje očitavanja
│   └── eventmanager.yaml            # NOVO — konzumira očitavanja, publikuje događaje
├── gateway/                         # nepromenjeno
├── datamanager/                     # + MQTT publisher
│   └── mqtt_publisher.py            # NOVO
├── eventmanager/                    # NOVO mikroservis
│   ├── main.py, rules.py, health.py
│   └── thresholds.json, Dockerfile
├── mqtt-client/                     # NOVO — web aplikacija
│   ├── index.html, app.js, style.css, nginx.conf, Dockerfile
├── mosquitto/
│   └── config/mosquitto.conf        # NOVO — TCP 1883 + WebSocket 9001
├── sensor-generator/                # + sintetičke koordinate
├── postman/, docs/, docker-compose.yml, README.md
```

## 1. MQTT broker (zahtev 3)

**Mosquitto 2** (`eclipse-mosquitto:2`) kao Docker servis. Konfiguracija:
```
listener 1883                # TCP — mikroservisi
protocol mqtt
listener 9001                # WebSocket — MqttClient u pregledaču
protocol websockets
allow_anonymous true         # samo za razvoj/demonstraciju
persistence true
persistence_location /mosquitto/data/
```
Healthcheck: `mosquitto_sub -t '$SYS/#' -C 1 -W 3`.

> WebSocket listener je neophodan jer se iz pregledača ne može otvoriti sirov TCP MQTT.

## 2. Topic-i i format poruka

| Topic | Ko publikuje | Ko sluša | QoS | Retain |
|---|---|---|---|---|
| `iots/readings/{deviceId}` | DataManager | EventManager | 1 | ne |
| `iots/events/{deviceId}/{field}` | EventManager | MqttClient | 1 | ne |

Wildcard pretplate: EventManager na `iots/readings/+`, MqttClient na `iots/events/#`.
`deviceId` sadrži `:` (MAC adresa) — dozvoljeno u MQTT topic-u, ali se **`/` i `+` moraju izbeći**;
MAC adrese ih nemaju, pa se koristi kakav jeste.

**Poruka očitavanja** (`iots/readings/{deviceId}`):
```json
{
  "id": 12345, "deviceId": "b8:27:eb:bf:9d:51", "ts": "2020-07-12T00:01:34Z",
  "temperature": 22.7, "humidity": 51.0, "co": 0.0049, "smoke": 0.0204,
  "location": { "lat": 44.8125, "lon": 20.4612 }
}
```

**Poruka događaja** (`iots/events/{deviceId}/{field}`):
```json
{
  "eventId": "b8:27:eb:bf:9d:51-temperature-1594512094",
  "type": "THRESHOLD_EXCEEDED",
  "severity": "WARNING",
  "deviceId": "b8:27:eb:bf:9d:51",
  "field": "temperature",
  "value": 30.4,
  "threshold": 29.0,
  "operator": "gt",
  "exceededBy": 1.4,
  "readingId": 12345,
  "readingTs": "2020-07-12T00:01:34Z",
  "detectedAt": "2026-09-02T01:15:22Z",
  "location": { "lat": 44.8125, "lon": 20.4612 }
}
```
Pokriva sve što zahtev 2 traži: **tip, vrednosti, lokacija, vreme**.

## 3. Izmena DataManager-a (zahtev 1)

- Novi modul `mqtt_publisher.py`: `paho-mqtt` klijent, `loop_start()` u pozadinskoj niti,
  `client_id=datamanager-{hostname}`, automatski reconnect, `max_inflight_messages`.
- Publikovanje **posle uspešnog commit-a** u `Create` i `BatchCreate` (nikad pre — u bazi je izvor istine).
- **Neblokirajuće**: greška u publikovanju se loguje i ne obara gRPC poziv (baza je već upisala).
- `BatchCreate` publikuje svaku poruku pojedinačno, ali kroz isti klijent; kod velikih serija
  postoji `MQTT_PUBLISH_ENABLED` i `MQTT_MAX_RATE` da se izbegne zagušenje brokera.
- Nove env varijable: `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC_PREFIX`, `MQTT_QOS`, `MQTT_PUBLISH_ENABLED`.

## 4. EventManager (zahtev 2)

- Pretplata na `iots/readings/+`, QoS 1, `clean_session=false` + trajni `client_id`
  (da se poruke ne gube pri restartu).
- Za svako očitavanje primenjuje pravila iz `thresholds.json`; za svako prekoračenje publikuje
  događaj na `iots/events/{deviceId}/{field}`.
- **Anti-flood**: cooldown po `(deviceId, field)` — podrazumevano 60 s. Bez toga bi replay
  dataset-a pri 200 poruka/s proizveo hiljade identičnih događaja u sekundi.
- **Severity**: `WARNING` pri prekoračenju praga, `CRITICAL` pri prekoračenju `criticalThreshold`.
- Mali HTTP `/health` endpoint (nit sa `http.server`) da Compose ima healthcheck.

**Pragovi izračunati iz stvarnog dataset-a** (405.184 očitavanja):

| polje | p50 | p95 | p99 | max | **prag** | okida |
|---|---|---|---|---|---|---|
| temperature | 22.20 | 28.00 | 29.60 | 30.60 | **29.0** | 2.24 % |
| humidity | 54.90 | 77.40 | 80.10 | 99.90 | **85.0** | 0.61 % |
| co | 0.0048 | 0.0062 | 0.0075 | 0.0144 | **0.0090** | 0.31 % |
| smoke | 0.0200 | 0.0244 | 0.0282 | 0.0466 | **0.0300** | 0.58 % |

Ukupno **3,44 %** očitavanja okida bar jedan događaj — dovoljno da demo bude živ, a ne poplava.

> Napomena: uređaji imaju bitno različite opsege (`b8:27:eb:bf:9d:51` ima temp 21–24 °C i
> **nikad** ne prelazi globalne pragove, dok `1c:bf:ce:15:ec:4d` daje 83 % svih događaja).
> `thresholds.json` zato podržava i **override po uređaju**, da se u demou vidi događaj i sa
> „mirnog" uređaja.

## 5. Lokacija podataka

Kaggle dataset **nema** koordinate, a zahtev 2 traži lokaciju u događaju. Rešenje:
SensorGenerator dodeljuje **determinističke koordinate po uređaju** (mapa `device → (lat, lon)`,
tri grada u Srbiji), pa lokacija kroz ceo lanac (REST → gRPC → baza → MQTT → događaj) nosi
stvarnu vrednost. Kolone `lat`/`lon` već postoje u bazi i u `.proto` iz Projekta 1.

## 6. MqttClient (zahtev 4)

Web aplikacija (statički HTML/JS + **MQTT.js** preko WebSocket-a na port 9001), servirana
`nginx:alpine` kontejnerom na portu **8081**:
- Pretplata na `iots/events/#`, live lista događaja (najnoviji na vrhu, do 200).
- Bojenje po `severity`, filter po uređaju i polju, brojači, dugme za pauzu/čišćenje.
- Prikaz statusa konekcije i reconnect.

## 7. AsyncAPI specifikacije (zahtevi 1, 2, 5)

**AsyncAPI 3.0.0**, dva dokumenta:
- `asyncapi/datamanager.yaml` — server `mosquitto` (mqtt://), kanal
  `iots/readings/{deviceId}` sa parametrom, operacija `send`, `ReadingMessage` šema.
- `asyncapi/eventmanager.yaml` — operacija `receive` na `iots/readings/{deviceId}` i
  `send` na `iots/events/{deviceId}/{field}`, `EventMessage` šema.
Validacija: `npx @asyncapi/cli validate asyncapi/*.yaml`.

## 8. Docker Compose (zahtev 3)

Servisi: `mosquitto`, `db`, `datamanager`, `gateway`, `eventmanager`, `mqtt-client`, `generator` (profil `tools`).
Zavisnosti preko healthcheck-ova: `mosquitto` + `db` → `datamanager` → `gateway`;
`mosquitto` → `eventmanager`. Portovi: 8080 gateway, 8081 MqttClient, 1883/9001 broker,
50051 gRPC, 5433 Postgres (kao u Projektu 1).

## 9. Testiranje

1. `mosquitto_sub -t 'iots/readings/#' -C 5` — očitavanja stižu na broker.
2. `mosquitto_sub -t 'iots/events/#'` — događaji se generišu.
3. Ručni okidač: `POST /api/v1/readings` sa `temperature: 99` → događaj u MqttClient-u za < 1 s.
4. Generator replay → provera da je broj događaja u očekivanom opsegu (~3,4 % očitavanja).
5. Cooldown: dva prekoračenja u istoj sekundi → samo jedan događaj.
6. Restart EventManager-a → nastavlja da prima (perzistentna sesija).

## 10. Redosled rada

1. Kopiranje `project-1` → `project-2` i provera da postojeći stack i dalje radi.
2. Mosquitto u Compose + provera oba listener-a (TCP i WebSocket).
3. Koordinate po uređaju u SensorGenerator-u.
4. `mqtt_publisher.py` + integracija u DataManager → provera `mosquitto_sub`-om.
5. `asyncapi/datamanager.yaml`.
6. EventManager (pravila, cooldown, severity, health) → provera događaja.
7. `asyncapi/eventmanager.yaml`.
8. MqttClient web aplikacija.
9. Kompletan Compose stack + end-to-end provera.
10. README (opis mikroservisa, topic-a, pragova) + push na GitHub.

## Otvorena pitanja za odluku

1. **Tehnologija EventManager-a** — predlog Python (paho-mqtt), radi konzistentnosti sa
   DataManager-om; Node.js je alternativa ako se želi još jedna tehnologija u portfoliju.
   (Zahtev 3 ovde *ne* traži dve različite tehnologije, za razliku od Projekta 1.)
2. **MqttClient** — predlog web (MQTT.js + WebSocket), jer ne traži instalaciju i lako se
   demonstrira; alternativa je desktop aplikacija.
3. **Pragovi** — globalni (gore) ili i override po uređaju da i „mirni" uređaj generiše događaje.
