"""MQTT publisher za DataManager.

Posle uspešnog upisa u bazu, očitavanje se objavljuje na topic
`{prefix}/readings/{deviceId}`. Publikovanje je namerno *neblokirajuće* i
tolerantno na greške - baza je izvor istine, MQTT je propagacija događaja.
"""

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

log = logging.getLogger("datamanager.mqtt")

ENABLED = os.getenv("MQTT_PUBLISH_ENABLED", "true").lower() in ("1", "true", "yes")
HOST = os.getenv("MQTT_HOST", "mosquitto")
PORT = int(os.getenv("MQTT_PORT", "1883"))
PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "iots")
QOS = int(os.getenv("MQTT_QOS", "1"))
MAX_RATE = float(os.getenv("MQTT_MAX_RATE", "0"))  # poruka/s, 0 = bez ograničenja


class ReadingPublisher:
    def __init__(self) -> None:
        self._client: mqtt.Client | None = None
        self._lock = threading.Lock()
        self._last_publish = 0.0
        self._published = 0
        self._failed = 0

    def start(self) -> None:
        if not ENABLED:
            log.info("MQTT publikovanje je isključeno (MQTT_PUBLISH_ENABLED=false)")
            return
        client_id = f"datamanager-{socket.gethostname()}"
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
            clean_session=True,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)
        try:
            self._client.connect_async(HOST, PORT, keepalive=60)
            self._client.loop_start()
            log.info("MQTT klijent pokrenut (%s:%s, prefix=%s, qos=%s)", HOST, PORT, PREFIX, QOS)
        except Exception as exc:  # pragma: no cover
            log.error("MQTT konekcija nije uspela: %s", exc)
            self._client = None

    def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()

    # -- callbacks -------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            log.info("povezan na MQTT broker %s:%s", HOST, PORT)
        else:
            log.warning("MQTT konekcija odbijena: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code != 0:
            log.warning("MQTT veza prekinuta (%s), sledi reconnect", reason_code)

    # -- publish ---------------------------------------------------------
    def topic_for(self, device_id: str) -> str:
        return f"{PREFIX}/readings/{device_id}"

    @staticmethod
    def payload_for(row) -> dict:
        ts = row.ts
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        payload = {
            "id": row.id,
            "deviceId": row.device_id,
            "ts": ts.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if ts else None,
            "temperature": row.temperature,
            "humidity": row.humidity,
            "co": row.co,
            "smoke": row.smoke,
        }
        if row.lat is not None and row.lon is not None:
            payload["location"] = {"lat": row.lat, "lon": row.lon}
        return payload

    def publish_reading(self, row) -> None:
        """Objavi jedno očitavanje. Nikada ne baca izuzetak."""
        if self._client is None:
            return
        try:
            if MAX_RATE > 0:
                with self._lock:
                    delta = time.monotonic() - self._last_publish
                    wait = (1.0 / MAX_RATE) - delta
                    if wait > 0:
                        time.sleep(wait)
                    self._last_publish = time.monotonic()
            info = self._client.publish(
                self.topic_for(row.device_id),
                json.dumps(self.payload_for(row)),
                qos=QOS,
                retain=False,
            )
            if info.rc == mqtt.MQTT_ERR_SUCCESS:
                self._published += 1
            else:
                self._failed += 1
                log.warning("MQTT publish rc=%s za uređaj %s", info.rc, row.device_id)
        except Exception as exc:
            self._failed += 1
            log.warning("MQTT publish greška: %s", exc)

    def publish_many(self, rows) -> None:
        for row in rows:
            self.publish_reading(row)

    @property
    def stats(self) -> dict:
        return {"published": self._published, "failed": self._failed}


publisher = ReadingPublisher()
