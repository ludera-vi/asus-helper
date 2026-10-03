"""asus-helperd — системный демон asushelper. Запуск: python -m asushelper.daemon [--session-bus]

--session-bus — для разработки: работать на сессионной шине без root, вместе с
ASUSHELPER_SYSROOT (поддельный sysfs) и ASUSHELPER_CONFIG_DIR.
"""
import argparse
import os
import logging
import signal
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

try:
    gi.require_version("GLibUnix", "2.0")
    from gi.repository import GLibUnix
    signal_add = GLibUnix.signal_add
except (ValueError, ImportError):   # старый GLib
    signal_add = GLib.unix_signal_add

from .. import BUS_NAME, __version__
from . import gpu
from . import hardware as hw
from .config import Config
from .ppd import PowerProfiles
from . import service as service_mod
from .service import Service
from ..i18n import _

log = logging.getLogger("asus-helperd")

ASUSD = "xyz.ljones.Asusd"


def name_has_owner(bus, name) -> bool:
    try:
        return bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                             "NameHasOwner", GLib.Variant("(s)", (name,)), None,
                             Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
    except GLib.Error:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(prog="asus-helperd")
    ap.add_argument("--session-bus", action="store_true", help=_("сессионная шина (разработка)"))
    ap.add_argument("--no-ppd", action="store_true", help=_("не выдавать себя за power-profiles-daemon"))
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    # systemd добавляет время сам — в журнал только уровень и текст
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    log.info("asus-helperd %s", __version__)

    bus = Gio.bus_get_sync(Gio.BusType.SESSION if args.session_bus else Gio.BusType.SYSTEM)
    if not args.session_bus and name_has_owner(bus, ASUSD):
        log.error(_("работает asusd — два демона будут спорить за вентиляторы и режимы. "
                  "Остановите его: sudo systemctl stop asusd"))
        return 1

    service_mod.USE_POLKIT = not args.session_bus
    config = Config().load()
    service = Service(bus, config)
    ppd = None if args.no_ppd else PowerProfiles(bus, service)

    hw.set_charge_limit(config.data["charge_limit"])
    service.startup()

    # ---------- сеть ↔ батарея (UPower сообщает об изменении) ----------
    def on_upower(*_):
        service.power_source_changed(hw.on_ac())
    bus.signal_subscribe("org.freedesktop.UPower", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                         "/org/freedesktop/UPower", None, Gio.DBusSignalFlags.NONE, on_upower)
    # подстраховка, если UPower не прислал сигнал
    GLib.timeout_add_seconds(10, lambda: on_upower() or True)

    # ---------- выход из сна: BIOS забывает кривые и лимит заряда ----------
    # Блокировка сна «с задержкой»: logind ждёт, пока мы её отпустим (не дольше InhibitDelayMaxSec).
    # Перед сном убираем с шины выключенную NVIDIA — иначе выход из сна ждёт её 65 с.
    inhibitor = []

    def take_inhibitor():
        if args.session_bus or inhibitor:
            return
        try:
            r, fds = bus.call_with_unix_fd_list_sync(
                "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Inhibit",
                GLib.Variant("(ssss)", ("sleep", "Asus-helper", _("подготовка видеокарты ко сну"), "delay")),
                GLib.VariantType("(h)"), Gio.DBusCallFlags.NONE, -1, None, None)
            inhibitor.append(fds.get(r.unpack()[0]))
        except GLib.Error as e:
            log.warning(_("logind не дал блокировку сна: %s"), e.message)

    def on_sleep(_c, _s, _p, _i, _sig, params):
        going_to_sleep = params.unpack()[0]
        if going_to_sleep:
            service.before_sleep()
            if gpu.supported() and not service.gpu.busy:
                gpu.fixup()
            while inhibitor:
                os.close(inhibitor.pop())
        else:
            hw.set_charge_limit(config.data["charge_limit"])
            service.resumed()
            take_inhibitor()
    take_inhibitor()
    bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
                         "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, on_sleep)

    loop = GLib.MainLoop()

    def on_name_acquired(_c, name):
        log.info(_("готов: %s"), name)
        if ppd:
            ppd.own_names()

    def on_name_lost(_c, name):
        log.error(_("не удалось занять имя %s на шине (уже запущен другой asus-helperd?)"), name)
        loop.quit()

    Gio.bus_own_name_on_connection(bus, BUS_NAME, Gio.BusNameOwnerFlags.NONE, on_name_acquired, on_name_lost)

    def reload():
        config.load()
        log.info(_("настройки перечитаны"))
        hw.set_charge_limit(config.data["charge_limit"])
        service.apply_keyboard()
        service.modes.reapply(_("перечитаны настройки"))
        return GLib.SOURCE_CONTINUE

    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, reload)
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: loop.quit() or GLib.SOURCE_REMOVE)
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: loop.quit() or GLib.SOURCE_REMOVE)
    loop.run()
    log.info(_("остановлен"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
