"""Доступ к железу ноутбука через интерфейсы ядра (asus-wmi, asus-armoury, cpufreq, hwmon, power_supply).
Что есть у конкретной модели — определяется по наличию файлов, списков моделей нет.

Здесь нет логики «когда что применять» — только чтение и запись. Логика в modes.py.
"""
import logging

from .. import FANS
from . import sysfs
from ..i18n import _

log = logging.getLogger(__name__)

# ---------- модель ----------
def model() -> dict:
    """Из DMI: {vendor, family, product, board, name} — name для заголовка окна."""
    dmi = {k: sysfs.read(f"/sys/class/dmi/id/{f}") or "" for k, f in
           (("vendor", "sys_vendor"), ("family", "product_family"), ("product", "product_name"), ("board", "board_name"))}
    family, board = dmi["family"], dmi["board"]
    # «ROG Zephyrus G16 GU605MZ_GU605MZ» → «ROG Zephyrus G16 GU605MZ»
    name = f"{family} {board}".strip() if family and board and board not in family else (family or dmi["product"].split("_")[0])
    return {**dmi, "name": name}


def cpu_driver() -> str:
    return sysfs.read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_driver") or "unknown"


# ---------- режим производительности ----------
PROFILE = "/sys/firmware/acpi/platform_profile"
PROFILE_CHOICES = "/sys/firmware/acpi/platform_profile_choices"


def profile() -> str | None:
    return sysfs.read(PROFILE)


def profile_choices() -> list[str]:
    return (sysfs.read(PROFILE_CHOICES) or "").split()


def set_profile(name: str) -> bool:
    return sysfs.write(PROFILE, name)


# ---------- EPP процессора (intel_pstate / amd-pstate) ----------
EPP_GLOB = "/sys/devices/system/cpu/cpu[0-9]*/cpufreq/energy_performance_preference"
EPP_CHOICES = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_available_preferences"


def epp() -> str | None:
    return sysfs.read("/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference")


def epp_choices() -> list[str]:
    return (sysfs.read(EPP_CHOICES) or "").split()


def set_epp(value: str) -> bool:
    if not epp_choices():
        return False              # драйвер процессора без EPP (acpi-cpufreq и т. п.) — молча пропускаем
    if value not in epp_choices():
        log.warning(_("EPP «%s» не поддерживается (есть: %s)"), value, epp_choices())
        return False
    return all([sysfs.write(p, value) for p in sysfs.find(EPP_GLOB)])


# ---------- Turbo Boost / Precision Boost ----------
NO_TURBO = "/sys/devices/system/cpu/intel_pstate/no_turbo"     # Intel: 1 — выключен
BOOST = "/sys/devices/system/cpu/cpufreq/boost"                 # AMD и acpi-cpufreq: 1 — включён


def turbo() -> bool | None:
    if (v := sysfs.read(NO_TURBO)) is not None:
        return v == "0"
    if (v := sysfs.read(BOOST)) is not None:
        return v == "1"
    return None


def set_turbo(on: bool) -> bool:
    cur = turbo()
    if cur is None:
        return False
    if cur == on:
        return True
    if sysfs.exists(NO_TURBO):
        return sysfs.write(NO_TURBO, 0 if on else 1)
    return sysfs.write(BOOST, 1 if on else 0)


# ---------- настройки BIOS (asus-armoury) ----------
ARMOURY = "/sys/class/firmware-attributes/asus-armoury/attributes"
# Числовые параметры мощности (что из них есть — зависит от модели); min/max ядро меняет
# при переключении сеть ↔ батарея
POWER_ATTRS = ("ppt_pl1_spl", "ppt_pl2_sppt", "ppt_pl3_fppt", "ppt_fppt", "ppt_apu_sppt", "ppt_platform_sppt",
               "nv_dynamic_boost", "nv_temp_target", "nv_base_tgp", "nv_tgp")
