"""SensorGenerator - čita IoT očitavanja iz CSV datoteke i šalje ih
Gateway mikroservisu preko REST-a, simulirajući akviziciju sa senzora."""

import argparse
import csv
import itertools
import logging
import os
import sys
import time
from datetime import datetime, timezone

import requests

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sensor-generator")

# mapiranje kolona iz CSV-a u polja API-ja
COLUMNS = {
    "device_id": ("device", "device_id", "mac"),
    "ts": ("ts", "timestamp", "time", "date"),
    "temperature": ("temp", "temperature"),
    "humidity": ("humidity", "hum"),
    "co": ("co",),
    "smoke": ("smoke",),
    "lat": ("lat", "latitude"),
    "lon": ("lon", "lng", "longitude"),
}


def _pick(row: dict, names) -> str | None:
    for n in names:
        if n in row and row[n] not in ("", None):
            return row[n]
    return None


def _to_iso(raw: str | None) -> str:
    if raw is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:  # unix epoch (sekunde ili milisekunde)
        val = float(raw)
        if val > 1e11:
            val /= 1000.0
        return datetime.fromtimestamp(val, timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _num(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def to_reading(row: dict) -> dict:
    row = {(k or "").strip().lower(): v for k, v in row.items()}
    reading = {
        "deviceId": _pick(row, COLUMNS["device_id"]) or "sensor-1",
        "ts": _to_iso(_pick(row, COLUMNS["ts"])),
    }
    for field in ("temperature", "humidity", "co", "smoke", "lat", "lon"):
        value = _num(_pick(row, COLUMNS[field]))
        if value is not None:
            reading[field] = value
    return reading


def post(session: requests.Session, url: str, payload, retries: int = 5):
    delay = 1.0
    for attempt in range(1, retries + 1):
        try:
            res = session.post(url, json=payload, timeout=30)
            if res.status_code < 400:
                return res
            log.warning("HTTP %s: %s", res.status_code, res.text[:200])
        except requests.RequestException as exc:
            log.warning("greška u komunikaciji (%s/%s): %s", attempt, retries, exc)
        time.sleep(delay)
        delay = min(delay * 2, 30)
    return None


def run(args) -> int:
    single_url = f"{args.gateway_url.rstrip('/')}/api/v1/readings"
    batch_url = f"{single_url}/batch"
    sent = 0
    interval = 1.0 / args.rate if args.rate > 0 else 0.0

    with requests.Session() as session:
        for cycle in itertools.count(1):
            with open(args.file, newline="", encoding="utf-8") as fh:
                buffer = []
                for row in csv.DictReader(fh):
                    if args.limit and sent >= args.limit:
                        break
                    buffer.append(to_reading(row))
                    sent += 1
                    if len(buffer) >= args.batch:
                        if post(session, batch_url if args.batch > 1 else single_url,
                                buffer if args.batch > 1 else buffer[0]) is None:
                            log.error("odustajanje nakon neuspelih pokušaja")
                            return 1
                        log.info("poslato %s očitavanja (ukupno %s)", len(buffer), sent)
                        buffer.clear()
                        if interval:
                            time.sleep(interval * args.batch)
                if buffer:
                    post(session, batch_url, buffer)
                    log.info("poslato %s očitavanja (ukupno %s)", len(buffer), sent)
            if not args.loop or (args.limit and sent >= args.limit):
                break
            log.info("kraj datoteke, ponovni prolaz #%s", cycle + 1)
    log.info("gotovo, ukupno poslato: %s", sent)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="IoT SensorGenerator")
    p.add_argument("--file", default=os.getenv("CSV_FILE", "data/sensor_data.csv"))
    p.add_argument("--gateway-url", default=os.getenv("GATEWAY_URL", "http://localhost:8080"))
    p.add_argument("--rate", type=float, default=float(os.getenv("RATE", "10")),
                   help="očitavanja u sekundi (0 = bez pauze)")
    p.add_argument("--batch", type=int, default=int(os.getenv("BATCH", "50")),
                   help="broj očitavanja po zahtevu (1 = pojedinačni POST)")
    p.add_argument("--limit", type=int, default=int(os.getenv("LIMIT", "0")),
                   help="maksimalan broj poslatih očitavanja (0 = svi)")
    p.add_argument("--loop", action="store_true",
                   default=os.getenv("LOOP", "").lower() in ("1", "true", "yes"))
    args = p.parse_args()

    if not os.path.exists(args.file):
        log.error("CSV datoteka ne postoji: %s", args.file)
        return 2
    log.info("slanje iz %s ka %s (rate=%s/s, batch=%s)",
             args.file, args.gateway_url, args.rate, args.batch)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
