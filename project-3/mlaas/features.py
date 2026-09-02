"""Izvlačenje atributa - DELJENO između treninga i serviranja.

Isti kod gradi feature vektor i u `train.py` i u FastAPI servisu i u Analytics
mikroservisu, čime se izbegava training/serving skew (da model u produkciji ne
dobija drugačije poređane ili drugačije izračunate atribute nego na treningu).
"""

from __future__ import annotations

# Trenutne (instant) vrednosti očitavanja.
# NAPOMENA: samo polja koja stvarno postoje u MQTT poruci koju šalje DataManager.
# `lpg` i `light`/`motion` iz CSV-a se NE koriste - nisu deo šeme baze ni MQTT poruke,
# pa bi model na treningu video stvarne vrednosti, a u produkciji uvek nulu
# (training/serving skew).
INSTANT_FIELDS = ["temperature", "humidity", "co", "smoke"]
# polja nad kojima se računaju agregati kliznog prozora
WINDOW_FIELDS = ["temperature", "humidity"]
WINDOW_STATS = ["mean", "std", "min", "max", "slope"]

WINDOW_SIZE = 12          # ~60 s pri intervalu uzorkovanja od ~5 s


def feature_names() -> list[str]:
    """Redosled atributa - jedini izvor istine za oblik vektora."""
    names = list(INSTANT_FIELDS)
    for field in WINDOW_FIELDS:
        for stat in WINDOW_STATS:
            names.append(f"{field}_{stat}")
    return names


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return (sum((v - m) ** 2 for v in values) / len(values)) ** 0.5


def _slope(values: list[float]) -> float:
    """Nagib proste linearne regresije po indeksu (trend u prozoru)."""
    n = len(values)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = _mean(values)
    denom = sum((i - mean_x) ** 2 for i in range(n))
    if denom == 0:
        return 0.0
    return sum((i - mean_x) * (values[i] - mean_y) for i in range(n)) / denom


_STAT_FN = {"mean": _mean, "std": _std, "min": min, "max": max, "slope": _slope}


def build_vector(window: list[dict]) -> list[float]:
    """Napravi feature vektor iz kliznog prozora očitavanja.

    `window` je lista dict-ova poređanih hronološki; poslednji element je najnovije
    očitavanje i iz njega se uzimaju instant vrednosti.
    """
    if not window:
        raise ValueError("prozor je prazan")

    latest = window[-1]
    vector = [float(latest.get(f) or 0.0) for f in INSTANT_FIELDS]

    for field in WINDOW_FIELDS:
        series = [float(row.get(field) or 0.0) for row in window]
        for stat in WINDOW_STATS:
            vector.append(float(_STAT_FN[stat](series)))
    return vector


def vector_to_dict(vector: list[float]) -> dict[str, float]:
    return dict(zip(feature_names(), vector))