# Переключатели 0/1
TOGGLE_ATTRS = ("panel_overdrive", "boot_sound")


def armoury_attr(name: str) -> dict | None:
    """{value, min, max, default} или None, если параметра нет."""
    d = f"{ARMOURY}/{name}"
    if not sysfs.exists(d + "/current_value"):
        return None
    return {
        "value": sysfs.read_int(d + "/current_value"),
        "min": sysfs.read_int(d + "/min_value"),
        "max": sysfs.read_int(d + "/max_value"),
        "default": sysfs.read_int(d + "/default_value"),
    }


def power_limits() -> dict[str, dict]:
    return {n: a for n in POWER_ATTRS if (a := armoury_attr(n)) is not None}


def set_armoury(name: str, value: int) -> bool:
    """Пишет параметр, ограничив его текущими min/max (они разные от сети и от батареи)."""
    a = armoury_attr(name)
    if a is None:
        return False
    v = int(value)
    if a["min"] is not None:
        v = max(v, a["min"])
    if a["max"] is not None:
        v = min(v, a["max"])
    if v != value:
        log.info(_("%s: %s ограничено до %s (допустимо %s–%s)"), name, value, v, a["min"], a["max"])
    if v == a["value"]:
        return True
    return sysfs.write(f"{ARMOURY}/{name}/current_value", v)


# ---------- вентиляторы ----------
# pwm1 — вентилятор CPU, pwm2 — GPU, pwm3 — средний (есть не у всех). Кривая — 8 точек (°C → pwm 0–255).
CURVE_POINTS = 8
FAN_INDEX = {"cpu": 1, "gpu": 2, "mid": 3}
# pwmN_enable у asus_custom_fan_curve: 1 — своя кривая, 2 — кривая BIOS, 3 — сброс точек к заводским
CURVE_ON, CURVE_BIOS, CURVE_RESET = 1, 2, 3


def _curve_dir() -> str | None:
    return sysfs.hwmon("asus_custom_fan_curve")


def has_fan_curves() -> bool:
    return _curve_dir() is not None


def curve_fans() -> list[str]:
    """Вентиляторы, которым можно задать свою кривую."""
    d = _curve_dir()
    return [f for f in FANS if d and sysfs.exists(f"{d}/pwm{FAN_INDEX[f]}_enable")]


def fans() -> list[str]:
    """Вентиляторы, у которых ядро показывает обороты."""
    d = sysfs.hwmon("asus")
    return [f for f in FANS if d and sysfs.exists(f"{d}/fan{FAN_INDEX[f]}_input")]


def fan_curve(fan: str) -> dict | None:
    """{enabled, temp[8], pwm[8]} — то, что сейчас записано в ядре."""
    d = _curve_dir()
    if d is None:
        return None
    i = FAN_INDEX[fan]
    temp, pwm = [], []
    for p in range(1, CURVE_POINTS + 1):
        temp.append(sysfs.read_int(f"{d}/pwm{i}_auto_point{p}_temp", 0))
        pwm.append(sysfs.read_int(f"{d}/pwm{i}_auto_point{p}_pwm", 0))
    return {"enabled": sysfs.read_int(f"{d}/pwm{i}_enable") == CURVE_ON, "temp": temp, "pwm": pwm}


def validate_curve(temp: list[int], pwm: list[int]) -> str | None:
    """Текст ошибки или None. BIOS требует неубывающие температуры и обороты."""
    if len(temp) != CURVE_POINTS or len(pwm) != CURVE_POINTS:
        return _("нужно ровно {0} точек").format(CURVE_POINTS)
    if any(not 0 <= t <= 120 for t in temp):
        return _("температура должна быть от 0 до 120 °C")
    if any(not 0 <= p <= 255 for p in pwm):
        return _("обороты (pwm) должны быть от 0 до 255")
    if any(b < a for a, b in zip(temp, temp[1:])):
        return _("температуры точек должны не убывать")
    if any(b < a for a, b in zip(pwm, pwm[1:])):
        return _("обороты точек должны не убывать")
    return None


