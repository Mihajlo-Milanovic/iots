# Projekat 3 — Plan implementacije

Nadogradnja na Projekat 2: novi **Analytics** mikroservis sluša MQTT topic sa očitavanjima,
poziva **MLaaS** (Python + FastAPI + scikit-learn) preko REST-a, a rezultate modela objavljuje
na **NATS** subject. Klijent iz Projekta 2 postaje **MqttNats** i prikazuje i predikcije.

```
DataManager ─publish→ iots/readings/{deviceId}  (MQTT / Mosquitto)
                             │
                  ┌──────────┴───────────┐
            EventManager              Analytics ──REST /predict──→ MLaaS (FastAPI + sklearn)
                  │                        │                            │
       iots/events/… (MQTT)                └─publish→ iots.analytics.predictions.{deviceId}
                  │                                            (NATS)
                  └──────────────┬─────────────────────────────────┘
                            MqttNats (web): MQTT/WS + NATS/WS
```

## 0. Polazna tačka i struktura

`project-2/` se **kopira** u `project-3/` i proširuje (Projekat 2 ostaje zamrznut).
Kontejneri `iots3-*`, image tagovi `:3.0.0` — da sva tri projekta mogu da koegzistiraju.

```
project-3/
├── mlaas/                        # NOVO (zahtev 2)
│   ├── app.py                    # FastAPI: /health, /model/info, /predict, /predict/batch
│   ├── train.py                  # trening + evaluacija, čuva model.joblib i metrics.json
│   ├── features.py               # deljeno izvlačenje atributa (trening i serviranje)
│   ├── model/                    # artefakt modela (nastaje u toku build-a)
│   └── Dockerfile, requirements.txt
├── analytics/                    # NOVO (zahtev 1, 3)
│   ├── main.py                   # MQTT subscribe → prozor → MLaaS REST → NATS publish
│   ├── window.py                 # klizni prozor po uređaju
│   └── Dockerfile, requirements.txt
├── nats/nats-server.conf         # NOVO — NATS sa WebSocket listener-om
├── mqtt-nats-client/             # Projekat 2 klijent + NATS pretplata (zahtev 4)
├── asyncapi/
│   ├── datamanager.yaml          # iz Projekta 2
│   ├── eventmanager.yaml         # iz Projekta 2
│   └── analytics.yaml            # NOVO — NATS kanal sa predikcijama (zahtev 3)
├── (gateway, datamanager, eventmanager, mosquitto, sensor-generator … iz Projekta 2)
└── docker-compose.yml            # 9 servisa
```

## 1. Izbor ML zadatka — na osnovu izmerenih svojstava dataset-a

Pre izbora modela izmereno je koliko je koji zadatak zapravo težak na ovim podacima:

| kandidat | rezultat merenja | zaključak |
|---|---|---|
| regresija: temperatura H koraka unapred | naivni „poslednja vrednost" baseline daje MAE **0,17–0,24 °C** i na 120 uzoraka unapred (autokorelacija 0,78–0,90) | model bi jedva nadmašio trivijalan baseline — **efektno ali bezvredno** |
| klasifikacija: da li sledi prekoračenje praga u narednih 60 s | naivno pravilo „već je u prekoračenju" daje **P=1,00 / R=0,90–0,97** | zadatak degenerisan (prekoračenja dolaze u dugim serijama) |
| **klasifikacija: koji je uređaj poslao očitavanje** | trivijalan nearest-centroid **99,94 %** naspram većinske klase **46,84 %** (hronološki 80/20 split) | jasno definisan, velika razlika u odnosu na baseline — **preporuka** |

**Izbor: višeklasna klasifikacija uređaja** (3 klase) — to je i standardna upotreba ovog
Kaggle dataset-a. Zadatak je lak, ali je *pošteno* lak: razmak do baseline-a je 46,8 % → ~100 %,
za razliku od druga dva gde baseline već rešava problem.

> Pošteno izveštavanje je deo plana: uvek se prikazuje i baseline (većinska klasa), koristi se
> **hronološki** split (ne slučajni — vremenska serija je autokorelisana, slučajni split curi
> informaciju), i objavljuju se per-klasa precision/recall, ne samo ukupna tačnost.

## 2. MLaaS mikroservis (zahtev 2)

