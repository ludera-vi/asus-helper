"""asus-helper-cli — управление демоном из терминала.

  asus-helper-cli                         состояние
  asus-helper-cli profile [quiet|balanced|performance|next]
  asus-helper-cli auto on|off             режим по источнику питания
  asus-helper-cli charge 80               лимит заряда батареи, %
  asus-helper-cli epp PROFILE VALUE|default
  asus-helper-cli fan [PROFILE]           кривые вентиляторов
  asus-helper-cli fan set PROFILE cpu|gpu 30:0,50:10,…   8 точек «°C:%»
  asus-helper-cli fan reset PROFILE cpu|gpu              вернуть кривую BIOS
  asus-helper-cli fan factory             заводские кривые текущего режима
  asus-helper-cli power                   лимиты мощности
  asus-helper-cli power set PROFILE ATTR VALUE|default
  asus-helper-cli power reset PROFILE
  asus-helper-cli gpu                    состояние видеокарты
  asus-helper-cli gpu eco|standard [--force] [--display]   выключить / включить NVIDIA
                                       --force закроет программы на ней, --display — даже с монитором на NVIDIA
  asus-helper-cli gpu auto on|off        «Авто»: Eco без зарядки, NVIDIA от сети
  asus-helper-cli kbd [0-3]              яркость подсветки клавиатуры
  asus-helper-cli aura static|breathe|cycle|strobe [#RRGGBB] [#RRGGBB] [slow|normal|fast]
  asus-helper-cli aura power awake,boot,sleep,shutdown   когда светиться (перечислить нужное)
  asus-helper-cli slash [0-3] [АНИМАЦИЯ] [пауза 0-5]   полоса на крышке (0 — выключить)
  asus-helper-cli slash options battery,lid            когда светиться: на батарее, с закрытой крышкой
  asus-helper-cli boost PROFILE on|off                 Turbo Boost процессора в режиме
  asus-helper-cli diag                 что Asus-helper нашёл у ноутбука (без демона, для отчёта об ошибке)
  asus-helper-cli import-asusd            перенести настройки из /etc/asusd (root, демон остановлен)
"""
import json
import re
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from . import BUS_NAME, INTERFACE, OBJECT_PATH, PROFILES

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
                msg = "демон asus-helperd не запущен (systemctl status asus-helperd)"
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
    boost = "" if s.get("cpu_boost") is None else f", Turbo Boost {'вкл' if s['cpu_boost'] else 'выкл'}"
    print(f"Ноутбук    : {s['model']['name']}")
    print(f"Режим      : {NAMES.get(s['profile'], s['profile'])}   (EPP {s['epp']}{boost})")
    print(f"Питание    : {'сеть' if s['ac'] else 'батарея'}   "
          f"авто: {'да' if s['auto_profile'] else 'нет'}  "
          f"(сеть → {NAMES[s['profile_on_ac']]}, батарея → {NAMES[s['profile_on_battery']]})")
    if b:
        wear = f"  износ {100 - b['health']}%" if b.get("health") else ""
        print(f"Батарея    : {b['capacity']}%  {b['status']}  {b['power_w']} Вт  лимит {b['charge_limit']}%{wear}")
    fans = s["fans"]
    print("Вентиляторы: " + ", ".join(f"{f.upper()} {v} об/мин" for f, v in fans.items()) + f"   CPU {s['cpu_temp']} °C")
    g = s.get("gpu") or {}
    if g.get("supported"):
        users = f"   используют: {', '.join(g['holders'])}" if g.get("holders") else ""
        print(f"Видеокарта : {GPU_NAMES.get(g['state'], g['state'])}"
              f"{'  (переключается…)' if g['switching'] else ''}"
              f"   авто: {'да' if g['auto_eco'] else 'нет'}{users}")
        if g.get("error"):
            print(f"             последняя ошибка: {g['error']}")
    k = s.get("keyboard") or {}
    if k:
        print(f"Подсветка  : яркость {k.get('brightness')}/{k.get('max', 3)}   {k['mode']} {k['color']}"
              f"{' ' + k['color2'] if k['mode'] == 'breathe' else ''} {k['speed']}")
    if s.get("fan_curves"):
        for f, c in s["fan_curves"].items():
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
        raise Error("asus-helper-cli auto on|off")
    cl.call("SetAutoProfile", "b", args[0] == "on")


