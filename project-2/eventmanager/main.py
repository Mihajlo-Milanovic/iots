"""EventManager - pretplaćuje se na očitavanja, detektuje prekoračenja pragova
i objavljuje događaje na zaseban MQTT topic."""

import json
import logging
import os
import socket
import sys
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

import health
from rules import RuleEngine

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("eventmanager")

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "iots")
QOS = int(os.getenv("MQTT_QOS", "1"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8000"))
CONFIG = os.getenv("THRESHOLDS_FILE", "thresholds.json")

READINGS_TOPIC = f"{PREFIX}/readings/+"
CLIENT_ID = os.getenv("MQTT_CLIENT_ID", f"eventmanager-{socket.gethostname()}")

engine = RuleEngine(CONFIG)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_event(reading: dict, breach: dict) -> dict:
    device_id = reading["deviceId"]
    event = {
        "eventId": f"{device_id}-{breach['field']}-{reading.get('id', 'na')}",
        "type": "THRESHOLD_EXCEEDED",
        "severity": breach["severity"],
        "deviceId": device_id,
        "field": breach["field"],
        "value": breach["value"],
        "unit": breach.get("unit"),
        "threshold": breach["threshold"],
        "operator": breach["operator"],
        "exceededBy": breach["exceededBy"],
        "readingId": reading.get("id"),
        "readingTs": reading.get("ts"),
        "detectedAt": _now_iso(),
    }
    if reading.get("location"):
        event["location"] = reading["location"]
    return event


def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        client.subscribe(READINGS_TOPIC, qos=QOS)
        health.set_state(mqtt_connected=True)
        log.info("povezan na %s:%s, pretplata na %s", MQTT_HOST, MQTT_PORT, READINGS_TOPIC)
    else:
        health.set_state(mqtt_connected=False)
        log.error("konekcija odbijena: %s", reason_code)


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    health.set_state(mqtt_connected=False)
    if reason_code != 0:
        log.warning("veza prekinuta (%s), sledi reconnect", reason_code)


def on_message(client, userdata, msg):
    try:
        reading = json.loads(msg.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        log.warning("neispravna poruka na %s: %s", msg.topic, exc)
        return

    health.bump("readings_seen")
    for breach in engine.evaluate(reading):
        event = build_event(reading, breach)
        topic = f"{PREFIX}/events/{event['deviceId']}/{event['field']}"
        client.publish(topic, json.dumps(event), qos=QOS, retain=False)
        health.bump("events_published")
        log.info("DOGAĐAJ %s %s=%s (prag %s) -> %s",
                 event["severity"], event["field"], event["value"],
                 event["threshold"], topic)


def main() -> int:
    health.start(HEALTH_PORT)
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=CLIENT_ID,
        clean_session=False,      # trajna sesija - poruke se ne gube pri restartu
    )
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)

    log.info("EventManager startuje (client_id=%s)", CLIENT_ID)
    try:
        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    except OSError as exc:
        log.error("ne mogu da se povežem na broker: %s", exc)
        return 1
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("zaustavljanje")
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
