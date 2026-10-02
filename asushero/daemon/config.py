"""Настройки демона: /etc/asushero/config.json.

Файл можно править руками (потом: systemctl reload asusherod), но обычно его меняет демон
по командам из приложения. Сохраняется атомарно, чтобы сбой питания не оставил пустой файл.
"""
import copy
import json
import logging
import os

from .. import FANS, PROFILES

log = logging.getLogger(__name__)

CONFIG_DIR = os.environ.get("ASUSHERO_CONFIG_DIR", "/etc/asushero")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_EPP = {"quiet": "power", "balanced": "balance_power", "performance": "performance"}


def default_profile() -> dict:
    return {
        "epp": None,             # None — по умолчанию из DEFAULT_EPP
        # своя кривая для вентилятора; null — кривая BIOS для этого режима
        "fan_curves": {f: None for f in FANS},
        # параметры asus-armoury (ppt_pl1_spl, nv_temp_target …); отсутствие — не трогать
        "power_limits": {},
    }


DEFAULTS = {
    "version": 1,
    # Режим, который включается от сети и от батареи. Выбор режима вручную
    # запоминается для текущего источника питания (как в G-Helper).
    "profile_on_ac": "balanced",
    "profile_on_battery": "quiet",
    "auto_profile": True,
    "charge_limit": 100,
    # Отключать nvidia-powerd на батарее (Dynamic Boost не нужен без сети)
    "stop_nvidia_powerd_on_battery": True,
    "profiles": {p: default_profile() for p in PROFILES},
}


def _merge(base: dict, over: dict) -> dict:
    """Рекурсивно накладывает over на base; неизвестные ключи из over сохраняются."""
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


class Config:
    def __init__(self, path: str = CONFIG_FILE):
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)

    def load(self) -> "Config":
        try:
            with open(self.path) as f:
                self.data = _merge(DEFAULTS, json.load(f))
        except FileNotFoundError:
            log.info("нет %s — настройки по умолчанию", self.path)
        except (OSError, ValueError) as e:
            log.error("не удалось прочитать %s: %s — настройки по умолчанию", self.path, e)
        return self

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # ---------- удобный доступ ----------
    def profile(self, name: str) -> dict:
        return self.data["profiles"][name]

    def epp(self, name: str) -> str:
        return self.profile(name).get("epp") or DEFAULT_EPP[name]

    def profile_for(self, ac: bool) -> str:
        p = self.data["profile_on_ac" if ac else "profile_on_battery"]
        return p if p in PROFILES else "balanced"

    def remember_profile(self, ac: bool, name: str) -> None:
        self.data["profile_on_ac" if ac else "profile_on_battery"] = name
