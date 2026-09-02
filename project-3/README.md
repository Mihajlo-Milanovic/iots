# IoTS — Projekat 3: Analytics, MLaaS i NATS

Nadogradnja Projekta 2. Novi **Analytics** mikroservis sluša MQTT topic sa očitavanjima,
za analizu koristi **MLaaS** (Python + FastAPI + scikit-learn) preko REST-a, a rezultate modela
objavljuje na **NATS** subject. Klijent iz Projekta 2 proširen je u **MqttNats** i prikazuje
i događaje (MQTT) i predikcije (NATS).

```
DataManager ─publish→ iots/readings/{deviceId}  (MQTT / Mosquitto)
                             │
                  ┌──────────┴───────────┐
            EventManager              Analytics ──REST /predict──→ MLaaS (FastAPI + sklearn)
                  │                        │
       iots/events/… (MQTT)                └─publish→ iots.analytics.predictions.{deviceId}
                  │                                            (NATS)
                  └──────────────┬─────────────────────────────────┘
                            MqttNats (web): MQTT/WS + NATS/WS
```

| Komponenta | Tehnologija | Port |
|---|---|---|
| **MLaaS** | **Python 3.12 / FastAPI + scikit-learn** | **8002** |
| **Analytics** | **Python 3.12 / paho-mqtt + nats-py + httpx** | **8003 (health)** |
| **NATS** | **nats:2-alpine** | **4222 (TCP), 9222 (WS), 8222 (monitoring)** |
| **MqttNats** | **HTML/JS + MQTT.js + nats.ws, nginx** | **8081** |
| Mosquitto | eclipse-mosquitto:2 | 1883, 9001 |
| Gateway / DataManager / EventManager / PostgreSQL | iz Projekta 2 | 8080 / 50051 / 8000 / 5433 |

## Pokretanje

```bash
cd project-3
docker compose up --build -d                          # svih 9 servisa
docker compose --profile tools run --rm generator     # replay podataka
```
- MqttNats klijent: <http://localhost:8081>
- MLaaS Swagger: <http://localhost:8002/docs> · metrike: <http://localhost:8002/model/info>
- Analytics health: <http://localhost:8003/health>

> Prvi build traje duže jer se **model trenira u toku Docker build-a** (~4 s trening,
> ostatak je instalacija scikit-learn-a).

## ML model (zahtev 2)

**Zadatak: višeklasna klasifikacija uređaja** — na osnovu očitavanja i agregata kliznog prozora
predviđa se sa kog je od tri senzora podatak došao.

Izbor zadatka nije proizvoljan — izmereno je koliko je koji kandidat zapravo težak na ovim podacima:

| kandidat | merenje | zaključak |
|---|---|---|
| regresija: temperatura H koraka unapred | naivni „poslednja vrednost" baseline: MAE **0,17–0,24 °C** i na 120 uzoraka unapred | model jedva nadmašuje trivijalan baseline |
| klasifikacija: sledi li prekoračenje praga | naivno pravilo „već je u prekoračenju": **P=1,00 / R=0,90–0,97** | zadatak degenerisan |
| **klasifikacija uređaja** | baseline (većinska klasa) **46,05 %** → model **99,71 %** | jasan doprinos modela — izabrano |

**Metodologija:**
- **Hronološki** 80/20 split, ne slučajni — serija je jako autokorelisana (lag-1 do 0,996),
  pa bi slučajni split procurio informaciju iz budućnosti.
- Uvek se izveštava i baseline većinske klase, i per-klasa metrike, ne samo ukupna tačnost.
- `RandomForestClassifier` (120 stabala, `class_weight="balanced"`) u `Pipeline`-u sa `StandardScaler`-om.
- 149.967 uzoraka (119.973 trening / 29.994 test), 14 atributa, prozor 12 uzoraka (~60 s).

**Atributi** — trenutne vrednosti (`temperature`, `humidity`, `co`, `smoke`) + agregati prozora
(`mean`, `std`, `min`, `max`, `slope`) za temperaturu i vlažnost.

> `features.py` je **deljen između treninga i serviranja** (isti fajl koristi i MLaaS i Analytics),
> čime se izbegava training/serving skew. Iz istog razloga je iz atributa **izbačen `lpg`**:
> postoji u CSV-u, ali ga MQTT poruka ne nosi, pa bi ga model u produkciji uvek video kao nulu.

**Rezultati** (`GET /model/info` vraća ceo izveštaj):

| metrika | vrednost |
|---|---|
| tačnost | **0,9971** |
| macro-F1 | **0,9971** |
| baseline (većinska klasa) | 0,4605 |

| klasa | precision | recall | F1 | n |
|---|---|---|---|---|
| `00:0f:00:70:91:0a` | 1,0000 | 1,0000 | 1,0000 | 8337 |
| `1c:bf:ce:15:ec:4d` | 0,9892 | 1,0000 | 0,9945 | 7846 |
| `b8:27:eb:bf:9d:51` | 1,0000 | 0,9938 | 0,9969 | 13811 |

Najvažniji atributi: `temperature_max` (0,190), `temperature` (0,166), `temperature_mean` (0,160),
`temperature_min` (0,121), `co` (0,077), `humidity_max` (0,075).

### REST endpointi MLaaS-a

