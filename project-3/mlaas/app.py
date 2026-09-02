"""MLaaS - REST servis koji servira istrenirani model (zahtev 2).

FastAPI je izabran umesto Flask-a jer daje automatsku validaciju ulaza (Pydantic)
i OpenAPI/Swagger dokumentaciju bez dodatnog koda.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from features import WINDOW_SIZE, build_vector, feature_names, vector_to_dict

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("mlaas")

MODEL_DIR = Path(os.getenv("MODEL_DIR", "model"))
N_FEATURES = len(feature_names())

app = FastAPI(
    title="IoTS MLaaS API",
    version="1.0.0",
    description="Serviranje ML modela za klasifikaciju IoT uređaja na osnovu "
                "očitavanja senzora i agregata kliznog prozora.",
)

_model = None
_metrics: dict = {}


@app.on_event("startup")
def load_model() -> None:
    global _model, _metrics
    model_path = MODEL_DIR / "model.joblib"
    metrics_path = MODEL_DIR / "metrics.json"
    if model_path.exists():
        _model = joblib.load(model_path)
        log.info("model učitan iz %s", model_path)
    else:
        log.error("model nije pronađen na %s", model_path)
    if metrics_path.exists():
        _metrics = json.loads(metrics_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- šeme

class FeatureRequest(BaseModel):
    """Ulaz kao gotov feature vektor (Analytics ga gradi istim kodom)."""
    features: list[float] = Field(..., description=f"Vektor od {N_FEATURES} vrednosti")

    @field_validator("features")
    @classmethod
    def check_length(cls, v: list[float]) -> list[float]:
        if len(v) != N_FEATURES:
            raise ValueError(f"očekuje se {N_FEATURES} atributa, dobijeno {len(v)}")
        return v


class WindowRequest(BaseModel):
    """Alternativni ulaz: sirov klizni prozor očitavanja; servis sam gradi vektor."""
    window: list[dict] = Field(..., description=f"Lista od {WINDOW_SIZE} očitavanja")

    @field_validator("window")
    @classmethod
    def check_window(cls, v: list[dict]) -> list[dict]:
        if not v:
            raise ValueError("prozor je prazan")
        return v


class BatchRequest(BaseModel):
    items: list[FeatureRequest]


class PredictionResponse(BaseModel):
    prediction: str
    confidence: float
    probabilities: dict[str, float]
    features: dict[str, float] | None = None


# ---------------------------------------------------------------- rute

@app.get("/health", summary="Status servisa")
def health() -> dict:
    ok = _model is not None
    return {"status": "UP" if ok else "DOWN", "modelLoaded": ok,
            "featureCount": N_FEATURES, "windowSize": WINDOW_SIZE}


@app.get("/model/info", summary="Metapodaci i metrike modela")
def model_info() -> dict:
    if not _metrics:
        raise HTTPException(status_code=503, detail="metrike modela nisu dostupne")
    return _metrics


def _predict_vector(vector: list[float], with_features: bool = False) -> PredictionResponse:
    if _model is None:
        raise HTTPException(status_code=503, detail="model nije učitan")
    proba = _model.predict_proba([vector])[0]
    classes = list(_model.classes_)
    probabilities = {c: round(float(p), 6) for c, p in zip(classes, proba)}
    best = max(probabilities, key=probabilities.get)
    return PredictionResponse(
        prediction=best,
        confidence=probabilities[best],
        probabilities=probabilities,
        features=vector_to_dict(vector) if with_features else None,
    )


@app.post("/predict", response_model=PredictionResponse, summary="Predikcija za jedan vektor")
def predict(req: FeatureRequest) -> PredictionResponse:
    return _predict_vector(req.features)


@app.post("/predict/window", response_model=PredictionResponse,
          summary="Predikcija iz sirovog kliznog prozora")
def predict_window(req: WindowRequest) -> PredictionResponse:
    try:
        vector = build_vector(req.window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _predict_vector(vector, with_features=True)


@app.post("/predict/batch", response_model=list[PredictionResponse],
          summary="Predikcija za više vektora odjednom")
def predict_batch(req: BatchRequest) -> list[PredictionResponse]:
    if not req.items:
        return []
    return [_predict_vector(item.features) for item in req.items]
