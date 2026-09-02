"""Pravila za detekciju događaja nad očitavanjima."""

import json
import logging
import os
import time
from typing import Any

log = logging.getLogger("eventmanager.rules")

OPERATORS = {
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
}


class RuleEngine:
    """Primenjuje pragove i sprečava poplavu identičnih događaja (cooldown)."""

    def __init__(self, config_path: str) -> None:
        with open(config_path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        self.cooldown = float(os.getenv("COOLDOWN_SECONDS", cfg.get("cooldownSeconds", 60)))
        self.global_rules: dict[str, dict] = {
            k: v for k, v in cfg.get("global", {}).items() if not k.startswith("_")
        }
        self.device_rules: dict[str, dict] = {
            dev: {k: v for k, v in rules.items() if not k.startswith("_")}
            for dev, rules in cfg.get("devices", {}).items()
            if not dev.startswith("_")
        }
        self._last_event: dict[tuple[str, str], float] = {}
        log.info("učitana pravila: %s globalnih, %s uređaja sa override-om, cooldown %.0fs",
                 len(self.global_rules), len(self.device_rules), self.cooldown)

    def rules_for(self, device_id: str) -> dict[str, dict]:
        """Globalna pravila, prepisana per-device vrednostima ako postoje."""
        merged = dict(self.global_rules)
        merged.update(self.device_rules.get(device_id, {}))
        return merged

    def _in_cooldown(self, device_id: str, field: str, now: float) -> bool:
        last = self._last_event.get((device_id, field))
        return last is not None and (now - last) < self.cooldown

    def evaluate(self, reading: dict[str, Any], now: float | None = None) -> list[dict]:
        """Vrati listu prekoračenja za dato očitavanje (poštujući cooldown)."""
        now = time.monotonic() if now is None else now
        device_id = reading.get("deviceId")
        if not device_id:
            return []

        found = []
        for field, rule in self.rules_for(device_id).items():
            value = reading.get(field)
            if value is None:
                continue
            check = OPERATORS.get(rule.get("operator", "gt"))
            if check is None:
                log.warning("nepoznat operator %r za polje %s", rule.get("operator"), field)
                continue
            threshold = rule["threshold"]
            if not check(value, threshold):
                continue
            if self._in_cooldown(device_id, field, now):
                continue
            self._last_event[(device_id, field)] = now

            critical = rule.get("critical")
            severity = "CRITICAL" if critical is not None and check(value, critical) else "WARNING"
            found.append({
                "field": field,
                "value": value,
                "threshold": threshold,
                "operator": rule.get("operator", "gt"),
                "severity": severity,
                "unit": rule.get("unit"),
                "exceededBy": round(abs(value - threshold), 6),
            })
        return found
