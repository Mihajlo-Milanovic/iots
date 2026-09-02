# Pokretanje pojedinačnim `docker run` komandama

> Zahtev 3 Projekta 2 traži pokretanje preko **docker compose** (`docker compose up --build -d`).
> Ovaj dokument je dodatak — isti sistem podignut ručno, radi razumevanja veza između kontejnera.
> Sve komande se izvršavaju iz korena `project-2/`.

## 1. Build image-a
```bash
docker build -t iots/datamanager:2.0.0     -f datamanager/Dockerfile .
docker build -t iots/gateway:2.0.0         -f gateway/Dockerfile .
docker build -t iots/eventmanager:2.0.0    ./eventmanager
docker build -t iots/mqtt-client:2.0.0     ./mqtt-client
docker build -t iots/sensor-generator:2.0.0 ./sensor-generator
```

## 2. Zajednička bridge mreža
```bash
docker network create --driver bridge iots2-net
```

## 3. Mosquitto (MQTT broker)
```bash
docker volume create iots2-mosquitto-data
docker run -d --name iots2-mosquitto --network iots2-net \
  -v "$(pwd)/mosquitto/config/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
  -v iots2-mosquitto-data:/mosquitto/data \
  -p 1883:1883 -p 9001:9001 eclipse-mosquitto:2
```

## 4. PostgreSQL
```bash
docker volume create iots2-pgdata
docker run -d --name iots2-db --network iots2-net \
  -e POSTGRES_DB=iots -e POSTGRES_USER=iots -e POSTGRES_PASSWORD=iots \
  -v iots2-pgdata:/var/lib/postgresql/data \
  -p 5433:5432 postgres:16-alpine
```

## 5. DataManager (gRPC + MQTT publisher)
```bash
docker run -d --name iots2-datamanager --network iots2-net \
  -e DB_HOST=iots2-db -e DB_PORT=5432 -e DB_NAME=iots \
  -e DB_USER=iots -e DB_PASSWORD=iots -e GRPC_PORT=50051 \
  -e MQTT_HOST=iots2-mosquitto -e MQTT_PORT=1883 \
  -e MQTT_TOPIC_PREFIX=iots -e MQTT_QOS=1 -e MQTT_PUBLISH_ENABLED=true \
  -p 50051:50051 iots/datamanager:2.0.0
```

## 6. EventManager
```bash
docker run -d --name iots2-eventmanager --network iots2-net \
  -e MQTT_HOST=iots2-mosquitto -e MQTT_PORT=1883 \
  -e MQTT_TOPIC_PREFIX=iots -e MQTT_QOS=1 \
  -e COOLDOWN_SECONDS=60 -e HEALTH_PORT=8000 \
  -p 8000:8000 iots/eventmanager:2.0.0
```

## 7. Gateway (REST)
```bash
docker run -d --name iots2-gateway --network iots2-net \
  -e DATAMANAGER_HOST=iots2-datamanager -e DATAMANAGER_PORT=50051 \
  -p 8080:8080 iots/gateway:2.0.0
```

## 8. MqttClient (web)
```bash
docker run -d --name iots2-mqtt-client --network iots2-net \
  -p 8081:80 iots/mqtt-client:2.0.0
```

## 9. SensorGenerator
```bash
docker run --rm --name iots2-generator --network iots2-net \
  -e GATEWAY_URL=http://iots2-gateway:8080 \
  -e RATE=200 -e BATCH=100 -e LIMIT=4000 -e OFFSET=194000 \
  iots/sensor-generator:2.0.0
```

## 10. Provera
```bash
docker exec iots2-mosquitto mosquitto_sub -h localhost -t 'iots/events/#' -v -C 3
curl http://localhost:8000/health
curl "http://localhost:8080/api/v1/readings?size=5"
xdg-open http://localhost:8081        # MqttClient
```

## 11. Čišćenje
```bash
docker rm -f iots2-mqtt-client iots2-gateway iots2-eventmanager iots2-datamanager iots2-db iots2-mosquitto
docker network rm iots2-net
docker volume rm iots2-pgdata iots2-mosquitto-data
```
