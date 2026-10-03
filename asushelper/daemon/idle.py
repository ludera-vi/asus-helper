"""Подсветка клавиатуры гаснет, если клавиатурой и тачпадом не пользуются, и загорается от первого касания.

Как в G-Helper («Backlight timeout»). Активность — любое событие от клавиатур и указателей
(/dev/input/event*): события читаются и выбрасываются, что нажато — не смотрим и не храним.
Время своё для сети и для батареи; 0 — не гаснуть.
"""
import logging
import os
import struct
import time

from gi.repository import GLib

from . import aura, sysfs
from ..i18n import _

log = logging.getLogger(__name__)

CHECK_S = 2
# struct input_event на 64-битной системе: время (16 байт), тип, код, значение
EVENT = struct.Struct("llHHi")
EV_KEY, EV_REL, EV_ABS = 1, 2, 3
RESCAN_S = 30      # новые устройства (Bluetooth-клавиатура, мышь)
KEY_A = 30


def _activity_devices() -> list[str]:
    """event-узлы клавиатур (есть клавиша A) и указателей (обработчик mouse)."""
    out = []
    try:
        with open(sysfs.path("/proc/bus/input/devices")) as f:
            blocks = f.read().split("\n\n")
    except OSError:
        return out
    for b in blocks:
        handlers = next((l.split("=", 1)[1].split() for l in b.splitlines() if l.startswith("H: Handlers=")), [])
        keys = next((l.split("=", 1)[1].split() for l in b.splitlines() if l.startswith("B: KEY=")), [])
        event = next((h for h in handlers if h.startswith("event")), None)
        if not event:
            continue
        # битовая карта клавиш: слова по 64 бита, младшее — последнее
        has_a = bool(keys) and len(keys) >= 1 and (int(keys[-1], 16) >> KEY_A) & 1
        if has_a or any(h.startswith("mouse") for h in handlers):
            out.append(event)
    return out


def is_activity(data: bytes) -> bool:
    """Есть ли среди событий действие человека: нажатие клавиши, движение мыши, касание тачпада.
    Служебные события (синхронизация, коды сканирования, светодиоды, отпускание клавиш) — нет."""
    for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
        _sec, _usec, etype, _code, value = EVENT.unpack_from(data, i)
        if (etype == EV_KEY and value != 0) or (etype == EV_REL and value != 0) or etype == EV_ABS:
            return True
    return False


class KeyboardIdle:
    def __init__(self, config, on_ac):
        self.config = config
        self.on_ac = on_ac            # () -> bool
        self.fds: dict[str, int] = {}
        self.last = time.monotonic()
        self.dimmed_from: int | None = None   # яркость до того, как погасили
        self._scan()
        GLib.timeout_add_seconds(CHECK_S, self._check)
        GLib.timeout_add_seconds(RESCAN_S, self._rescan)

    def timeout(self) -> int:
        k = self.config.data["keyboard"]
        return int(k.get("timeout_ac" if self.on_ac() else "timeout_battery", 0) or 0)

    # ---------- устройства ----------
    def _scan(self) -> None:
        if sysfs.ROOT:
            return
        for node in _activity_devices():
            if node in self.fds:
                continue
            try:
                fd = os.open("/dev/input/" + node, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self.fds[node] = fd
            GLib.io_add_watch(fd, GLib.PRIORITY_LOW, GLib.IOCondition.IN | GLib.IOCondition.HUP | GLib.IOCondition.ERR,
                              self._on_input, node)

    def _rescan(self) -> bool:
        self._scan()
        return GLib.SOURCE_CONTINUE

    def _on_input(self, fd, cond, node) -> bool:
        if cond & (GLib.IOCondition.HUP | GLib.IOCondition.ERR):
            os.close(fd)            # устройство отключили
            self.fds.pop(node, None)
            return GLib.SOURCE_REMOVE
        active = False
        try:
            while data := os.read(fd, EVENT.size * 64):
                active |= is_activity(data)
        except BlockingIOError:
            pass
        except OSError:
            os.close(fd)
            self.fds.pop(node, None)
            return GLib.SOURCE_REMOVE
        if active:
            self.activity()
        return GLib.SOURCE_CONTINUE

    # ---------- логика ----------
    def activity(self) -> None:
        self.last = time.monotonic()
        if self.dimmed_from is not None:
            level, self.dimmed_from = self.dimmed_from, None
            # если за это время яркость поменяли клавишами — не перебиваем
            if (aura.brightness() or {}).get("value") == 0:
                aura.set_brightness(level)
                log.info(_("подсветка клавиатуры: снова горит"))

    def _check(self) -> bool:
        t = self.timeout()
        if t <= 0 or self.dimmed_from is not None:
            return GLib.SOURCE_CONTINUE
        b = aura.brightness()
        if b and b["value"] > 0 and time.monotonic() - self.last >= t:
            self.dimmed_from = b["value"]
            aura.set_brightness(0)
            log.info(_("подсветка клавиатуры: погашена — %d с без нажатий"), t)
        return GLib.SOURCE_CONTINUE

    def reset(self) -> None:
        """После сна или смены настроек — считать, что только что пользовались."""
        self.last = time.monotonic()
        self.dimmed_from = None