**Tehnologija: Python 3.12 + FastAPI + scikit-learn** (spec traži Flask/FastAPI; FastAPI daje
automatski OpenAPI i validaciju preko Pydantic-a).

**Model**: `RandomForestClassifier` (ili `HistGradientBoostingClassifier`), `class_weight="balanced"`.
**Atributi** — trenutno očitavanje + agregati kliznog prozora (tu ulazi vremenska serija):

| grupa | atributi |
|---|---|
| trenutni | `temperature`, `humidity`, `co`, `smoke`, `lpg` |
| prozor (W=12 uzoraka, ~60 s) | `mean`, `std`, `min`, `max`, `slope` za temperature i humidity |

`features.py` je **deljen između treninga i serviranja** — isti kod gradi vektor u oba slučaja,
čime se izbegava training/serving skew.

**Trening** (`train.py`, pokreće se u toku Docker build-a pa je model deo image-a):
- hronološki 80/20 split, `StandardScaler` + model u `Pipeline`,
- subsample na ~150.000 redova radi vremena treninga,
- zapisuje `model/model.joblib` i `model/metrics.json` (accuracy, macro-F1, confusion matrix,
  baseline, broj atributa, verzija sklearn-a, datum treninga).

**REST endpointi:**

| metod | putanja | opis |
|---|---|---|
| GET | `/health` | status servisa i da li je model učitan |
| GET | `/model/info` | metapodaci: tip modela, atributi, metrike, datum treninga |
| POST | `/predict` | jedan feature vektor → `{prediction, confidence, probabilities}` |
| POST | `/predict/batch` | lista vektora → lista predikcija |
| GET | `/docs` | Swagger UI (FastAPI automatski) |

## 3. Analytics mikroservis (zahtev 1, 3)

**Tehnologija: Python 3.12** (paho-mqtt + nats-py + httpx), radi konzistentnosti sa ostalim servisima.

Tok:
1. Pretplata na `iots/readings/+` (QoS 1, trajna sesija) — isti topic koji puni DataManager.
2. Održava **klizni prozor po uređaju** (`collections.deque`, W=12).
3. Kada je prozor pun, gradi feature vektor (`features.py`, deljen sa MLaaS-om).
4. **Throttling**: MLaaS se ne poziva za svako očitavanje (replay ide i do 200 poruka/s) —
   poziva se najviše jednom u `PREDICT_INTERVAL` sekundi po uređaju (podrazumevano 2 s).
   Bez toga bi Analytics pravio stotine HTTP poziva u sekundi.
5. `POST /predict` na MLaaS; timeout, retry sa backoff-om, i **circuit-breaker** ponašanje —
   ako MLaaS ne odgovara, Analytics loguje i nastavlja (ne pada).
6. Rezultat objavljuje na NATS subject `iots.analytics.predictions.{deviceId}`.

**Poruka predikcije:**
```json
{
  "predictionId": "b8:27:eb:bf:9d:51-1594512094",
  "deviceId": "b8:27:eb:bf:9d:51",
  "modelTask": "device_classification",
  "prediction": "b8:27:eb:bf:9d:51",
  "confidence": 0.98,
  "probabilities": { "b8:27:eb:bf:9d:51": 0.98, "00:0f:00:70:91:0a": 0.01, "1c:bf:ce:15:ec:4d": 0.01 },
  "correct": true,
  "windowSize": 12,
  "features": { "temperature_mean": 22.4, "temperature_slope": 0.01, "…": 0 },
  "readingTs": "2020-07-12T00:01:34Z",
  "predictedAt": "2026-09-02T10:15:22Z",
  "latencyMs": 7,
  "location": { "lat": 44.8125, "lon": 20.4612 }
}
```
> `correct` se može izračunati jer je stvarni uređaj poznat iz topic-a — zgodno za demo
> (klijent prikazuje tekuću tačnost uživo), i pošteno je označeno kao evaluacija, ne kao ulaz modela.

## 4. NATS broker (zahtev 5)

`nats:2-alpine` sa konfiguracijom koja uključuje **WebSocket listener** — bez njega
MqttNats aplikacija iz pregledača ne može da se pretplati:
```
port: 4222
http_port: 8222            # monitoring
websocket {
  port: 9222
  no_tls: true
}
```
Healthcheck: `wget -qO- http://localhost:8222/healthz`.

## 5. AsyncAPI specifikacija (zahtevi 3, 6)