def cmd_charge(cl, args):
    if not args or not args[0].isdigit():
        raise Error("asus-helper-cli charge 20…100")
    cl.call("SetChargeLimit", "u", int(args[0]))


def cmd_epp(cl, args):
    if len(args) != 2:
        raise Error("asus-helper-cli epp PROFILE VALUE|default")
    cl.call("SetEpp", "ss", args[0], "" if args[1] == "default" else args[1])


def cmd_fan(cl, args):
    if not args or args[0] in PROFILES:
        cfg = json.loads(cl.call("GetConfig"))
        present = list(cl.state().get("fan_curves") or {})
        for p in [args[0]] if args else PROFILES:
            print(f"{NAMES[p]}:")
            for f in present:
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
        for f, c in r["curves"].items():
            print(f"  {f.upper()}: {fmt_curve(c)}")
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
    print("Если демон запущен: sudo systemctl reload asus-helperd")


GPU_NAMES = {"off": "выключена (Eco)", "suspended": "включена, спит", "active": "включена, работает",
             "missing": "включена, но драйвер не загружен"}


def cmd_gpu(cl, args):
    if not args:
        g = cl.state()["gpu"]
        print(GPU_NAMES.get(g["state"], g["state"]))
        if g.get("holders"):
            print("Используют: " + ", ".join(g["holders"]))
    elif args[0] in ("eco", "standard"):
        cl.call("SetGpuModeFlags", "su", args[0], (1 if "--force" in args else 0) | (2 if "--display" in args else 0))
        print("Переключаю… (это занимает несколько секунд)")
        # ждём окончания — демон сообщает сигналом, проще опросить состояние
        import time
        for _ in range(60):
            time.sleep(0.5)
            g = cl.state()["gpu"]
            if not g["switching"]:
                if g["error"]:
                    hint = ("\nЗакрыть их и выключить: asus-helper-cli gpu eco --force"
                            if g.get("can_force") and "--force" not in args else
                            "\nВыключить всё равно: asus-helper-cli gpu eco --display" if "монитор" in g["error"] else "")
                    raise Error(g["error"] + hint)
                print(GPU_NAMES.get(g["state"], g["state"]))
                return
        raise Error("переключение не закончилось за 30 с — смотри журнал демона")
    elif args[0] == "auto" and len(args) == 2 and args[1] in ("on", "off"):
        cl.call("SetGpuAutoEco", "b", args[1] == "on")
    else:
        raise Error(__doc__)


def cmd_kbd(cl, args):
    if not args:
        k = cl.state()["keyboard"]
        print(f"{k.get('brightness')}/{k.get('max', 3)}")
    elif args[0].isdigit():
        cl.call("SetKeyboardBrightness", "u", int(args[0]))
    else:
        raise Error("asus-helper-cli kbd 0…3")


def cmd_aura(cl, args):
    k = cl.state()["keyboard"]
    if not args:
        print(f"{k['mode']} {k['color']} {k['color2']} {k['speed']}")
        print("светится: " + ", ".join(x for x in ("awake", "boot", "sleep", "shutdown") if k[x]))
    elif args[0] == "power":
        on = set(args[1].split(",")) if len(args) > 1 else set()
        cl.call("SetAuraPower", "bbbb", "awake" in on, "boot" in on, "sleep" in on, "shutdown" in on)
    else:
        colors = [a for a in args[1:] if a.startswith("#")]
        speeds = [a for a in args[1:] if a in ("slow", "normal", "fast")]
        cl.call("SetAura", "ssss", args[0], colors[0] if colors else k["color"],
                colors[1] if len(colors) > 1 else k["color2"], speeds[0] if speeds else k["speed"])


