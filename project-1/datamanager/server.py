import logging
import os
from concurrent import futures
from datetime import datetime, timezone

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from grpc_reflection.v1alpha import reflection

import repository
from db import init_db
from generated import reading_pb2 as pb
from generated import reading_pb2_grpc as pb_grpc

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("datamanager")


def _to_dt(ts: Timestamp):
    if ts is None or (ts.seconds == 0 and ts.nanos == 0):
        return None
    return ts.ToDatetime().replace(tzinfo=timezone.utc)


def _to_ts(dt: datetime) -> Timestamp:
    ts = Timestamp()
    if dt is not None:
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ts.FromDatetime(dt.astimezone(timezone.utc))
    return ts


def _to_proto(row) -> pb.Reading:
    msg = pb.Reading(
        id=row.id,
        device_id=row.device_id,
        ts=_to_ts(row.ts),
        temperature=row.temperature or 0.0,
        humidity=row.humidity or 0.0,
        co=row.co or 0.0,
        smoke=row.smoke or 0.0,
    )
    if row.lat is not None:
        msg.lat = row.lat
    if row.lon is not None:
        msg.lon = row.lon
    return msg


def _to_dict(msg: pb.Reading) -> dict:
    data = {
        "device_id": msg.device_id,
        "ts": _to_dt(msg.ts) or datetime.now(timezone.utc),
        "temperature": msg.temperature,
        "humidity": msg.humidity,
        "co": msg.co,
        "smoke": msg.smoke,
        "lat": msg.lat if msg.HasField("lat") else None,
        "lon": msg.lon if msg.HasField("lon") else None,
    }
    return data


class ReadingService(pb_grpc.ReadingServiceServicer):

    def Create(self, request, context):
        r = request.reading
        if not r.device_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "device_id is required")
        return _to_proto(repository.create(_to_dict(r)))

    def Get(self, request, context):
        row = repository.get(request.id)
        if row is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"reading {request.id} not found")
        return _to_proto(row)

    def List(self, request, context):
        rows, total = repository.list_readings(
            request.device_id, _to_dt(request.start_time), _to_dt(request.end_time),
            request.page, request.page_size,
        )
        return pb.ListResponse(readings=[_to_proto(r) for r in rows], total=total)

    def Update(self, request, context):
        row = repository.update(request.id, _to_dict(request.reading),
                                list(request.fields))
        if row is None:
            context.abort(grpc.StatusCode.NOT_FOUND, f"reading {request.id} not found")
        return _to_proto(row)

    def Delete(self, request, context):
        return pb.DeleteResponse(deleted=repository.delete(request.id))

    def Aggregate(self, request, context):
        field = request.field or "temperature"
        if field not in repository.AGGREGATABLE:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT,
                          f"field must be one of {sorted(repository.AGGREGATABLE)}")
        res = repository.aggregate(request.device_id, field,
                                   _to_dt(request.start_time), _to_dt(request.end_time))
        return pb.AggregateResponse(field=field, **res)

    def BatchCreate(self, request_iterator, context):
        buf, created = [], 0
        for msg in request_iterator:
            buf.append(_to_dict(msg))
            if len(buf) >= 500:
                created += repository.create_many(buf)
                buf.clear()
        created += repository.create_many(buf)
        return pb.BatchResponse(created=created)


def serve():
    init_db()
    port = os.getenv("GRPC_PORT", "50051")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=16))
    pb_grpc.add_ReadingServiceServicer_to_server(ReadingService(), server)

    hs = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(hs, server)
    hs.set("", health_pb2.HealthCheckResponse.SERVING)
    hs.set("iots.datamanager.v1.ReadingService",
           health_pb2.HealthCheckResponse.SERVING)

    reflection.enable_server_reflection(
        (pb.DESCRIPTOR.services_by_name["ReadingService"].full_name,
         health_pb2.DESCRIPTOR.services_by_name["Health"].full_name,
         reflection.SERVICE_NAME), server)

    server.add_insecure_port(f"0.0.0.0:{port}")
    server.start()
    log.info("DataManager gRPC listening on 0.0.0.0:%s", port)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
