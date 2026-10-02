"""asusherod — системный демон asushero. Запуск: python -m asushero.daemon [--session-bus]

--session-bus — для разработки: работать на сессионной шине без root, вместе с
ASUSHERO_SYSROOT (поддельный sysfs) и ASUSHERO_CONFIG_DIR.
"""
import argparse
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
from . import hardware as hw
from .config import Config
from .ppd import PowerProfiles
from . import service as service_mod
from .service import Service

log = logging.getLogger("asusherod")

ASUSD = "xyz.ljones.Asusd"


def name_has_owner(bus, name) -> bool:
    try:
        return bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                             "NameHasOwner", GLib.Variant("(s)", (name,)), None,
                             Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
    except GLib.Error:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(prog="asusherod")
    ap.add_argument("--session-bus", action="store_true", help="сессионная шина (разработка)")
    ap.add_argument("--no-ppd", action="store_true", help="не выдавать себя за power-profiles-daemon")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    # systemd добавляет время сам — в журнал только уровень и текст
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    log.info("asusherod %s", __version__)

    bus = Gio.bus_get_sync(Gio.BusType.SESSION if args.session_bus else Gio.BusType.SYSTEM)
    if not args.session_bus and name_has_owner(bus, ASUSD):
        log.error("работает asusd — два демона будут спорить за вентиляторы и режимы. "
                  "Остановите его: sudo systemctl stop asusd")
        return 1

    service_mod.USE_POLKIT = not args.session_bus
    config = Config().load()
    service = Service(bus, config)
    ppd = None if args.no_ppd else PowerProfiles(bus, service)

    hw.set_charge_limit(config.data["charge_limit"])
    service.modes.startup()

    # ---------- сеть ↔ батарея (UPower сообщает об изменении) ----------
    def on_upower(*_):
        service.modes.power_source_changed(hw.on_ac())
    bus.signal_subscribe("org.freedesktop.UPower", "org.freedesktop.DBus.Properties", "PropertiesChanged",
                         "/org/freedesktop/UPower", None, Gio.DBusSignalFlags.NONE, on_upower)
    # подстраховка, если UPower не прислал сигнал
    GLib.timeout_add_seconds(10, lambda: on_upower() or True)

    # ---------- выход из сна: BIOS забывает кривые и лимит заряда ----------
    def on_sleep(_c, _s, _p, _i, _sig, params):
        going_to_sleep = params.unpack()[0]
        if not going_to_sleep:
            hw.set_charge_limit(config.data["charge_limit"])
            service.modes.ac = hw.on_ac()
            service.modes.reapply("выход из сна")
    bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
                         "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, on_sleep)

    loop = GLib.MainLoop()

    def on_name_acquired(_c, name):
        log.info("готов: %s", name)
        if ppd:
            ppd.own_names()

    def on_name_lost(_c, name):
        log.error("не удалось занять имя %s на шине (уже запущен другой asusherod?)", name)
        loop.quit()

    Gio.bus_own_name_on_connection(bus, BUS_NAME, Gio.BusNameOwnerFlags.NONE, on_name_acquired, on_name_lost)

    def reload():
        config.load()
        log.info("настройки перечитаны")
        hw.set_charge_limit(config.data["charge_limit"])
        service.modes.reapply("перечитаны настройки")
        return GLib.SOURCE_CONTINUE

    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, reload)
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: loop.quit() or GLib.SOURCE_REMOVE)
    signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: loop.quit() or GLib.SOURCE_REMOVE)
    loop.run()
    log.info("остановлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