| metod | putanja | opis |
|---|---|---|
| GET | `/health` | status servisa, da li je model učitan |
| GET | `/model/info` | metrike, atributi, klase, confusion matrix, datum treninga |
| POST | `/predict` | jedan feature vektor (14 vrednosti) → predikcija + verovatnoće |
| POST | `/predict/window` | sirov klizni prozor očitavanja (servis sam gradi vektor) |
| POST | `/predict/batch` | više vektora odjednom |
| GET | `/docs` | Swagger UI (FastAPI) |

```bash
curl -X POST http://localhost:8002/predict -H 'Content-Type: application/json' \
  -d '{"features":[22.7,51.0,0.0049,0.0204,22.5,0.2,22.1,22.9,0.01,51.2,0.5,50.1,52.0,-0.02]}'
```

## Analytics (zahtevi 1 i 3)

1. Pretplata na `iots/readings/+` (QoS 1, trajna sesija).
2. Klizni prozor po uređaju (12 uzoraka).
3. **Throttling**: MLaaS se poziva najviše jednom po uređaju u `PREDICT_INTERVAL` (2 s).
   Mereno pri replay-u: **4000 očitavanja → 30 predikcija** (1 na 133 očitavanja) umesto
   4000 HTTP poziva.
4. **Otpornost**: ako MLaaS padne, Analytics loguje grešku i nastavlja da radi
   (`mlaas_reachable: false` u health-u); po povratku MLaaS-a automatski nastavlja.
5. Objava na NATS subject `iots.analytics.predictions.{deviceId}`.

> NATS koristi tačku kao separator nivoa, pa se dvotačke iz MAC adrese zamenjuju crticom:
> `b8:27:eb:bf:9d:51` → `iots.analytics.predictions.b8-27-eb-bf-9d-51`.

**Poruka predikcije:**
```json
{ "predictionId": "1c:bf:ce:15:ec:4d-12", "deviceId": "1c:bf:ce:15:ec:4d",
  "modelTask": "device_classification", "prediction": "1c:bf:ce:15:ec:4d",
  "confidence": 1.0, "probabilities": { "…": 0.0 }, "correct": true,
  "windowSize": 12, "features": { "temperature_mean": 30.2083, "…": 0 },
  "readingId": 12, "readingTs": "2020-07-12T12:00:00Z",
  "predictedAt": "2026-09-02T09:49:13Z", "latencyMs": 64.8,
  "location": { "lat": 44.8, "lon": 20.4 } }
```
Polje `correct` postoji jer je stvarni uređaj poznat iz MQTT topic-a — koristi se **isključivo za
evaluaciju uživo** u klijentu, nije ulaz u model.

Specifikacija: [`asyncapi/analytics.yaml`](asyncapi/analytics.yaml) (AsyncAPI 3.1.0, prolazi
`npx @asyncapi/cli validate` bez grešaka), pored specifikacija iz Projekta 2.

## MqttNats klijent (zahtev 4)

Dve nezavisne konekcije i dva taba:
- **Događaji** — MQTT preko WebSocket-a (9001), `iots/events/#` (kao u Projektu 2).
- **Predikcije** — NATS preko WebSocket-a (9222), `iots.analytics.predictions.>`:
  tabela sa stvarnim i predviđenim uređajem, trakom pouzdanosti, ishodom i latencijom,
  plus zbirni panel (broj predikcija, **tačnost uživo**, prosečna pouzdanost i latencija).

JS biblioteke (`mqtt.js`, `nats.ws`) su **ugrađene u image** (`vendor/`), ne učitavaju se sa CDN-a,
pa demonstracija radi i bez pristupa internetu.

Parametri preko query stringa:
`http://localhost:8081/?host=localhost&port=9001&natsHost=localhost&natsPort=9222`

## Testiranje

```bash
# metrike modela
curl -s http://localhost:8002/model/info | python3 -m json.tool

# predikcije na NATS-u
docker run --rm --network project-3_iots-net natsio/nats-box:latest \
  nats sub -s nats://nats:4222 'iots.analytics.predictions.>'

# otpornost: Analytics preživljava pad MLaaS-a
docker compose stop mlaas && curl -s http://localhost:8003/health   # mlaas_reachable: false
docker compose start mlaas                                          # automatski nastavlja

# validacija AsyncAPI specifikacija
npx @asyncapi/cli validate asyncapi/analytics.yaml
```

Provereno: 19/19 (REST/gRPC iz Projekta 1, MQTT događaji iz Projekta 2, MLaaS/Analytics/NATS
iz Projekta 3), uz replay dataset-a i test otpornosti.

## Struktura

```
project-3/
├── mlaas/                     # FastAPI + sklearn (zahtev 2)
│   ├── features.py            # DELJENO izvlačenje atributa (trening + serviranje)
│   ├── train.py               # trening, hronološki split, metrics.json
│   ├── app.py                 # REST endpointi
│   └── model/                 # model.joblib + metrics.json (nastaje u build-u)
├── analytics/                 # MQTT → prozor → MLaaS → NATS (zahtevi 1, 3)
├── nats/nats-server.conf      # NATS sa WebSocket listener-om
├── mqtt-nats-client/          # web klijent sa dva taba (zahtev 4)
├── asyncapi/                  # datamanager, eventmanager, analytics
├── (gateway, datamanager, eventmanager, mosquitto, sensor-generator … iz Projekta 2)
└── docker-compose.yml         # 9 servisa (zahtev 5)
```

> Kontejneri su imenovani `iots3-*`, image-i tagovani `:3.0.0` — sva tri projekta mogu da
> postoje jedan pored drugog bez sudara imena i portova.
