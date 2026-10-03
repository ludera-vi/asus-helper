"""Подсветка клавиатуры: яркость (ядро, *::kbd_backlight) и цвет/эффект Aura.

Цвет — двумя путями, как в G-Helper:
  • HID: устройство ASUS с feature-отчётом 0x5d (ROG: Zephyrus, Strix, Flow…);
  • ядро: /sys/class/leds/*::kbd_backlight/kbd_rgb_mode (TUF и другие модели без HID Aura).
Протокол HID как в G-Helper (USB/Aura.cs): feature-отчёт 0x5d.
  0x5d B3 <зона> <режим> R G B <скорость> <направление> <случайный> R2 G2 B2 — эффект
  0x5d B5 — применить, 0x5d B4 — сохранить
  0x5d BD 01 <клавиатура> <полоса> <крышка> <задняя> FF — когда светиться (загрузка/работа/сон/выключение)
У отчёта 0x5d нет выходного варианта, только feature (62 байта), поэтому — HIDIOCSFEATURE.
"""
import fcntl
import logging
import os

from . import hid, sysfs
from ..i18n import _

log = logging.getLogger(__name__)

REPORT = 0x5D

MODES = {"static": 0, "breathe": 1, "cycle": 2, "strobe": 10}
SPEEDS = {"slow": 0xE1, "normal": 0xEB, "fast": 0xF5}


def _hidiocsfeature(length: int) -> int:
    # _IOC(_IOC_READ|_IOC_WRITE, 'H', 0x06, len)
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x06


# ---------- яркость (ядро) ----------
def _led() -> str | None:
    found = sysfs.find("/sys/class/leds/*::kbd_backlight")
    return found[0] if found else None


def brightness() -> dict | None:
    """{value, max}"""
    d = _led()
    if d is None:
        return None
    return {"value": sysfs.read_int(d + "/brightness", 0), "max": sysfs.read_int(d + "/max_brightness", 3)}


def set_brightness(level: int) -> bool:
    b = brightness()
    if b is None:
        return False
    return sysfs.write(_led() + "/brightness", max(0, min(b["max"], int(level))))


def brightness_hw_changed_path() -> str | None:
    """Файл, который ядро «будит» (POLLPRI), когда яркость меняют клавишами."""
    d = _led()
    return d + "/brightness_hw_changed" if d and sysfs.exists(d + "/brightness_hw_changed") else None


# ---------- Aura ----------
def find_device() -> dict | None:
    """HID-устройство клавиатуры Aura: {dev, product, features}."""
    return hid.find(REPORT)


def _wmi_rgb() -> str | None:
    """kbd_rgb_mode ядра — для моделей без HID Aura (TUF)."""
    d = _led()
    return d + "/kbd_rgb_mode" if d and sysfs.exists(d + "/kbd_rgb_mode") else None


def rgb_method() -> str | None:
    """hid | wmi | None — есть ли у клавиатуры цвет и как им управлять."""
    if find_device():
        return "hid"
    if _wmi_rgb():
        return "wmi"
    return None


def parse_color(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    if len(s) != 6:
        raise ValueError(_("цвет «{0}»: нужен вид #RRGGBB").format(s))
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def effect_message(mode: str, color: str, color2: str = "#000000", speed: str = "normal") -> bytes:
    r, g, b = parse_color(color)
    r2, g2, b2 = parse_color(color2)
    m = MODES[mode]
    # чёрный цвет — «случайные цвета», у дыхания — второй цвет
    random_flag = 0xFF if (r, g, b) == (0, 0, 0) else (1 if mode == "breathe" else 0)
    return bytes([REPORT, 0xB3, 0x00, m, r, g, b, SPEEDS[speed], 0x00, random_flag, r2, g2, b2])


def power_message(awake: bool, boot: bool, sleep: bool, shutdown: bool) -> bytes:
    """Когда светиться. Клавиатура и логотип вместе (у GU605 логотипа нет — бит ни на что не влияет)."""
    keyb = 0
    for on, bits in ((boot, 0b11), (awake, 0b1100), (sleep, 0b110000), (shutdown, 0b11000000)):
        if on:
            keyb |= bits
    return bytes([REPORT, 0xBD, 0x01, keyb, 0x00, 0x00, 0x00, 0xFF])


INIT = [bytes([REPORT, 0xB9]), bytes([REPORT]) + b"ASUS Tech.Inc."]
SET = bytes([REPORT, 0xB5, 0, 0, 0])
APPLY = bytes([REPORT, 0xB4])


def send(messages: list[bytes]) -> bool:
    found = find_device()
    if found is None:
        log.warning(_("клавиатура Aura (HID ASUS с отчётом 0x5d) не найдена"))
        return False
    dev = found["dev"]
    length = found["features"][REPORT] + 1      # + id отчёта
    try:
        fd = os.open(sysfs.path(dev), os.O_RDWR)
    except OSError as e:
        log.warning(_("не открыть %s: %s"), dev, e)
        return False
    try:
        for m in messages:
            buf = bytearray(length)
            buf[:len(m)] = m
            if sysfs.ROOT:            # тесты: обычный файл вместо устройства
                os.write(fd, bytes(buf))
            else:
                fcntl.ioctl(fd, _hidiocsfeature(length), buf)
        return True
    except OSError as e:
        log.warning(_("Aura: запись не удалась: %s"), e)
        return False
    finally:
        os.close(fd)


def apply(cfg: dict) -> bool:
    """cfg: {mode, color, color2, speed, awake, boot, sleep, shutdown}"""
    method = rgb_method()
    if method == "wmi":
        # «cmd mode R G B speed»: cmd 1 — применить и сохранить
        r, g, b = parse_color(cfg["color"])
        return sysfs.write(_wmi_rgb(), f"1 {MODES[cfg['mode']]} {r} {g} {b} {SPEEDS[cfg['speed']]}")
    if method is None:
        return False
    return send([
        *INIT,
        effect_message(cfg["mode"], cfg["color"], cfg.get("color2", "#000000"), cfg["speed"]),
        SET, APPLY,
        power_message(cfg["awake"], cfg["boot"], cfg["sleep"], cfg["shutdown"]),
    ])
