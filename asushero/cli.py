"""asushero-cli — управление демоном из терминала.

  asushero-cli                         состояние
  asushero-cli profile [quiet|balanced|performance|next]
  asushero-cli auto on|off             режим по источнику питания
  asushero-cli charge 80               лимит заряда батареи, %
  asushero-cli epp PROFILE VALUE|default
  asushero-cli fan [PROFILE]           кривые вентиляторов
  asushero-cli fan set PROFILE cpu|gpu 30:0,50:10,…   8 точек «°C:%»
  asushero-cli fan reset PROFILE cpu|gpu              вернуть кривую BIOS
  asushero-cli fan factory             заводские кривые текущего режима
  asushero-cli power                   лимиты мощности
  asushero-cli power set PROFILE ATTR VALUE|default
  asushero-cli power reset PROFILE
  asushero-cli import-asusd            перенести настройки из /etc/asusd (root, демон остановлен)
"""
import json
import re
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from . import BUS_NAME, FANS, INTERFACE, OBJECT_PATH, PROFILES

NAMES = {"quiet": "Тихий", "balanced": "Баланс", "performance": "Турбо"}
POWER_NAMES = {
    "ppt_pl1_spl": "CPU PL1 (долговременный), Вт",
    "ppt_pl2_sppt": "CPU PL2 (кратковременный), Вт",
    "ppt_fppt": "CPU fPPT, Вт",
    "nv_dynamic_boost": "NVIDIA Dynamic Boost, Вт",
    "nv_temp_target": "NVIDIA предел температуры, °C",
    "nv_tgp": "NVIDIA TGP, Вт",
}


class Error(Exception):
    pass


class Client:
    def __init__(self, session: bool = False):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION if session else Gio.BusType.SYSTEM)

    def call(self, method: str, sig: str | None = None, *args):
        try:
            r = self.bus.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, method,
                                   GLib.Variant(f"({sig})", args) if sig else None,
                                   None, Gio.DBusCallFlags.NONE, 30000, None)
        except GLib.Error as e:
            msg = re.sub(r"^GDBus\.Error:[\w.]+:\s*", "", e.message)
            if "ServiceUnknown" in e.message or "was not provided" in e.message:
                msg = "демон asusherod не запущен (systemctl status asusherod)"
            raise Error(msg) from None
        v = r.unpack()
        return v[0] if v else None

    def state(self) -> dict:
        return json.loads(self.call("GetState"))


def pct(pwm: int) -> int:
    return round(pwm * 100 / 255)


def fmt_curve(c: dict | None) -> str:
    if not c:
        return "BIOS"
    return "  ".join(f"{t}°:{pct(p)}%" for t, p in zip(c["temp"], c["pwm"]))


def cmd_status(cl: Client, _args):
    s = cl.state()
    b = s.get("battery") or {}
    print(f"Режим      : {NAMES.get(s['profile'], s['profile'])}   (EPP {s['epp']})")
    print(f"Питание    : {'сеть' if s['ac'] else 'батарея'}   "
          f"авто: {'да' if s['auto_profile'] else 'нет'}  "
          f"(сеть → {NAMES[s['profile_on_ac']]}, батарея → {NAMES[s['profile_on_battery']]})")
    if b:
        wear = f"  износ {100 - b['health']}%" if b.get("health") else ""
        print(f"Батарея    : {b['capacity']}%  {b['status']}  {b['power_w']} Вт  лимит {b['charge_limit']}%{wear}")
    fans = s["fans"]
    print(f"Вентиляторы: CPU {fans['cpu']} об/мин, GPU {fans['gpu']} об/мин   CPU {s['cpu_temp']} °C")
    if s.get("fan_curves"):
        for f in FANS:
            c = s["fan_curves"][f]
            print(f"  {f.upper()}: {'своя' if c['enabled'] else 'BIOS'}  {fmt_curve(c) if c['enabled'] else ''}")


