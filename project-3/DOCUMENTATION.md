# Projekat 3 — Dokumentacija

## 1. Namena projekta

Projekat 3 nadograđuje Projekat 2 **mašinskim učenjem i drugim message broker-om**:

1. **Analytics** mikroservis se pretplaćuje na MQTT topic sa očitavanjima (koji puni DataManager),
   održava klizni prozor po uređaju i za analizu koristi **MLaaS** preko REST-a.
2. **MLaaS** (Python + FastAPI + scikit-learn) servira istrenirani ML model preko REST endpointa.
3. Rezultat modela Analytics objavljuje na **NATS** subject.
4. **MqttNats** (proširen klijent iz Projekta 2) pretplaćuje se i na NATS i prikazuje predikcije.

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

Sve iz Projekata 1 i 2 radi nepromenjeno.

## 2. Tehnologije i portovi

| Komponenta | Tehnologija | Port (host) |
|---|---|---|
| **MLaaS** | **Python 3.12 / FastAPI + scikit-learn** | **8002** |
| **Analytics** | **Python 3.12 / paho-mqtt + nats-py + httpx** | **8003** (health) |
| **NATS** | **nats:2-alpine** | **4222** (TCP), **9222** (WS), **8222** (monitoring) |
| **MqttNats** | **HTML/JS + MQTT.js + nats.ws, nginx** | **8081** |
| Mosquitto | eclipse-mosquitto:2 | 1883, 9001 |
| Gateway / DataManager / EventManager / PostgreSQL | iz Projekta 2 | 8080 / 50051 / 8000 / 5433 |

> I NATS ima **WebSocket listener** (9222) — bez njega se aplikacija iz pregledača ne može
> pretplatiti na NATS subject.

## 3. Struktura foldera

```
project-3/
├── mlaas/                     # ML kao servis (zahtev 2)
│   ├── features.py            # DELJENO izvlačenje atributa: trening + serviranje
│   ├── train.py               # trening, hronološki split, metrics.json
│   ├── app.py                 # FastAPI REST endpointi
│   ├── model/                 # model.joblib + metrics.json (nastaje u toku build-a)
│   └── Dockerfile             # trenira model u toku build-a
├── analytics/                 # MQTT → prozor → MLaaS → NATS (zahtevi 1 i 3)
│   ├── main.py                # glavna petlja, poziv MLaaS-a, objava na NATS
│   ├── window.py              # klizni prozor po uređaju + throttling
│   └── health.py              # HTTP /health sa statistikom
├── nats/nats-server.conf      # NATS sa WebSocket listener-om
├── mqtt-nats-client/          # web klijent sa dva taba (zahtev 4)
│   ├── index.html, app.js (MQTT), nats-app.js (NATS), style.css
│   └── vendor/                # ugrađene JS biblioteke (rade i bez interneta)
├── asyncapi/
│   ├── analytics.yaml         # NOVO - NATS kanal sa predikcijama
│   ├── datamanager.yaml, eventmanager.yaml     # iz Projekta 2
├── (gateway, datamanager, eventmanager, mosquitto, sensor-generator … iz Projekta 2)
├── docker-compose.yml         # 9 servisa
└── README.md, PLAN.md, DOCUMENTATION.md
```

## 4. ML model

### 4.1 Zašto baš ovaj zadatak

Pre izbora modela izmereno je koliko je koji kandidat **zaista** težak na ovim podacima:

| kandidat | merenje | zaključak |
|---|---|---|
| regresija: temperatura H koraka unapred | naivni „poslednja vrednost" baseline daje MAE **0,17–0,24 °C** i 120 uzoraka unapred | model jedva nadmašuje trivijalan baseline |
| klasifikacija: sledi li prekoračenje praga | naivno pravilo „već je u prekoračenju": **P=1,00 / R=0,90–0,97** | zadatak degenerisan |
| **klasifikacija uređaja** | baseline (većinska klasa) **46,05 %** → model **99,71 %** | jasan doprinos modela — **izabrano** |

**Zadatak: višeklasna klasifikacija uređaja** — na osnovu očitavanja i agregata kliznog prozora
predviđa se sa kog je od tri senzora podatak došao.

### 4.2 Metodologija

- **Hronološki 80/20 split**, ne slučajni: serija je jako autokorelisana (lag-1 do 0,996), pa bi
  slučajni split procurio informaciju iz budućnosti i dao nerealno dobar rezultat.
