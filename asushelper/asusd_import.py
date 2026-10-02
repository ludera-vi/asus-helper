"""Перенос настроек из asusd (/etc/asusd/*.ron) в config.json asushelper.

Берёт кривые вентиляторов по режимам, режим на сети и батарее, связку режим → EPP и лимит заряда.
Формат RON разбирается регулярными выражениями: нужны только эти поля.
"""
import glob
import re

from . import PROFILES

EPP_NAMES = {"Default": "default", "Performance": "performance", "BalancePerformance": "balance_performance",
             "BalancePower": "balance_power", "Power": "power"}
PROFILE_NAMES = {"Quiet": "quiet", "Balanced": "balanced", "Performance": "performance", "LowPower": "quiet"}


def _tuple(s: str) -> list[int]:
    return [int(x) for x in s.replace(" ", "").split(",") if x]


def parse_fan_curves(text: str) -> dict:
    """{profile: {cpu|gpu: {enabled, temp, pwm}}}"""
    out = {}
    for profile in PROFILES:
        m = re.search(rf"\b{profile}\s*:\s*\[(.*?)\]", text, re.S)
        if not m:
            continue
        curves = {}
        for block in re.finditer(r"\(\s*fan:\s*(\w+),\s*pwm:\s*\(([^)]*)\),\s*temp:\s*\(([^)]*)\),\s*enabled:\s*(\w+)", m.group(1)):
            fan, pwm, temp, enabled = block.groups()
            fan = fan.lower()
            if fan in ("cpu", "gpu", "mid"):
                curves[fan] = {"enabled": enabled == "true", "temp": _tuple(temp), "pwm": _tuple(pwm)}
        if curves:
            out[profile] = curves
    return out


def _field(text: str, name: str) -> str | None:
    m = re.search(rf"\b{name}\s*:\s*([^,\n]+)", text)
    return m.group(1).strip().strip('"') if m else None


def parse_asusd(text: str) -> dict:
    out = {"profiles": {}}
    if (v := _field(text, "charge_control_end_threshold")) and v.isdigit():
        out["charge_limit"] = int(v)
    if (v := _field(text, "platform_profile_on_ac")) in PROFILE_NAMES:
        out["profile_on_ac"] = PROFILE_NAMES[v]
    if (v := _field(text, "platform_profile_on_battery")) in PROFILE_NAMES:
        out["profile_on_battery"] = PROFILE_NAMES[v]
    if (v := _field(text, "disable_nvidia_powerd_on_battery")) in ("true", "false"):
        out["stop_nvidia_powerd_on_battery"] = v == "true"
    if _field(text, "platform_profile_linked_epp") != "false":
        for profile in PROFILES:
            if (v := _field(text, f"profile_{profile}_epp")) in EPP_NAMES:
                out["profiles"].setdefault(profile, {})["epp"] = EPP_NAMES[v]
    return out


AURA_MODES = {"Static": "static", "Breathe": "breathe", "RainbowCycle": "cycle", "Pulse": "strobe"}
AURA_SPEEDS = {"Low": "slow", "Med": "normal", "High": "fast"}
AURA_BRIGHTNESS = {"Off": 0, "Low": 1, "Med": 2, "High": 3}


def parse_aura(text: str) -> dict:
    """aura_*.ron: текущий эффект, его цвета и скорость, яркость, состояния питания клавиатуры."""
    out = {}
    if (v := _field(text, "brightness")) in AURA_BRIGHTNESS:
        out["brightness"] = AURA_BRIGHTNESS[v]
    mode = _field(text, "current_mode")
    if mode in AURA_MODES:
        out["mode"] = AURA_MODES[mode]
        m = re.search(rf"\b{mode}\s*:\s*\((.*?)\n        \),", text, re.S)
        if m:
            block = m.group(1)
            colours = re.findall(r"colour\d:\s*\(\s*r:\s*(\d+),\s*g:\s*(\d+),\s*b:\s*(\d+)", block)
            if colours:
                out["color"] = "#%02X%02X%02X" % tuple(map(int, colours[0]))
            if len(colours) > 1:
                out["color2"] = "#%02X%02X%02X" % tuple(map(int, colours[1]))
            if (v := _field(block, "speed")) in AURA_SPEEDS:
                out["speed"] = AURA_SPEEDS[v]
    m = re.search(r"zone:\s*Keyboard,\s*boot:\s*(\w+),\s*awake:\s*(\w+),\s*sleep:\s*(\w+),\s*shutdown:\s*(\w+)", text)
    if m:
        out.update(zip(("boot", "awake", "sleep", "shutdown"), (x == "true" for x in m.groups())))
    return out


def import_into(config, asusd_dir: str = "/etc/asusd") -> list[str]:
    """Переносит настройки в объект Config; возвращает список того, что перенесено."""
    done = []
    try:
        with open(f"{asusd_dir}/asusd.ron") as f:
            a = parse_asusd(f.read())
        for k in ("charge_limit", "profile_on_ac", "profile_on_battery", "stop_nvidia_powerd_on_battery"):
            if k in a:
                config.data[k] = a[k]
                done.append(f"{k} = {a[k]}")
        for profile, p in a["profiles"].items():
            config.profile(profile)["epp"] = p["epp"]
            done.append(f"{profile}: EPP {p['epp']}")
    except FileNotFoundError:
        pass
    try:
        with open(f"{asusd_dir}/fan_curves.ron") as f:
            curves = parse_fan_curves(f.read())
        for profile, fans in curves.items():
            for fan, c in fans.items():
                config.profile(profile)["fan_curves"][fan] = c if c["enabled"] else None
                done.append(f"{profile}: кривая {fan.upper()}" + ("" if c["enabled"] else " (выключена — BIOS)"))
    except FileNotFoundError:
        pass
    for path in sorted(glob.glob(f"{asusd_dir}/aura_*.ron"))[:1]:
        with open(path) as f:
            a = parse_aura(f.read())
        config.data["keyboard"].update(a)
        done.append("подсветка: " + ", ".join(f"{k} = {v}" for k, v in a.items()))
    return done