def cmd_profile(cl, args):
    if not args:
        print(cl.state()["profile"])
    elif args[0] == "next":
        print(NAMES[cl.call("CycleProfile")])
    else:
        cl.call("SetProfile", "s", args[0])


def cmd_auto(cl, args):
    if not args or args[0] not in ("on", "off"):
        raise Error("asushero-cli auto on|off")
    cl.call("SetAutoProfile", "b", args[0] == "on")


def cmd_charge(cl, args):
    if not args or not args[0].isdigit():
        raise Error("asushero-cli charge 20…100")
    cl.call("SetChargeLimit", "u", int(args[0]))


def cmd_epp(cl, args):
    if len(args) != 2:
        raise Error("asushero-cli epp PROFILE VALUE|default")
    cl.call("SetEpp", "ss", args[0], "" if args[1] == "default" else args[1])


def cmd_fan(cl, args):
    if not args or args[0] in PROFILES:
        cfg = json.loads(cl.call("GetConfig"))
        for p in [args[0]] if args else PROFILES:
            print(f"{NAMES[p]}:")
            for f in FANS:
                print(f"  {f.upper()}: {fmt_curve(cfg['profiles'][p]['fan_curves'][f])}")
    elif args[0] == "set" and len(args) == 4:
        temp, pwm = [], []
        for point in args[3].split(","):
            t, p = point.split(":")
            temp.append(int(t))
            pwm.append(round(int(p.rstrip("%")) * 255 / 100))
        cl.call("SetFanCurve", "ssaiai", args[1], args[2], temp, pwm)
    elif args[0] == "reset" and len(args) == 3:
        cl.call("ResetFanCurve", "ss", args[1], args[2])
    elif args[0] == "factory":
        r = json.loads(cl.call("GetFactoryFanCurves"))
        print(f"Заводские кривые режима {NAMES[r['profile']]}:")
        for f in FANS:
            print(f"  {f.upper()}: {fmt_curve(r['curves'][f])}")
    else:
        raise Error(__doc__)


def cmd_power(cl, args):
    if not args:
        s = cl.state()
        cfg = json.loads(cl.call("GetConfig"))["profiles"][s["profile"]]["power_limits"]
        print(f"Режим {NAMES[s['profile']]}, {'сеть' if s['ac'] else 'батарея'}:")
        for attr, a in s["power_limits"].items():
            mine = f"  (задано: {cfg[attr]})" if attr in cfg else ""
            print(f"  {POWER_NAMES.get(attr, attr):34} {a['value']:>4}   допустимо {a['min']}–{a['max']}{mine}")
    elif args[0] == "set" and len(args) == 4:
        cl.call("SetPowerLimit", "ssi", args[1], args[2], -1 if args[3] == "default" else int(args[3]))
    elif args[0] == "reset" and len(args) == 2:
        cl.call("ResetPowerLimits", "s", args[1])
    else:
        raise Error(__doc__)


def cmd_import(_cl, _args):
    from .asusd_import import import_into
    from .daemon.config import Config
    cfg = Config().load()
    done = import_into(cfg)
    if not done:
        raise Error("в /etc/asusd нечего переносить")
    cfg.save()
    print("Перенесено в", cfg.path)
    for line in done:
        print("  " + line)
    print("Если демон запущен: sudo systemctl reload asusherod")


COMMANDS = {"status": cmd_status, "profile": cmd_profile, "auto": cmd_auto, "charge": cmd_charge,
            "epp": cmd_epp, "fan": cmd_fan, "power": cmd_power, "import-asusd": cmd_import}


def main() -> int:
    argv = sys.argv[1:]
    session = "--session" in argv
    argv = [a for a in argv if a != "--session"]
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = COMMANDS.get(argv[0] if argv else "status")
    if cmd is None:
        print(__doc__)
        return 2
    try:
        cmd(None if cmd is cmd_import else Client(session), argv[1:])
    except Error as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