- Uz tačnost se **uvek** izveštava i baseline većinske klase, i per-klasa precision/recall.
- `RandomForestClassifier` (120 stabala, `class_weight="balanced"`) u `Pipeline`-u sa `StandardScaler`-om.
- 149.967 uzoraka (119.973 trening / 29.994 test), 14 atributa, prozor 12 uzoraka (~60 s).

### 4.3 Atributi

Trenutne vrednosti (`temperature`, `humidity`, `co`, `smoke`) + agregati prozora
(`mean`, `std`, `min`, `max`, `slope`) za temperaturu i vlažnost.

> [`mlaas/features.py`](mlaas/features.py) je **deljen između treninga i serviranja** — isti fajl
> koristi i MLaaS i Analytics (Docker build ga kopira u oba image-a), čime se izbegava
> training/serving skew. Iz istog razloga je iz atributa **izbačen `lpg`**: postoji u CSV-u, ali
> ga MQTT poruka ne nosi, pa bi ga model u produkciji uvek video kao nulu.

### 4.4 Rezultati

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

Ceo izveštaj (uz confusion matrix i važnost atributa) vraća `GET /model/info`.

## 5. MLaaS REST API

| Metod | Putanja | Opis |
|---|---|---|
| `GET` | `/health` | status servisa, da li je model učitan |
| `GET` | `/model/info` | metrike, atributi, klase, confusion matrix, datum treninga |
| `POST` | `/predict` | jedan feature vektor (14 vrednosti) → predikcija + verovatnoće |
| `POST` | `/predict/window` | sirov klizni prozor očitavanja (servis sam gradi vektor) |
| `POST` | `/predict/batch` | više vektora odjednom |
| `GET` | `/docs` | Swagger UI (FastAPI generiše automatski) |

## 6. Analytics

1. Pretplata na `iots/readings/+` (QoS 1, trajna sesija).
2. Klizni prozor po uređaju (12 uzoraka); predikcija tek kad se prozor napuni.
3. **Throttling**: MLaaS se poziva najviše jednom po uređaju u `PREDICT_INTERVAL` (2 s).
   Bez toga bi replay od 200 poruka/s pravio stotine HTTP poziva u sekundi.
4. **Otpornost**: ako MLaaS padne, Analytics loguje grešku i nastavlja da radi; kada se MLaaS
   vrati, automatski nastavlja da objavljuje.
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

Polje `correct` postoji jer je stvarni uređaj poznat iz MQTT topic-a. Koristi se **isključivo za
evaluaciju uživo** u klijentu — **nije ulaz u model**.

Specifikacija: [`asyncapi/analytics.yaml`](asyncapi/analytics.yaml) (AsyncAPI 3.1.0).

## 7. MqttNats klijent

Dve nezavisne konekcije i dva taba:
- **Događaji** — MQTT preko WebSocket-a (9001), `iots/events/#` (kao u Projektu 2).
- **Predikcije** — NATS preko WebSocket-a (9222), `iots.analytics.predictions.>`: tabela sa
  stvarnim i predviđenim uređajem, trakom pouzdanosti, ishodom i latencijom, plus zbirni panel
  (broj predikcija, **tačnost uživo**, prosečna pouzdanost i latencija).

JS biblioteke su **ugrađene u image** (`mqtt-nats-client/vendor/`), ne učitavaju se sa CDN-a,
pa demonstracija radi i bez pristupa internetu.

Parametri preko query stringa:
```
http://localhost:8081/?host=localhost&port=9001&natsHost=localhost&natsPort=9222
```

## 8. Pokretanje

```bash
cd project-3
docker compose up --build -d
docker compose ps                # svih 9 servisa treba da bude (healthy)
```

> **Prvi build traje duže** nego u ranijim projektima: instalira se scikit-learn i **model se
> trenira u toku Docker build-a** (sam trening je ~4 s, instalacija je duža).

Replay podataka:
```bash
docker compose --profile tools run --rm generator
```

Linkovi:
- MqttNats klijent: <http://localhost:8081>
- MLaaS Swagger: <http://localhost:8002/docs>
- Metrike modela: <http://localhost:8002/model/info>
- Analytics health: <http://localhost:8003/health>
- NATS monitoring: <http://localhost:8222/varz>

Gašenje:
```bash
docker compose --profile tools down -v
```

## 9. Testiranje

