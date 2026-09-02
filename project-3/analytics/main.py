"""Analytics mikroservis (zahtevi 1 i 3).

Pretplaćuje se na MQTT topic sa očitavanjima koji puni DataManager, održava
klizni prozor po uređaju, poziva MLaaS REST endpoint za predikciju i rezultat
objavljuje na NATS subject.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import time
from datetime import datetime, timezone

import httpx
import nats
import paho.mqtt.client as mqtt

import health
from features import WINDOW_SIZE, build_vector, vector_to_dict
from window import DeviceWindows

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("analytics")

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "iots")
MQTT_QOS = int(os.getenv("MQTT_QOS", "1"))
NATS_URL = os.getenv("NATS_URL", "nats://nats:4222")
NATS_SUBJECT_PREFIX = os.getenv("NATS_SUBJECT_PREFIX", "iots.analytics.predictions")
MLAAS_URL = os.getenv("MLAAS_URL", "http://mlaas:8002")
PREDICT_INTERVAL = float(os.getenv("PREDICT_INTERVAL", "2.0"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8003"))
CLIENT_ID = os.getenv("MQTT_CLIENT_ID", f"analytics-{socket.gethostname()}")

READINGS_TOPIC = f"{MQTT_PREFIX}/readings/+"

windows = DeviceWindows(WINDOW_SIZE, PREDICT_INTERVAL)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Analytics:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.nc = None
        self.http: httpx.AsyncClient | None = None
        self._mlaas_down_logged = False

    # ---------------------------------------------------------- MQTT
    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            client.subscribe(READINGS_TOPIC, qos=MQTT_QOS)
            health.set_state(mqtt_connected=True)
            log.info("MQTT povezan, pretplata na %s", READINGS_TOPIC)
        else:
            health.set_state(mqtt_connected=False)
            log.error("MQTT konekcija odbijena: %s", reason_code)

    def on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        health.set_state(mqtt_connected=False)
        if reason_code != 0:
            log.warning("MQTT veza prekinuta (%s)", reason_code)

    def on_message(self, client, userdata, msg):
        try:
            reading = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("neispravna poruka na %s", msg.topic)
            return
        health.bump("readings_seen")
        device_id = reading.get("deviceId")
        if not device_id:
            return
        windows.add(device_id, reading)
        if windows.should_predict(device_id):
            # posao se predaje asyncio petlji iz paho niti
            asyncio.run_coroutine_threadsafe(self.predict_and_publish(device_id), self.loop)

    # ---------------------------------------------------------- MLaaS + NATS
    async def predict_and_publish(self, device_id: str) -> None:
        snapshot = windows.snapshot(device_id)
        if len(snapshot) < WINDOW_SIZE:
            return
        try:
            vector = build_vector(snapshot)
        except ValueError as exc:
            log.warning("ne mogu da izgradim vektor: %s", exc)
            return

        started = time.perf_counter()
        try:
            res = await self.http.post(f"{MLAAS_URL}/predict", json={"features": vector})
            res.raise_for_status()
            payload = res.json()
            self._mlaas_down_logged = False
            health.set_state(mlaas_reachable=True)
        except (httpx.HTTPError, ValueError) as exc:
            # MLaaS nedostupan - Analytics ne sme da padne, samo preskače predikciju
            health.set_state(mlaas_reachable=False)
            health.bump("mlaas_errors")
            if not self._mlaas_down_logged:
                log.error("MLaaS nedostupan (%s) - predikcije se preskaču", exc)
                self._mlaas_down_logged = True
            return
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        latest = snapshot[-1]
        event = {
            "predictionId": f"{device_id}-{latest.get('id', 'na')}",
            "deviceId": device_id,
            "modelTask": "device_classification",
            "prediction": payload["prediction"],
            "confidence": payload["confidence"],
            "probabilities": payload["probabilities"],
            # stvarni uređaj je poznat iz topic-a -> evaluacija uživo (nije ulaz modela)
            "correct": payload["prediction"] == device_id,
            "windowSize": WINDOW_SIZE,
            "features": {k: round(v, 4) for k, v in vector_to_dict(vector).items()},
            "readingId": latest.get("id"),
            "readingTs": latest.get("ts"),
            "predictedAt": _now_iso(),
            "latencyMs": latency_ms,
        }
        if latest.get("location"):
            event["location"] = latest["location"]

        subject = f"{NATS_SUBJECT_PREFIX}.{device_id.replace(':', '-')}"
        try:
            await self.nc.publish(subject, json.dumps(event).encode())
            health.bump("predictions_published")
            if event["correct"]:
                health.bump("predictions_correct")
            log.info("PREDIKCIJA %s conf=%.3f %s (%.1f ms) -> %s",
                     event["prediction"], event["confidence"],
                     "OK" if event["correct"] else "NETAČNO", latency_ms, subject)
        except Exception as exc:
            health.bump("nats_errors")
            log.error("NATS publish greška: %s", exc)

    # ---------------------------------------------------------- start
    async def run(self) -> int:
        self.loop = asyncio.get_running_loop()
        health.start(HEALTH_PORT)
        self.http = httpx.AsyncClient(timeout=float(os.getenv("MLAAS_TIMEOUT", "5.0")))

        for attempt in range(1, 31):
            try:
                self.nc = await nats.connect(
                    NATS_URL, name=CLIENT_ID,
                    reconnect_time_wait=2, max_reconnect_attempts=-1)
                break
            except Exception as exc:
                log.warning("NATS nedostupan (%s/30): %s", attempt, exc)
                await asyncio.sleep(2)
        else:
            log.error("ne mogu da se povežem na NATS %s", NATS_URL)
            return 1
        health.set_state(nats_connected=True)
        log.info("NATS povezan: %s (subject prefix %s)", NATS_URL, NATS_SUBJECT_PREFIX)

        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                             client_id=CLIENT_ID, clean_session=False)
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_message = self.on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()

        log.info("Analytics pokrenut (prozor=%d, interval predikcije=%.1fs)",
                 WINDOW_SIZE, PREDICT_INTERVAL)
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            client.loop_stop()
            await self.http.aclose()
            if self.nc:
                await self.nc.drain()
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(Analytics().run()))
    except KeyboardInterrupt:
        pass
