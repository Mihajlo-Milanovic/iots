# Pokretanje pojedinačnim `docker run` komandama

> Zahtev 3 Projekta 3 traži pokretanje preko **docker compose** (`docker compose up --build -d`).
> Ovaj dokument je dodatak — isti sistem podignut ručno, radi razumevanja veza između kontejnera.
> Sve komande se izvršavaju iz korena `project-2/`.

## 1. Build image-a
```bash
docker build -t iots/datamanager:3.0.0     -f datamanager/Dockerfile .
docker build -t iots/gateway:3.0.0         -f gateway/Dockerfile .
docker build -t iots/eventmanager:3.0.0    ./eventmanager
docker build -t iots/mqtt-nats-client:3.0.0 ./mqtt-nats-client
docker build -t iots/mlaas:3.0.0            -f mlaas/Dockerfile .
docker build -t iots/analytics:3.0.0       -f analytics/Dockerfile .
docker build -t iots/sensor-generator:3.0.0 ./sensor-generator
```

## 2. Zajednička bridge mreža
```bash
docker network create --driver bridge iots3-net
```

## 3. Mosquitto (MQTT broker)
```bash
docker volume create iots3-mosquitto-data
docker run -d --name iots3-mosquitto --network iots3-net \
  -v "$(pwd)/mosquitto/config/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" \
  -v iots3-mosquitto-data:/mosquitto/data \
  -p 1883:1883 -p 9001:9001 eclipse-mosquitto:2
```

## 3b. NATS broker
```bash
docker run -d --name iots3-nats --network iots3-net \
  -v "$(pwd)/nats/nats-server.conf:/etc/nats/nats-server.conf:ro" \
  -p 4222:4222 -p 9222:9222 -p 8222:8222 \
  nats:2-alpine -c /etc/nats/nats-server.conf
```

## 3c. MLaaS
```bash
docker run -d --name iots3-mlaas --network iots3-net -p 8002:8002 iots/mlaas:3.0.0
```

## 3d. Analytics
```bash
docker run -d --name iots3-analytics --network iots3-net \
  -e MQTT_HOST=iots3-mosquitto -e NATS_URL=nats://iots3-nats:4222 \
  -e MLAAS_URL=http://iots3-mlaas:8002 -e PREDICT_INTERVAL=2.0 \
  -p 8003:8003 iots/analytics:3.0.0
```

## 4. PostgreSQL
```bash
docker volume create iots3-pgdata
docker run -d --name iots3-db --network iots3-net \
  -e POSTGRES_DB=iots -e POSTGRES_USER=iots -e POSTGRES_PASSWORD=iots \
  -v iots3-pgdata:/var/lib/postgresql/data \
  -p 5433:5432 postgres:16-alpine
```

## 5. DataManager (gRPC + MQTT publisher)
```bash
docker run -d --name iots3-datamanager --network iots3-net \
  -e DB_HOST=iots3-db -e DB_PORT=5432 -e DB_NAME=iots \
  -e DB_USER=iots -e DB_PASSWORD=iots -e GRPC_PORT=50051 \
  -e MQTT_HOST=iots3-mosquitto -e MQTT_PORT=1883 \
  -e MQTT_TOPIC_PREFIX=iots -e MQTT_QOS=1 -e MQTT_PUBLISH_ENABLED=true \
  -p 50051:50051 iots/datamanager:3.0.0
```

## 6. EventManager
```bash
docker run -d --name iots3-eventmanager --network iots3-net \
  -e MQTT_HOST=iots3-mosquitto -e MQTT_PORT=1883 \
  -e MQTT_TOPIC_PREFIX=iots -e MQTT_QOS=1 \
  -e COOLDOWN_SECONDS=60 -e HEALTH_PORT=8000 \
  -p 8000:8000 iots/eventmanager:3.0.0
```

## 7. Gateway (REST)
```bash
docker run -d --name iots3-gateway --network iots3-net \
  -e DATAMANAGER_HOST=iots3-datamanager -e DATAMANAGER_PORT=50051 \
  -p 8080:8080 iots/gateway:3.0.0
```

## 8. MqttClient (web)
```bash
docker run -d --name iots3-mqtt-client --network iots3-net \
  -p 8081:80 iots/mqtt-nats-client:3.0.0
```

## 9. SensorGenerator
```bash
docker run --rm --name iots3-generator --network iots3-net \
  -e GATEWAY_URL=http://iots3-gateway:8080 \
  -e RATE=200 -e BATCH=100 -e LIMIT=4000 -e OFFSET=194000 \
  iots/sensor-generator:3.0.0
```

## 10. Provera
```bash
docker exec iots3-mosquitto mosquitto_sub -h localhost -t 'iots/events/#' -v -C 3
curl http://localhost:8000/health
curl "http://localhost:8080/api/v1/readings?size=5"
xdg-open http://localhost:8081        # MqttClient
```

## 11. Čišćenje
```bash
docker rm -f iots3-mqtt-client iots3-gateway iots3-eventmanager iots3-datamanager iots3-db iots3-mosquitto
docker network rm iots3-net
docker volume rm iots3-pgdata iots3-mosquitto-data
```
