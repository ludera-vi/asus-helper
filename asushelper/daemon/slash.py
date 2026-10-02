"""Slash — световая полоса на крышке (HID 0b05:193b, feature-отчёт 0x5e, 128 байт).

Протокол как в G-Helper (AnimeMatrix/SlashDevice.cs). У GU605 на полосе 7 сегментов.
  включить/выключить        D8 02 00 01 <00|80>
  режим (анимация)          D2 03 00 0C → прочитать записи, D3 04 … <режим>
  яркость и пауза           D3 03 01 08 AB FF 01 01 06 <яркость> FF <пауза>
  сохранить                 D4 00 00 01 AB
  светиться на батарее      D8 01 00 01 <00|80>
  светиться с закрытой крышкой  D8 00 00 02 A5 <00|80>
  свой рисунок (заряд)      D2 02 01 08 AC, D3 03 01 08 AC FF FF 01 05 FF FF, D4 00 00 01 AC, D3 00 00 07 <7 байт>
"""
import fcntl
import logging
import os

from . import sysfs

log = logging.getLogger(__name__)

VENDOR, PRODUCT = 0x0B05, 0x193B
REPORT = 0x5E
FEATURE_LEN = 128
SEGMENTS = 7

# id → (код анимации, название)
MODES = {
    "bounce": (0x10, "Отскок"),
    "slash": (0x12, "Слэш"),
    "loading": (0x13, "Загрузка"),
    "bitstream": (0x1D, "Поток битов"),
    "transmission": (0x1A, "Передача"),
    "flow": (0x19, "Течение"),
    "flux": (0x25, "Флюкс"),
    "phantom": (0x24, "Фантом"),
    "spectrum": (0x26, "Спектр"),
    "hazard": (0x32, "Опасность"),
    "interfacing": (0x33, "Связь"),
    "ramp": (0x34, "Нарастание"),
    "gameover": (0x42, "Game Over"),
    "start": (0x43, "Старт"),
    "buzzer": (0x44, "Зуммер"),
    "static": (0x06, "Ровный"),
    "battery": (None, "Заряд батареи"),   # рисует сам демон: горит доля полосы по заряду
}


def _ioc(nr: int, length: int) -> int:
    return (3 << 30) | (length << 16) | (ord("H") << 8) | nr


HIDIOCSFEATURE = _ioc(0x06, FEATURE_LEN)
HIDIOCGFEATURE = _ioc(0x07, FEATURE_LEN)


def find_device() -> str | None:
    want = f"{VENDOR:08X}:{PRODUCT:08X}"
    for h in sysfs.find("/sys/class/hidraw/hidraw*"):
        if want in (sysfs.read(h + "/device/uevent") or "").upper():
            return "/dev/" + os.path.basename(h)
    return None


def supported() -> bool:
    return find_device() is not None


class Device:
    """Открытое устройство на время одной серии команд."""

    def __enter__(self):
        dev = find_device()
        if dev is None:
            raise OSError("полоса Slash (0b05:193b) не найдена")
        self.fd = os.open(sysfs.path(dev), os.O_RDWR)
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def set(self, *data: int) -> None:
        buf = bytearray(FEATURE_LEN)
        buf[0] = REPORT
        buf[1:1 + len(data)] = bytes(data)
        if sysfs.ROOT:              # тесты: обычный файл
            os.write(self.fd, bytes(buf))
        else:
            fcntl.ioctl(self.fd, HIDIOCSFEATURE, buf)

    def get(self) -> bytes | None:
        """Ответ устройства на предыдущую команду."""
        if sysfs.ROOT:
            return None
        buf = bytearray(FEATURE_LEN)
        buf[0] = REPORT
        try:
            fcntl.ioctl(self.fd, HIDIOCGFEATURE, buf)
            return bytes(buf)
        except OSError:
            return None

    # ---------- команды ----------
    def wake_up(self):
        self.set(*b"ASUS Tech.Inc.")
        self.set(0xC2)
        self.set(0xD1, 0x01, 0x00, 0x01)

    def init(self):
        self.set(0xD7, 0x00, 0x00, 0x01, 0xAC)
        self.set(0xD2, 0x02, 0x01, 0x08, 0xAB)

    def enabled(self, on: bool):
        self.set(0xD8, 0x02, 0x00, 0x01, 0x00 if on else 0x80)

    def mode(self, code: int):
        # прочитать текущие записи анимаций и поменять только первую — как G-Helper
        self.set(0xD2, 0x03, 0x00, 0x0C)
        pool = self.get()
        if pool and pool[5] == 0x01:
            pool = bytearray(pool)
            pool[1], pool[2], pool[6] = 0xD3, 0x04, code
            self.set(*pool[1:])
        else:
            self.set(0xD3, 0x04, 0x00, 0x0C, 0x01, code, 0x02, 0x42, 0x03, 0x13, 0x04, 0x11, 0x05, 0x12, 0x06, 0x13)

    def options(self, brightness: int, interval: int):
        self.set(0xD3, 0x03, 0x01, 0x08, 0xAB, 0xFF, 0x01, 0x01, 0x06, int(brightness * 85.333), 0xFF, interval)

    def save(self):
        self.set(0xD4, 0x00, 0x00, 0x01, 0xAB)

    def on_battery(self, on: bool):
        self.set(0xD8, 0x01, 0x00, 0x01, 0x00 if on else 0x80)

    def lid_closed(self, on: bool):
        self.set(0xD8, 0x00, 0x00, 0x02, 0xA5, 0x00 if on else 0x80)

    def custom(self, segments: list[int]):
        self.set(0xD2, 0x02, 0x01, 0x08, 0xAC)
        self.set(0xD3, 0x03, 0x01, 0x08, 0xAC, 0xFF, 0xFF, 0x01, 0x05, 0xFF, 0xFF)
        self.set(0xD4, 0x00, 0x00, 0x01, 0xAC)
        self.set(0xD3, 0x00, 0x00, SEGMENTS, *segments[:SEGMENTS])


def battery_pattern(brightness: int, percent: float) -> list[int]:
    """Доля полосы по заряду: горят сегменты справа, последний — частично (как в G-Helper)."""
    full = int(brightness * 85.333)   # 3 → 255, как (byte) в G-Helper
    step = 100 / SEGMENTS
    lit = int(percent // step)
    if lit >= SEGMENTS:
        return [full] * SEGMENTS
    out = [0] * SEGMENTS
    for i in range(SEGMENTS - 1, SEGMENTS - 1 - lit, -1):
        out[i] = full
    out[SEGMENTS - 1 - lit] = round((percent % step) * full / step)
    return out


def apply(cfg: dict, battery_percent: float | None = None, wake: bool = False) -> bool:
    """cfg: {brightness 0–3, mode, interval, on_battery, lid_closed}"""
    try:
        with Device() as d:
            if wake:
                d.wake_up()
            d.on_battery(cfg["on_battery"])
            d.lid_closed(cfg["lid_closed"])
            if cfg["brightness"] <= 0:
                d.enabled(False)
                return True
            d.enabled(True)
            if cfg["mode"] == "battery":
                d.custom(battery_pattern(cfg["brightness"], battery_percent or 0))
                return True
            d.init()
            d.mode(MODES[cfg["mode"]][0])
            d.options(cfg["brightness"], cfg["interval"])
            d.save()
        return True
    except OSError as e:
        log.warning("Slash: %s", e)
        return False
