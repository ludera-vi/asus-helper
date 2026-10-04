"""asus-helper-agent — помощник в сеансе пользователя (замена asus-osd).

Слушает демон на системной шине и показывает карточки KDE (в GNOME — через расширение Asus-helper):
  • смена режима (Fn+F5, автоматика сеть/батарея, приложение) — карточка режима;
  • яркость подсветки клавишами — карточка подсветки;
  • видеокарта переключилась или не смогла — уведомление;
  • зарядку отключили, а на NVIDIA работают программы — уведомление «закрыть или подождать».
KDE сам рисует карточку режима только когда меняет его сам, поэтому её показываем мы.
Потом этот код войдёт в приложение в трее; пока это отдельная служба.
"""
import json
import logging
import os
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from . import BUS_NAME, INTERFACE, OBJECT_PATH
from .i18n import _

log = logging.getLogger("asus-helper-agent")

PPD_NAMES = {"quiet": "power-saver", "balanced": "balanced", "performance": "performance"}
# GNOME: значки карточек из темы Adwaita и подписи режимов
GNOME_ICONS = {"quiet": "power-profile-power-saver-symbolic", "balanced": "power-profile-balanced-symbolic",
               "performance": "power-profile-performance-symbolic"}
PROFILE_NAMES = {"quiet": _("Тихий"), "balanced": _("Баланс"), "performance": _("Турбо")}
GNOME = "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
GPU_TEXT = {"off": _("NVIDIA выключена (Eco)"), "suspended": _("NVIDIA включена"), "active": _("NVIDIA включена")}


class Agent:
    def __init__(self, system: Gio.DBusConnection, session: Gio.DBusConnection):
        self.system = system
        self.session = session
        self.profile = None
        self.notification_id = 0
        self.ask_id = 0             # открытое уведомление «закрыть программы или подождать»
        for signal, handler in (("StateChanged", self.on_state), ("KeyboardBrightnessChanged", self.on_brightness),
                                ("GpuSwitchFinished", self.on_gpu), ("GpuAutoAsk", self.on_auto_ask)):
            system.signal_subscribe(BUS_NAME, INTERFACE, signal, OBJECT_PATH, None,
                                    Gio.DBusSignalFlags.NONE, handler)
        for signal, handler in (("ActionInvoked", self.on_action), ("NotificationClosed", self.on_closed)):
            session.signal_subscribe("org.freedesktop.Notifications", "org.freedesktop.Notifications", signal,
                                     "/org/freedesktop/Notifications", None, Gio.DBusSignalFlags.NONE, handler)
        # текущий режим — чтобы не показать карточку при запуске
        try:
            r = system.call_sync(BUS_NAME, OBJECT_PATH, "org.freedesktop.DBus.Properties", "Get",
                                 GLib.Variant("(ss)", (INTERFACE, "Profile")), None,
                                 Gio.DBusCallFlags.NO_AUTO_START, 2000, None)
            self.profile = r.unpack()[0]
        except GLib.Error:
            log.info(_("демон пока не запущен — жду его сигналов"))

    def gnome_osd(self, icon: str, label: str, level: float = -1) -> None:
        """Карточка GNOME через расширение Asus-helper (org.asushelper.Shell); нет расширения — молча ничего."""
        self.session.call("org.asushelper.Shell", "/org/asushelper/Shell", "org.asushelper.Shell", "ShowOSD",
                          GLib.Variant("(ssd)", (icon, label, level)), None, Gio.DBusCallFlags.NO_AUTO_START,
                          -1, None, None, None)

    def osd(self, method: str, sig: str, value) -> None:
        self.session.call("org.kde.plasmashell", "/org/kde/osdService", "org.kde.osdService", method,
                          GLib.Variant(f"({sig})", (value,)), None, Gio.DBusCallFlags.NO_AUTO_START,
                          -1, None, None, None)

    def notify(self, title: str, text: str, icon: str = "video-display") -> None:
        def done(conn, res):
            try:
                self.notification_id = conn.call_finish(res).unpack()[0]
            except GLib.Error as e:
                log.warning(_("уведомление: %s"), e.message)
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
                if GNOME:
                    self.gnome_osd(GNOME_ICONS.get(profile, GNOME_ICONS["balanced"]), PROFILE_NAMES.get(profile, profile))
                else:
                    self.osd("powerProfileChanged", "s", PPD_NAMES.get(profile, "balanced"))
            self.profile = profile
        # вопрос больше не актуален (подключили зарядку, программы закрыли, выбрали режим вручную)
        if self.ask_id and not (state.get("gpu") or {}).get("auto_waiting"):
            self.close_ask()

    def on_brightness(self, *args):
        level, top = args[5].unpack()
        if GNOME:
            self.gnome_osd("keyboard-brightness-symbolic", _("Подсветка клавиатуры"), level / (top or 1))
        else:
            self.osd("keyboardBrightnessChanged", "i", round(level * 100 / (top or 1)))

    def on_gpu(self, *args):
        state, error = args[5].unpack()
        if error:
            self.notify(_("Видеокарта не переключилась"), error, "dialog-warning")
        else:
            self.notify(_("Видеокарта"), GPU_TEXT.get(state, f"NVIDIA: {state}"))


    # ---------- «Авто»: закрыть программы на NVIDIA или подождать ----------
    def on_auto_ask(self, *args):
        programs, manual = args[5].unpack()
        if not programs:
            return
        first = programs[0]
        more = len(programs) - 1
        who = first if not more else _("{0} и ещё {1}").format(first, more)
        text = (_("Чтобы выключить NVIDIA (Eco), нужно закрыть: {0}. Закрыть и выключить сейчас или подождать, "
                  "пока вы закроете сами?") if manual else
                _("Зарядка отключена, а NVIDIA занята: {0}. Закрыть и выключить видеокарту, чтобы батарея "
                  "прожила дольше, или подождать, пока вы закроете сами?")).format(who)
        actions = ["close", _("Закрыть и выключить"), "wait", _("Подождать")]

        def done(conn, res):
            try:
                self.ask_id = conn.call_finish(res).unpack()[0]
            except GLib.Error as e:
                log.warning(_("уведомление: %s"), e.message)
        self.session.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                          "org.freedesktop.Notifications", "Notify",
                          GLib.Variant("(susssasa{sv}i)", ("Asus-helper", self.ask_id, "video-display",
                                                           _("NVIDIA занята"), text, actions,
                                                           {"desktop-entry": GLib.Variant("s", "asus-helper"),
                                                            "urgency": GLib.Variant("y", 1)}, 0)),
                          None, Gio.DBusCallFlags.NONE, -1, None, done)

    def on_action(self, *args):
        nid, action = args[5].unpack()
        if nid != self.ask_id or action not in ("close", "wait"):
            return
        self.ask_id = 0
        self.system.call(BUS_NAME, OBJECT_PATH, INTERFACE, "SetGpuAutoAnswer", GLib.Variant("(s)", (action,)),
                         None, Gio.DBusCallFlags.NONE, -1, None, None)

    def on_closed(self, *args):
        if args[5].unpack()[0] == self.ask_id:
            self.ask_id = 0         # закрыли крестиком — значит, подождать (это и так по умолчанию)

    def close_ask(self):
        nid, self.ask_id = self.ask_id, 0
        self.session.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                          "org.freedesktop.Notifications", "CloseNotification", GLib.Variant("(u)", (nid,)),
                          None, Gio.DBusCallFlags.NONE, -1, None, None)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    Agent(Gio.bus_get_sync(Gio.BusType.SYSTEM), Gio.bus_get_sync(Gio.BusType.SESSION))
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