def set_fan_curve(fan: str, temp: list[int], pwm: list[int]) -> bool:
    """Записывает точки и включает свою кривую. Ядро отправляет кривую в BIOS только при pwmN_enable=1."""
    d = _curve_dir()
    if d is None:
        return False
    if err := validate_curve(temp, pwm):
        log.warning(_("кривая %s отклонена: %s"), fan, err)
        return False
    i = FAN_INDEX[fan]
    ok = True
    for p in range(CURVE_POINTS):
        ok &= sysfs.write(f"{d}/pwm{i}_auto_point{p + 1}_temp", temp[p])
        ok &= sysfs.write(f"{d}/pwm{i}_auto_point{p + 1}_pwm", pwm[p])
    return sysfs.write(f"{d}/pwm{i}_enable", CURVE_ON) and ok


def set_fan_curve_mode(fan: str, mode: int) -> bool:
    d = _curve_dir()
    return d is not None and sysfs.write(f"{d}/pwm{FAN_INDEX[fan]}_enable", mode)


def factory_fan_curve(fan: str) -> dict | None:
    """Заводская кривая BIOS для текущего режима (сбрасывает точки в ядре и выключает свою кривую)."""
    if not set_fan_curve_mode(fan, CURVE_RESET):
        return None
    c = fan_curve(fan)
    set_fan_curve_mode(fan, CURVE_BIOS)
    return c


def fan_rpm() -> dict[str, int | None]:
    d = sysfs.hwmon("asus")
    return {f: sysfs.read_int(f"{d}/fan{FAN_INDEX[f]}_input") for f in fans()}


# ---------- температуры ----------
# (hwmon, подпись датчика) по порядку: Intel, AMD, запасной вариант ACPI
CPU_SENSORS = (("coretemp", "Package id 0"), ("k10temp", "Tctl"), ("k10temp", "Tdie"),
               ("zenpower", "Tdie"), ("acpitz", None))


def cpu_temp() -> float | None:
    """Температура процессора, °C."""
    for name, label in CPU_SENSORS:
        d = sysfs.hwmon(name)
        if d is None:
            continue
        if label is None:
            v = sysfs.read_int(d + "/temp1_input")
            return v / 1000 if v is not None else None
        for lab in sysfs.find(d + "/temp*_label"):
            if sysfs.read(lab) == label:
                v = sysfs.read_int(lab.replace("_label", "_input"))
                return v / 1000 if v is not None else None
    return None


# ---------- питание и батарея ----------
def _supply(kind: str) -> str | None:
    for d in sysfs.find("/sys/class/power_supply/*"):
        if sysfs.read(d + "/type") == kind:
            return d
    return None


def on_ac() -> bool:
    d = _supply("Mains")
    return d is not None and sysfs.read(d + "/online") == "1"


def battery() -> dict | None:
    d = _supply("Battery")
    if d is None:
        return None
    current = sysfs.read_int(d + "/current_now", 0)
    voltage = sysfs.read_int(d + "/voltage_now", 0)
    full = sysfs.read_int(d + "/charge_full") or sysfs.read_int(d + "/energy_full")
    design = sysfs.read_int(d + "/charge_full_design") or sysfs.read_int(d + "/energy_full_design")
    return {
        "capacity": sysfs.read_int(d + "/capacity"),
        "status": sysfs.read(d + "/status"),
        "power_w": round(current * voltage / 1e12, 1),
        "health": round(full * 100 / design) if full and design else None,
        "charge_limit": sysfs.read_int(d + "/charge_control_end_threshold"),
    }


def set_charge_limit(percent: int) -> bool:
    d = _supply("Battery")
    if d is None or not sysfs.exists(d + "/charge_control_end_threshold"):
        return False
    return sysfs.write(d + "/charge_control_end_threshold", max(20, min(100, int(percent))))
