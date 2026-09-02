# Pokretanje pojedinačnim `docker run` komandama (zahtev 5a)

Sve komande se izvršavaju iz korena `project-1/`.

## 1. Build image-a
```bash
docker build -t iots/datamanager:1.0.0 -f datamanager/Dockerfile .
docker build -t iots/gateway:1.0.0     -f gateway/Dockerfile .
docker build -t iots/sensor-generator:1.0.0 ./sensor-generator
```

## 2. Zajednička bridge mreža
```bash
docker network create --driver bridge iots-net
```

## 3. PostgreSQL
```bash
docker volume create iots-pgdata
docker run -d --name iots-db --network iots-net \
  -e POSTGRES_DB=iots -e POSTGRES_USER=iots -e POSTGRES_PASSWORD=iots \
  -v iots-pgdata:/var/lib/postgresql/data \
  -p 5433:5432 postgres:16-alpine
```

## 4. DataManager (gRPC)
```bash
docker run -d --name iots-datamanager --network iots-net \
  -e DB_HOST=iots-db -e DB_PORT=5432 -e DB_NAME=iots \
  -e DB_USER=iots -e DB_PASSWORD=iots -e GRPC_PORT=50051 \
  -p 50051:50051 iots/datamanager:1.0.0
```

## 5. Gateway (REST)
```bash
docker run -d --name iots-gateway --network iots-net \
  -e DATAMANAGER_HOST=iots-datamanager -e DATAMANAGER_PORT=50051 \
  -p 8080:8080 iots/gateway:1.0.0
```

## 6. SensorGenerator
```bash
docker run --rm --name iots-generator --network iots-net \
  -e GATEWAY_URL=http://iots-gateway:8080 \
  -e RATE=200 -e BATCH=100 -e LIMIT=2000 \
  iots/sensor-generator:1.0.0
```

## 7. Provera
```bash
curl "http://localhost:8080/api/v1/readings?size=5"
curl "http://localhost:8080/api/v1/readings/aggregate?field=temperature&from=2020-07-12T00:00:00Z&to=2020-07-13T00:00:00Z"
open http://localhost:8080/swagger-ui.html
```

## 8. Čišćenje
```bash
docker rm -f iots-gateway iots-datamanager iots-db
docker network rm iots-net
docker volume rm iots-pgdata
```
