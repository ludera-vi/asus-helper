"""Slash — световая полоса на крышке ROG (Zephyrus G14/G16 2024+, Flow и др.).

Устройство ищется как в G-Helper (SlashDevice.Detect): HID ASUS с feature-отчётом 0x5d длиной ≥ 127
(новые модели — полоса на устройстве клавиатуры) или с отчётом 0x5e (отдельное устройство, 193b).
Протокол — AnimeMatrix/SlashDevice.cs. Сегментов 7, у «длинных» полос (GA405, GU405, GU606, GX651) — 35.
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

from . import hid, sysfs
from ..i18n import _

log = logging.getLogger(__name__)

LONG_MODELS = ("GA405", "GU405", "GU606", "GX651")

# id → (код анимации, название)
MODES = {
    "bounce": (0x10, _("Отскок")),
    "slash": (0x12, _("Слэш")),
    "loading": (0x13, _("Загрузка")),
    "bitstream": (0x1D, _("Поток битов")),
    "transmission": (0x1A, _("Передача")),
    "flow": (0x19, _("Течение")),
    "flux": (0x25, _("Флюкс")),
    "phantom": (0x24, _("Фантом")),
    "spectrum": (0x26, _("Спектр")),
    "hazard": (0x32, _("Опасность")),
    "interfacing": (0x33, _("Связь")),
    "ramp": (0x34, _("Нарастание")),
    "gameover": (0x42, "Game Over"),
    "start": (0x43, _("Старт")),
    "buzzer": (0x44, _("Зуммер")),
    "static": (0x06, _("Ровный")),
    "battery": (None, _("Заряд батареи")),   # рисует сам демон: горит доля полосы по заряду
}


def _ioc(nr: int, length: int) -> int:
    return (3 << 30) | (length << 16) | (ord("H") << 8) | nr


def find_device() -> tuple[str, int, int] | None:
    """(устройство, id отчёта, длина отчёта с id) или None."""
    d = hid.find(0x5D, 127)
    if d:
        return d["dev"], 0x5D, d["features"][0x5D] + 1
    d = hid.find(0x5E, 127)
    if d:
        return d["dev"], 0x5E, d["features"][0x5E] + 1
    return None


def supported() -> bool:
    return find_device() is not None


def segments() -> int:
    model = (sysfs.read("/sys/class/dmi/id/product_name") or "") + (sysfs.read("/sys/class/dmi/id/board_name") or "")
    return 35 if any(m in model for m in LONG_MODELS) else 7


class Device:
    """Открытое устройство на время одной серии команд."""

    def __enter__(self):
        found = find_device()
        if found is None:
            raise OSError(_("полоса Slash не найдена"))
        dev, self.report, self.length = found
        self.fd = os.open(sysfs.path(dev), os.O_RDWR)
        return self

    def __exit__(self, *_):
        os.close(self.fd)

    def set(self, *data: int) -> None:
        buf = bytearray(self.length)
        buf[0] = self.report
        buf[1:1 + len(data)] = bytes(data)
        if sysfs.ROOT:              # тесты: обычный файл
            os.write(self.fd, bytes(buf))
        else:
            fcntl.ioctl(self.fd, _ioc(0x06, self.length), buf)

    def get(self) -> bytes | None:
        """Ответ устройства на предыдущую команду."""
        if sysfs.ROOT:
            return None
        buf = bytearray(self.length)
        buf[0] = self.report
        try:
            fcntl.ioctl(self.fd, _ioc(0x07, self.length), buf)
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
        n = len(segments)
        self.set(0xD3, 0x00, 0x00, n, *segments)


def battery_pattern(brightness: int, percent: float, n: int = 7) -> list[int]:
    """Доля полосы по заряду: горят сегменты справа, последний — частично (как в G-Helper)."""
    full = int(brightness * 85.333)   # 3 → 255, как (byte) в G-Helper
    step = 100 / n
    lit = int(percent // step)
    if lit >= n:
        return [full] * n
    out = [0] * n
    for i in range(n - 1, n - 1 - lit, -1):
        out[i] = full
    out[n - 1 - lit] = round((percent % step) * full / step)
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
                d.custom(battery_pattern(cfg["brightness"], battery_percent or 0, segments()))
                return True
            d.init()
            d.mode(MODES[cfg["mode"]][0])
            d.options(cfg["brightness"], cfg["interval"])
            d.save()
        return True
    except OSError as e:
        log.warning("Slash: %s", e)
        return False
