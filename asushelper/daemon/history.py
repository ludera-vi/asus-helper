"""История для графиков: датчики за последний час и здоровье батареи по дням.

Датчики — раз в 5 секунд в память (за час 720 точек, ~50 КБ): температура CPU, обороты
вентиляторов, мощность батареи. Только дешёвые чтения sysfs; NVIDIA не трогаем, чтобы не будить.
Здоровье батареи (ёмкость сейчас / паспортная) — раз в день в /var/lib/asus-helper/battery.json.
"""
import collections
import json
import logging
import os
import time

from gi.repository import GLib

from . import hardware as hw

log = logging.getLogger(__name__)

SAMPLE_S = 5
KEEP_S = 3600
STATE_DIR = os.environ.get("ASUSHELPER_STATE_DIR", "/var/lib/asus-helper")
HEALTH_FILE = os.path.join(STATE_DIR, "battery.json")


class History:
    def __init__(self):
        self.samples = collections.deque(maxlen=KEEP_S // SAMPLE_S)
        self.health = self._load_health()

    def start(self) -> None:
        self._sample()
        GLib.timeout_add_seconds(SAMPLE_S, self._sample)

    def _sample(self) -> bool:
        b = hw.battery() or {}
        fans = hw.fan_rpm()
        # мощность со знаком: + разряд, − заряд (у батареи ток всегда положительный — смотрим статус)
        power = b.get("power_w")
        if power is not None and b.get("status") == "Charging":
            power = -power
        self.samples.append((int(time.time()), hw.cpu_temp(), fans.get("cpu"), fans.get("gpu"), power))
        self._record_health(b)
        return GLib.SOURCE_CONTINUE

    def dump(self) -> dict:
        cols = list(zip(*self.samples)) if self.samples else [[], [], [], [], []]
        return {
            "interval": SAMPLE_S,
            "t": list(cols[0]), "cpu_temp": list(cols[1]),
            "fan_cpu": list(cols[2]), "fan_gpu": list(cols[3]), "battery_w": list(cols[4]),
            "health": self.health,
        }

    # ---------- здоровье батареи ----------
    def _load_health(self) -> list:
        try:
            with open(HEALTH_FILE) as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _record_health(self, b: dict) -> None:
        today = time.strftime("%Y-%m-%d")
        if not b.get("health") or (self.health and self.health[-1]["date"] == today):
            return
        self.health.append({"date": today, "health": b["health"]})
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
            tmp = HEALTH_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.health, f)
            os.replace(tmp, HEALTH_FILE)
        except OSError as e:
            log.warning("не сохранить %s: %s", HEALTH_FILE, e)
