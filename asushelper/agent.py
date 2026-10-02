"""asus-helper-agent — помощник в сеансе пользователя (замена asus-osd).

Слушает демон на системной шине и показывает карточки KDE:
  • смена режима (Fn+F5, автоматика сеть/батарея, приложение) — карточка режима;
  • яркость подсветки клавишами — карточка подсветки;
  • видеокарта переключилась или не смогла — уведомление.
KDE сам рисует карточку режима только когда меняет его сам, поэтому её показываем мы.
Потом этот код войдёт в приложение в трее; пока это отдельная служба.
"""
import json
import logging
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from . import BUS_NAME, INTERFACE, OBJECT_PATH

log = logging.getLogger("asus-helper-agent")

PPD_NAMES = {"quiet": "power-saver", "balanced": "balanced", "performance": "performance"}
GPU_TEXT = {"off": "NVIDIA выключена (Eco)", "suspended": "NVIDIA включена", "active": "NVIDIA включена"}


class Agent:
    def __init__(self, system: Gio.DBusConnection, session: Gio.DBusConnection):
        self.system = system
        self.session = session
        self.profile = None
        self.notification_id = 0
        for signal, handler in (("StateChanged", self.on_state), ("KeyboardBrightnessChanged", self.on_brightness),
                                ("GpuSwitchFinished", self.on_gpu)):
            system.signal_subscribe(BUS_NAME, INTERFACE, signal, OBJECT_PATH, None,
                                    Gio.DBusSignalFlags.NONE, handler)
        # текущий режим — чтобы не показать карточку при запуске
        try:
            r = system.call_sync(BUS_NAME, OBJECT_PATH, "org.freedesktop.DBus.Properties", "Get",
                                 GLib.Variant("(ss)", (INTERFACE, "Profile")), None,
                                 Gio.DBusCallFlags.NO_AUTO_START, 2000, None)
            self.profile = r.unpack()[0]
        except GLib.Error:
            log.info("демон пока не запущен — жду его сигналов")

    def osd(self, method: str, sig: str, value) -> None:
        self.session.call("org.kde.plasmashell", "/org/kde/osdService", "org.kde.osdService", method,
                          GLib.Variant(f"({sig})", (value,)), None, Gio.DBusCallFlags.NO_AUTO_START,
                          -1, None, None, None)

    def notify(self, title: str, text: str, icon: str = "video-display") -> None:
        def done(conn, res):
            try:
                self.notification_id = conn.call_finish(res).unpack()[0]
            except GLib.Error as e:
                log.warning("уведомление: %s", e.message)
        # replaces_id — новое уведомление заменяет прошлое, а не копится
        self.session.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                          "org.freedesktop.Notifications", "Notify",
                          GLib.Variant("(susssasa{sv}i)", ("Asus-helper", self.notification_id, icon, title, text,
                                                           [], {}, 5000)),
                          None, Gio.DBusCallFlags.NONE, -1, None, done)

    # ---------- сигналы демона ----------
    def on_state(self, *args):
        state = json.loads(args[5].unpack()[0])
        profile = state.get("profile")
        if profile and profile != self.profile:
            if self.profile is not None:
                self.osd("powerProfileChanged", "s", PPD_NAMES.get(profile, "balanced"))
            self.profile = profile

    def on_brightness(self, *args):
        level, top = args[5].unpack()
        self.osd("keyboardBrightnessChanged", "i", round(level * 100 / (top or 1)))

    def on_gpu(self, *args):
        state, error = args[5].unpack()
        if error:
            self.notify("Видеокарта не переключилась", error, "dialog-warning")
        else:
            self.notify("Видеокарта", GPU_TEXT.get(state, f"NVIDIA: {state}"))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    Agent(Gio.bus_get_sync(Gio.BusType.SYSTEM), Gio.bus_get_sync(Gio.BusType.SESSION))
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