### 9.1 Metrike modela
```bash
curl -s http://localhost:8002/model/info | python3 -m json.tool
```
Očekivano: `"accuracy": 0.9971`, `"baselineMajorityClass": {"accuracy": 0.4605}`,
14 atributa i `"split": "chronological 80/20"`.

### 9.2 Direktna predikcija
```bash
curl -X POST http://localhost:8002/predict -H 'Content-Type: application/json' \
  -d '{"features":[22.7,51.0,0.0049,0.0204,22.5,0.2,22.1,22.9,0.01,51.2,0.5,50.1,52.0,-0.02]}'
```
Očekivano: `{"prediction":"b8:27:eb:bf:9d:51","confidence":0.99…}`.

Validacija ulaza (pogrešan broj atributa → HTTP 422):
```bash
curl -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8002/predict \
  -H 'Content-Type: application/json' -d '{"features":[1,2,3]}'
```

### 9.3 Predikcije stižu na NATS
```bash
docker run --rm --network project-3_iots-net natsio/nats-box:latest \
  nats sub -s nats://nats:4222 'iots.analytics.predictions.>'
```
Zatim pošaljite bar 12 očitavanja jednog uređaja (prozor mora da se napuni), npr. replay-om
generatora ili ponovljenim `POST /api/v1/readings`.

### 9.4 Statistika Analytics-a
```bash
curl -s http://localhost:8003/health
```
Vraća `readings_seen`, `predictions_published`, `predictions_correct`, `mlaas_reachable`,
`mlaas_errors`, `nats_errors`.

### 9.5 Provera throttling-a
```bash
curl -s http://localhost:8003/health          # zapamtiti brojeve
docker compose --profile tools run --rm generator
curl -s http://localhost:8003/health          # uporediti
```
Očekivano: broj predikcija je **red veličine manji** od broja očitavanja
(mereno: 4000 očitavanja → 30 predikcija, tj. 1 na 133), jer se model poziva najviše
jednom po uređaju u 2 s.

### 9.6 Otpornost na pad MLaaS-a
```bash
docker compose stop mlaas
curl -s http://localhost:8003/health          # "mlaas_reachable": false
docker compose ps analytics                   # i dalje Up (healthy)
docker compose start mlaas
curl -s http://localhost:8003/health          # "mlaas_reachable": true
```
Očekivano: Analytics **ne pada**, samo preskače predikcije i posle oporavka nastavlja.

### 9.7 Klijent
Otvoriti <http://localhost:8081>. Oba indikatora u gornjem desnom uglu treba da budu zelena
(`MQTT: povezan`, `NATS: povezan`). Tab **Predikcije** prikazuje predikcije sa tačnošću uživo,
tab **Događaji** i dalje prikazuje događaje iz Projekta 2.

### 9.8 Validacija AsyncAPI specifikacija
```bash
npx @asyncapi/cli validate asyncapi/analytics.yaml
npx @asyncapi/cli validate asyncapi/datamanager.yaml
npx @asyncapi/cli validate asyncapi/eventmanager.yaml
```

### 9.9 Regresija Projekata 1 i 2
REST/gRPC i MQTT događaji nisu menjani — vidi `DOCUMENTATION.md` Projekta 1 (odeljak 7) i
Projekta 2 (odeljak 9).

## 10. Napomene i česti problemi

**Nema predikcija.** Prozor mora da se napuni: potrebno je **bar 12 očitavanja istog uređaja**.
Uz to, predikcija se pravi najviše jednom u 2 s po uređaju (`PREDICT_INTERVAL`).

**Nema događaja pri replay-u.** Isto kao u Projektu 2: prekoračenja su grupisana, pa je Compose
podešen na `OFFSET=194000` (najgušći deo datoteke).

**Ponovni trening modela.** Model se trenira u toku build-a, pa je dovoljno:
```bash
docker compose build --no-cache mlaas && docker compose up -d mlaas
```
Ako se menja `features.py`, **mora se rebuild-ovati i Analytics** (`docker compose build analytics`),
jer oba image-a nose isti fajl — inače nastaje training/serving skew.

**Sudar portova sa ranijim projektima.** Kontejneri su `iots3-*`, image-i `:3.0.0`, ali su portovi
isti kao u Projektima 1 i 2 — pokretati samo jedan projekat u datom trenutku.

**Veličina image-a.** `iots/mlaas:3.0.0` je ~686 MB (scikit-learn i numpy). To je očekivano.
