# Internet stvari i servisa (IoTS) — projekti 1, 2 i 3

Repozitorijum sadrži tri povezana projekta iz predmeta *Internet stvari i servisa*.
Svaki naredni projekat **nadograđuje prethodni**: Projekat 2 kreće od koda Projekta 1,
Projekat 3 od koda Projekta 2. Projekti su namerno razdvojeni u zasebne foldere da bi svaki
ostao zamrznut u izvornom stanju.

## Sadržaj foldera

| Folder                     | Šta je unutra                                                                                                                                                                                                         | Dokumentacija                                            |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| [`project-1/`](project-1/) | REST + gRPC + PostgreSQL: **Gateway** (REST/OpenAPI) i **DataManager** (gRPC/Protobuf) nad vremenskom serijom očitavanja IoT senzora, plus **SensorGenerator** koji simulira akviziciju                               | [project-1/DOCUMENTATION.md](project-1/DOCUMENTATION.md) |
| [`project-2/`](project-2/) | Projekat 1 + **MQTT**: DataManager objavljuje očitavanja na Mosquitto, novi **EventManager** detektuje prekoračenja pragova i objavljuje događaje, **MqttClient** web aplikacija ih prikazuje                         | [project-2/DOCUMENTATION.md](project-2/DOCUMENTATION.md) |
| [`project-3/`](project-3/) | Projekat 2 + **ML i NATS**: **MLaaS** (FastAPI + scikit-learn) servira model, **Analytics** ga poziva nad tokom očitavanja i rezultate objavljuje na **NATS**, **MqttNats** klijent prikazuje i događaje i predikcije | [project-3/DOCUMENTATION.md](project-3/DOCUMENTATION.md) |
| `.obsidian/`               | Konfiguracija Obsidian aplikacije za pregled ovih Markdown fajlova. **Nije deo projekata** i ne utiče na kod.                                                                                                         | —                                                        |

U svakom folderu se nalaze i:
- `README.md` — kratak pregled projekta (početna stranica na GitHub-u),
- `DOCUMENTATION.md` — detaljna dokumentacija: namena, struktura, pokretanje i testiranje,
- `PLAN.md` — plan implementacije napravljen pre pisanja koda, sa obrazloženjem odluka,
- originalni PDF sa postavkom zadatka.

## Kako se projekti nadovezuju

```
Projekat 1                Projekat 2                       Projekat 3
──────────                ──────────                       ──────────
SensorGenerator           + Mosquitto (MQTT broker)        + NATS (message broker)
Gateway    (REST)         + DataManager objavljuje         + MLaaS    (FastAPI + sklearn)
DataManager(gRPC)           očitavanja na MQTT             + Analytics(MQTT→ML→NATS)
PostgreSQL                + EventManager (pragovi)         MqttClient → MqttNats
                          + MqttClient (web)                 (dodat tab sa predikcijama)
```

Komponente iz ranijih projekata se u kasnijim **ne prepisuju** — Gateway, DataManager,
PostgreSQL i SensorGenerator rade isto, uz dodatke koji su opisani u dokumentaciji svakog projekta.

## Zajedničke odluke koje važe za sva tri projekta

**Dataset.** Korišćen je *Environmental Sensor Telemetry Data* (Kaggle) — 405.184 očitavanja
sa tri senzorska uređaja u periodu 12–20. jula 2020. Kolone: `ts` (Unix epoch), `device` (MAC),
`co`, `humidity`, `light`, `lpg`, `motion`, `smoke`, `temp`. Ista datoteka
(`sensor-generator/data/sensor_data.csv`) postoji u sva tri projekta.

**Izolacija projekata.** Da bi mogli da se pokreću jedan pored drugog bez sudara:

|            | kontejneri | image tagovi |
| ---------- | ---------- | ------------ |
| Projekat 1 | `iots-*`   | `:1.0.0`     |
| Projekat 2 | `iots2-*`  | `:2.0.0`     |
| Projekat 3 | `iots3-*`  | `:3.0.0`     |
|            |            |              |

**Portovi** 
	PostgreSQL je u svim projektima na hostu izložen na **5433** (ne 5432), da ne bi
	došlo do sudara sa lokalno instaliranim PostgreSQL-om ili drugim kontejnerom.
	Detaljna tabela portova je u dokumentaciji svakog projekta.

> Pošto sva tri projekta koriste iste portove (8080, 8081, 1883, …), **istovremeno treba pokretati
> samo jedan**. Prethodni se gasi sa `docker compose down` u njegovom folderu.

## Preduslovi

- Docker i Docker Compose (v2)
- Korisnik mora imati pristup Docker socket-u
- Za lokalni build Gateway-a van Docker-a: JDK 21 i Maven (nije neophodno — Docker build sve radi sam)

Za brzi start izaberite projekat i pratite njegov `DOCUMENTATION.md`, odeljak **Pokretanje**.
