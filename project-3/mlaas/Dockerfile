# build kontekst je koren project-3 direktorijuma (zbog sensor-generator/data)
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 MODEL_DIR=/app/model

COPY mlaas/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mlaas/features.py mlaas/train.py mlaas/app.py ./

# Model se trenira u toku build-a - artefakt je deo image-a, pa je serviranje
# reproducibilno i ne zavisi od deljenog volumena.
COPY sensor-generator/data/sensor_data.csv /tmp/sensor_data.csv
RUN python train.py --csv /tmp/sensor_data.csv --out /app/model \
 && rm -f /tmp/sensor_data.csv

EXPOSE 8002
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8002"]
