"""Trening modela za klasifikaciju uređaja na osnovu očitavanja senzora.

Ključne metodološke odluke:
  * HRONOLOŠKI split (ne slučajni) - vremenska serija je jako autokorelisana
    (lag-1 do 0.996), pa bi slučajni split procurio informaciju iz budućnosti
    i dao nerealno dobre rezultate.
  * Uvek se izveštava i baseline (većinska klasa), da se vidi koliko model
    zaista doprinosi.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import time
from collections import Counter, deque
from datetime import datetime, timezone

import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from features import WINDOW_SIZE, build_vector, feature_names

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("train")

COLUMN_MAP = {"temp": "temperature", "humidity": "humidity", "co": "co",
              "smoke": "smoke"}


def load_rows(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            row = {"device": raw["device"], "ts": float(raw["ts"])}
            for src, dst in COLUMN_MAP.items():
                try:
                    row[dst] = float(raw[src])
                except (KeyError, TypeError, ValueError):
                    row[dst] = 0.0
            rows.append(row)
    rows.sort(key=lambda r: r["ts"])
    return rows


def build_dataset(rows: list[dict]) -> tuple[list[list[float]], list[str]]:
    """Klizni prozor po uređaju -> (X, y). Prozor se ne meša između uređaja."""
    windows: dict[str, deque] = {}
    X, y = [], []
    for row in rows:
        dev = row["device"]
        win = windows.setdefault(dev, deque(maxlen=WINDOW_SIZE))
        win.append(row)
        if len(win) == WINDOW_SIZE:
            X.append(build_vector(list(win)))
            y.append(dev)
    return X, y


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default=os.getenv("TRAIN_CSV", "data/sensor_data.csv"))
    p.add_argument("--out", default=os.getenv("MODEL_DIR", "model"))
    p.add_argument("--max-rows", type=int, default=int(os.getenv("MAX_ROWS", "150000")))
    p.add_argument("--trees", type=int, default=int(os.getenv("N_ESTIMATORS", "120")))
    args = p.parse_args()

    log.info("učitavanje %s", args.csv)
    rows = load_rows(args.csv)
    log.info("učitano %d redova", len(rows))

    if args.max_rows and len(rows) > args.max_rows:
        # ravnomerno prorediti kroz ceo period, ne odseći kraj (da ostanu svi režimi)
        step = len(rows) / args.max_rows
        rows = [rows[int(i * step)] for i in range(args.max_rows)]
        log.info("prorijeđeno na %d redova (korak %.2f)", len(rows), step)

    X, y = build_dataset(rows)
    log.info("dataset: %d uzoraka, %d atributa, klase: %s",
             len(X), len(X[0]), dict(Counter(y)))

    split = int(0.8 * len(X))
    X_tr, X_te, y_tr, y_te = X[:split], X[split:], y[:split], y[split:]
    log.info("hronološki split: %d trening / %d test", len(X_tr), len(X_te))

    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", RandomForestClassifier(
            n_estimators=args.trees, max_depth=None, min_samples_leaf=2,
            class_weight="balanced", n_jobs=-1, random_state=42)),
    ])

    started = time.time()
    pipe.fit(X_tr, y_tr)
    train_seconds = round(time.time() - started, 2)
    log.info("trening gotov za %.2fs", train_seconds)

    y_pred = pipe.predict(X_te)
    report = classification_report(y_te, y_pred, output_dict=True, zero_division=0)
    labels = sorted(set(y_te))
    matrix = confusion_matrix(y_te, y_pred, labels=labels).tolist()

    # baseline: uvek predviđaj većinsku klasu iz TRENING skupa
    majority = Counter(y_tr).most_common(1)[0][0]
    baseline_acc = sum(1 for t in y_te if t == majority) / len(y_te)

    accuracy = report["accuracy"]
    log.info("tačnost: %.4f | macro-F1: %.4f | baseline (većinska klasa): %.4f",
             accuracy, report["macro avg"]["f1-score"], baseline_acc)

    os.makedirs(args.out, exist_ok=True)
    joblib.dump(pipe, os.path.join(args.out, "model.joblib"))

    importances = pipe.named_steps["clf"].feature_importances_
    metrics = {
        "task": "device_classification",
        "model": "RandomForestClassifier",
        "trainedAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "trainSeconds": train_seconds,
        "samples": {"total": len(X), "train": len(X_tr), "test": len(X_te)},
        "windowSize": WINDOW_SIZE,
        "featureNames": feature_names(),
        "classes": labels,
        "accuracy": round(accuracy, 4),
        "macroF1": round(report["macro avg"]["f1-score"], 4),
        "baselineMajorityClass": {"class": majority, "accuracy": round(baseline_acc, 4)},
        "perClass": {
            c: {"precision": round(report[c]["precision"], 4),
                "recall": round(report[c]["recall"], 4),
                "f1": round(report[c]["f1-score"], 4),
                "support": int(report[c]["support"])}
            for c in labels
        },
        "confusionMatrix": {"labels": labels, "matrix": matrix},
        "featureImportances": {n: round(float(v), 5)
                               for n, v in sorted(zip(feature_names(), importances),
                                                  key=lambda kv: -kv[1])},
        "split": "chronological 80/20",
    }
    with open(os.path.join(args.out, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, ensure_ascii=False)

    log.info("sačuvano u %s/ (model.joblib, metrics.json)", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