def cmd_slash(cl, args):
    sl = cl.state().get("slash") or {}
    if not sl.get("supported"):
        raise Error("полоса Slash не найдена")
    names = {m["id"]: m["name"] for m in sl["modes"]}
    if not args:
        print(f"яркость {sl['brightness']}/3, {names.get(sl['mode'], sl['mode'])}, пауза {sl['interval']} с, "
              f"на батарее: {'да' if sl['on_battery'] else 'нет'}, с закрытой крышкой: {'да' if sl['lid_closed'] else 'нет'}")
        print("анимации: " + ", ".join(names))
    elif args[0] == "options":
        on = set(args[1].split(",")) if len(args) > 1 else set()
        cl.call("SetSlashOptions", "bb", "battery" in on, "lid" in on)
    else:
        level = int(args[0]) if args[0].isdigit() else sl["brightness"] or 2
        mode = next((a for a in args if a in names), sl["mode"])
        nums = [int(a) for a in args[1:] if a.isdigit()]
        cl.call("SetSlash", "suu", mode, level, nums[0] if nums else sl["interval"])


def cmd_boost(cl, args):
    if len(args) != 2 or args[1] not in ("on", "off"):
        raise Error("asus-helper-cli boost PROFILE on|off")
    cl.call("SetCpuBoost", "sb", args[0], args[1] == "on")


def cmd_diag(_cl, _args):
    """Отчёт о возможностях ноутбука — читает железо напрямую, root и демон не нужны."""
    import os
    import platform
    from .daemon import aura, gpu, hardware as hw, hid, slash
    m = hw.model()
    yes = lambda v: "есть" if v else "нет"
    print(f"Ноутбук        : {m['name']}  ({m['product']}, {m['vendor']})")
    print(f"Ядро           : {platform.release()}   asus-armoury: {yes(os.path.isdir(hw.ARMOURY))}")
    print(f"Режимы         : {' '.join(hw.profile_choices()) or 'нет'}  (сейчас {hw.profile()})")
    print(f"Процессор      : {hw.cpu_driver()}, EPP: {' '.join(hw.epp_choices()) or 'нет'}, "
          f"Turbo Boost: {'нет' if hw.turbo() is None else 'есть'}, температура: {hw.cpu_temp()} °C")
    print(f"Вентиляторы    : {', '.join(f'{f} {v} об/мин' for f, v in hw.fan_rpm().items()) or 'нет'}")
    print(f"Свои кривые    : {', '.join(hw.curve_fans()) or 'нет'}")
    lim = hw.power_limits()
    print(f"Лимиты мощности: " + (", ".join(f"{a} {v['min']}–{v['max']}" for a, v in lim.items()) or "нет"))
    print(f"Переключатели  : " + (", ".join(a for a in hw.TOGGLE_ATTRS if hw.armoury_attr(a)) or "нет"))
    print(f"Видеокарта     : {'Eco поддерживается' if gpu.supported() else 'нет NVIDIA / нет dgpu_disable'}"
          f"{'' if gpu.mux_hybrid() else ', MUX: только NVIDIA'}")
    b = aura.brightness()
    print(f"Подсветка клав.: яркость {'0–' + str(b['max']) if b else 'нет'}, цвет: {aura.rgb_method() or 'нет'}")
    sl = slash.find_device()
    print(f"Slash          : {f'{sl[0]}, отчёт {sl[1]:#x}, {slash.segments()} сегм.' if sl else 'нет'}")
    bat = hw.battery()
    print("Батарея        : " + (f"здоровье {bat['health']}%, лимит заряда {bat['charge_limit']}%" if bat else "нет"))
    print("HID ASUS       : " + ("; ".join(f"{d['dev']} {d['product']:04x} отчёты " + ",".join(f"{k:#x}" for k in d["features"])
                                         for d in hid.devices()) or "нет"))


COMMANDS = {"diag": cmd_diag, "slash": cmd_slash, "boost": cmd_boost, "gpu": cmd_gpu, "kbd": cmd_kbd, "aura": cmd_aura, "status": cmd_status, "profile": cmd_profile, "auto": cmd_auto, "charge": cmd_charge,
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
        cmd(None if cmd in (cmd_import, cmd_diag) else Client(session), argv[1:])
    except Error as e:
        print(f"ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
