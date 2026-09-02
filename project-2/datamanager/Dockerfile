# build kontekst je koren project-1 direktorijuma (zbog proto/)
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app

COPY datamanager/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/ /app/proto/
RUN mkdir -p /app/generated && touch /app/generated/__init__.py \
 && python -m grpc_tools.protoc -I/app/proto \
      --python_out=/app/generated --grpc_python_out=/app/generated \
      /app/proto/reading.proto \
 && sed -i 's/^import reading_pb2 as/from generated import reading_pb2 as/' \
      /app/generated/reading_pb2_grpc.py

COPY datamanager/*.py /app/

EXPOSE 50051
CMD ["python", "server.py"]