`asyncapi/analytics.yaml`, AsyncAPI **3.1.0** (kao u Projektu 2, prolazi `asyncapi validate`):
- server `nats` (`protocol: nats`) i `nats-ws` (`protocol: ws`),
- kanal `iots.analytics.predictions.{deviceId}` sa parametrom,
- operacija `receive` na `iots/readings/{deviceId}` (ulaz) i `send` na NATS kanal (izlaz),
- kompletna `PredictionPayload` šema sa primerom.

## 6. MqttNats klijent (zahtev 4)

Web aplikacija iz Projekta 2 se proširuje: **dve konekcije** — MQTT preko WebSocket-a (događaji,
kao do sada) i **NATS preko WebSocket-a** (`nats.ws`), pretplata na `iots.analytics.predictions.*`.

- Dva taba: **Događaji** (Projekat 2) i **Predikcije** (novo).
- Tabela predikcija: vreme, uređaj, predviđena klasa, pouzdanost (traka), tačno/netačno, latencija.
- Zbirni panel: broj predikcija, **tekuća tačnost**, prosečna pouzdanost i latencija.
- Dva nezavisna indikatora stanja veze (MQTT i NATS) sa automatskim reconnect-om.
- **JS biblioteke se ugrađuju u image u toku build-a** (ne učitavaju se sa CDN-a u toku rada),
  da demonstracija radi i bez interneta.

## 7. Docker Compose (zahtev 5)

Devet servisa: `mosquitto`, `nats`, `db`, `datamanager`, `gateway`, `eventmanager`,
**`mlaas`**, **`analytics`**, `mqtt-nats-client`, plus `generator` (profil `tools`).
Zavisnosti preko healthcheck-ova: `mlaas` mora biti `healthy` pre `analytics`;
`nats` + `mosquitto` pre `analytics`.

Portovi: 8080 gateway, 8081 klijent, 8000 eventmanager, **8002 mlaas**, **8003 analytics health**,
1883/9001 MQTT, **4222/9222/8222 NATS**, 50051 gRPC, 5433 Postgres.

## 8. Testiranje

1. `GET /model/info` → prikaz metrika iz treninga.
2. `POST /predict` ručno (curl) sa poznatim vektorom → očekivana klasa.
3. `nats sub 'iots.analytics.predictions.>'` → predikcije stižu na broker.
4. Replay generatora (`OFFSET=194000`) → MqttNats prikazuje i događaje i predikcije.
5. **Otpornost**: `docker compose stop mlaas` → Analytics loguje greške i nastavlja,
   ne pada; posle `start` nastavlja da objavljuje.
6. Throttling: pri 200 poruka/s broj poziva MLaaS-a ostaje ≈ 1 po uređaju u 2 s.
7. Provera da Projekat 2 funkcionalnost (događaji, REST, gRPC) i dalje radi — regresioni set.

## 9. Redosled rada

1. Kopiranje `project-2` → `project-3`, preimenovanje kontejnera/tagova, provera da stack radi.
2. NATS u Compose + provera TCP i WebSocket listener-a.
3. `features.py` + `train.py` → trening modela, uvid u stvarne metrike.
4. MLaaS FastAPI servis + Dockerfile (trening u toku build-a) → provera endpointa.
5. Analytics servis (prozor, throttling, MLaaS poziv, NATS publish).
6. `asyncapi/analytics.yaml` + validacija.
7. MqttNats klijent (tabovi, NATS pretplata, ugrađene biblioteke).
8. Kompletan Compose stack + end-to-end i regresiona provera.
9. README (opis modela, metrika, endpointa, subject-a) + push na GitHub.

## Otvorena pitanja za odluku

1. **ML zadatak** — predlog klasifikacija uređaja (obrazloženje i merenja u odeljku 1).
   Alternativa je regresija temperature, ali uz jasno upozorenje da naivni baseline već rešava
   problem; ako je za predmet važnije da bude *regresija*, treba je uzeti uz iskreno poređenje.
2. **Biblioteka** — predlog scikit-learn (dovoljno za tabelarne podatke, brz trening).
   TensorFlow/Keras bi značajno povećao image i vreme build-a bez dobitka u tačnosti.
3. **Gde se trenira model** — predlog u toku Docker build-a (model deo image-a, reproducibilno).
   Alternativa je poseban `trainer` servis koji piše u deljeni volume.
