# build kontekst je koren project-3 direktorijuma (zbog deljenog mlaas/features.py)
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY analytics/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# features.py je DELJEN sa MLaaS-om - isti kod gradi vektor na obe strane
COPY mlaas/features.py ./features.py
COPY analytics/*.py ./

EXPOSE 8003
CMD ["python", "main.py"]
