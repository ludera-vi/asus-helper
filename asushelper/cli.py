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
  asus-helper-cli kbd timeout СЕТЬ БАТАРЕЯ   гаснуть без нажатий через N секунд (0 — не гаснуть)
  asus-helper-cli aura static|breathe|cycle|strobe [#RRGGBB] [#RRGGBB] [slow|normal|fast]
  asus-helper-cli aura power awake,boot,sleep,shutdown   когда светиться (перечислить нужное)
  asus-helper-cli slash [0-3] [АНИМАЦИЯ] [пауза 0-5]   полоса на крышке (0 — выключить)
  asus-helper-cli slash options battery,lid            когда светиться: на батарее, с закрытой крышкой
  asus-helper-cli boost PROFILE on|off                 Turbo Boost процессора в режиме
  asus-helper-cli language ru|en        язык программы (демон и окно перезапустятся)
  asus-helper-cli diag                 что Asus-helper нашёл у ноутбука (без демона, для отчёта об ошибке)
  asus-helper-cli restore              вернуть заводские лимиты, кривые вентиляторов BIOS, Turbo Boost
  asus-helper-cli import-asusd            перенести настройки из /etc/asusd (root, демон остановлен)
"""
import json
import re
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from . import BUS_NAME, INTERFACE, OBJECT_PATH, PROFILES
from .i18n import _

NAMES = {"quiet": _("Тихий"), "balanced": _("Баланс"), "performance": _("Турбо")}
POWER_NAMES = {
    "ppt_pl1_spl": _("CPU PL1 (долговременный), Вт"),
    "ppt_pl2_sppt": _("CPU PL2 (кратковременный), Вт"),
    "ppt_fppt": _("CPU fPPT, Вт"),
    "nv_dynamic_boost": _("NVIDIA Dynamic Boost, Вт"),
    "nv_temp_target": _("NVIDIA предел температуры, °C"),
    "nv_tgp": _("NVIDIA TGP, Вт"),
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
                msg = _("демон asus-helperd не запущен (systemctl status asus-helperd)")
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
    boost = "" if s.get("cpu_boost") is None else f", Turbo Boost {_('вкл') if s['cpu_boost'] else _('выкл')}"
    print(_("Ноутбук    : {0}").format(s['model']['name']))
    print(_("Режим      : {0}   (EPP {1}{2})").format(NAMES.get(s['profile'], s['profile']), s['epp'], boost))
    print(_("Питание    : {0}   авто: {1}  (сеть → {2}, батарея → {3})").format(_('сеть') if s['ac'] else _('батарея'), _('да') if s['auto_profile'] else _('нет'), NAMES[s['profile_on_ac']], NAMES[s['profile_on_battery']]))
    if b:
        wear = _("  износ {0}%").format(100 - b['health']) if b.get("health") else ""
        print(_("Батарея    : {0}%  {1}  {2} Вт  лимит {3}%{4}").format(b['capacity'], b['status'], b['power_w'], b['charge_limit'], wear))
    fans = s["fans"]
    print(_("Вентиляторы: ") + ", ".join(_("{0} {1} об/мин").format(f.upper(), v) for f, v in fans.items()) + f"   CPU {s['cpu_temp']} °C")
    g = s.get("gpu") or {}
    if g.get("supported"):
        users = _("   используют: {0}").format(', '.join(g['holders'])) if g.get("holders") else ""
        print(_("Видеокарта : {0}{1}   авто: {2}{3}").format(GPU_NAMES.get(g['state'], g['state']), _('  (переключается…)') if g['switching'] else '', _('да') if g['auto_eco'] else _('нет'), users))
        if g.get("auto_waiting"):
            print(_("             авто ждёт, пока NVIDIA отпустят: {0}").format(', '.join(g['auto_waiting'])))
        if g.get("error"):
            print(_("             последняя ошибка: {0}").format(g['error']))
    k = s.get("keyboard") or {}
    if k:
        print(_("Подсветка  : яркость {0}/{1}   {2} {3}{4} {5}").format(k.get('brightness'), k.get('max', 3), k['mode'], k['color'], ' ' + k['color2'] if k['mode'] == 'breathe' else '', k['speed']))
    if s.get("fan_curves"):
        for f, c in s["fan_curves"].items():
            print(f"  {f.upper()}: {_('своя') if c['enabled'] else 'BIOS'}  {fmt_curve(c) if c['enabled'] else ''}")


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
        print(_("Заводские кривые режима {0}:").format(NAMES[r['profile']]))
        for f, c in r["curves"].items():
            print(f"  {f.upper()}: {fmt_curve(c)}")
    else:
        raise Error(_(__doc__))


def cmd_power(cl, args):
    if not args:
        s = cl.state()
        cfg = json.loads(cl.call("GetConfig"))["profiles"][s["profile"]]["power_limits"]
        print(_("Режим {0}, {1}:").format(NAMES[s['profile']], _('сеть') if s['ac'] else _('батарея')))
        for attr, a in s["power_limits"].items():
            mine = _("  (задано: {0})").format(cfg[attr]) if attr in cfg else ""
            print(_("  {0:34} {1:>4}   допустимо {2}–{3}{4}").format(POWER_NAMES.get(attr, attr), a['value'], a['min'], a['max'], mine))
    elif args[0] == "set" and len(args) == 4:
        cl.call("SetPowerLimit", "ssi", args[1], args[2], -1 if args[3] == "default" else int(args[3]))
    elif args[0] == "reset" and len(args) == 2:
        cl.call("ResetPowerLimits", "s", args[1])
    else:
        raise Error(_(__doc__))


def cmd_import(_cl, _args):
    from .asusd_import import import_into
    from .daemon.config import Config
    cfg = Config().load()
    done = import_into(cfg)
    if not done:
        raise Error(_("в /etc/asusd нечего переносить"))
    cfg.save()
    print(_("Перенесено в"), cfg.path)
    for line in done:
        print("  " + line)
    print(_("Если демон запущен: sudo systemctl reload asus-helperd"))


GPU_NAMES = {"off": _("выключена (Eco)"), "suspended": _("включена, спит"), "active": _("включена, работает"),
             "missing": _("включена, но драйвер не загружен")}


def cmd_gpu(cl, args):
    if not args:
        g = cl.state()["gpu"]
        print(GPU_NAMES.get(g["state"], g["state"]))
        if g.get("holders"):
            print(_("Используют: ") + ", ".join(g["holders"]))
    elif args[0] in ("eco", "standard"):
        cl.call("SetGpuModeFlags", "su", args[0], (1 if "--force" in args else 0) | (2 if "--display" in args else 0))
        print(_("Переключаю… (это занимает несколько секунд)"))
        # ждём окончания — демон сообщает сигналом, проще опросить состояние
        import time
        for _attempt in range(240):        # с паузой между переключениями — до двух минут
            time.sleep(0.5)
            g = cl.state()["gpu"]
            if not g["switching"]:
                if g["error"]:
                    hint = (_("\nЗакрыть их и выключить: asus-helper-cli gpu eco --force")
                            if g.get("can_force") and "--force" not in args else
                            _("\nВыключить всё равно: asus-helper-cli gpu eco --display") if _("монитор") in g["error"] else "")
                    raise Error(g["error"] + hint)
                print(GPU_NAMES.get(g["state"], g["state"]))
                return
        raise Error(_("переключение не закончилось за 2 минуты — смотри журнал демона"))
    elif args[0] == "auto" and len(args) == 2 and args[1] in ("on", "off"):
        cl.call("SetGpuAutoEco", "b", args[1] == "on")
    else:
        raise Error(_(__doc__))


def cmd_kbd(cl, args):
    if not args:
        k = cl.state()["keyboard"]
        print(f"{k.get('brightness')}/{k.get('max', 3)}")
    elif args[0] == "timeout" and len(args) == 3:
        cl.call("SetKeyboardTimeout", "uu", int(args[1]), int(args[2]))
    elif args[0].isdigit():
        cl.call("SetKeyboardBrightness", "u", int(args[0]))
    else:
        raise Error("asus-helper-cli kbd 0…3")


def cmd_aura(cl, args):
    k = cl.state()["keyboard"]
    if not args:
        print(f"{k['mode']} {k['color']} {k['color2']} {k['speed']}")
        print(_("светится: ") + ", ".join(x for x in ("awake", "boot", "sleep", "shutdown") if k[x]))
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
        raise Error(_("полоса Slash не найдена"))
    names = {m["id"]: m["name"] for m in sl["modes"]}
    if not args:
        print(_("яркость {0}/3, {1}, пауза {2} с, на батарее: {3}, с закрытой крышкой: {4}").format(sl['brightness'], names.get(sl['mode'], sl['mode']), sl['interval'], _('да') if sl['on_battery'] else _('нет'), _('да') if sl['lid_closed'] else _('нет')))
        print(_("анимации: ") + ", ".join(names))
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


def _remembered_dgpu():
    """Название дискретной видеокарты, которое демон запомнил, пока она была включена."""
    try:
        with open("/etc/asus-helper/config.json") as f:
            d = (json.load(f).get("gpu") or {}).get("dgpu") or {}
        return d.get("model") and d["model"] + (" — " + _("выключена (Eco)") if d else "")
    except (OSError, ValueError):
        return None


def cmd_diag(_cl, _args):
    """Отчёт о возможностях ноутбука — читает железо напрямую, root и демон не нужны."""
    import os
    import platform
    from .daemon import aura, gpu, hardware as hw, hid, slash
    m = hw.model()
    yes = lambda v: _("есть") if v else _("нет")
    print(_("Ноутбук        : {0}  ({1}, {2})").format(m['name'], m['product'], m['vendor']))
    print(_("Ядро           : {0}   asus-armoury: {1}").format(platform.release(), yes(os.path.isdir(hw.ARMOURY))))
    print(_("Режимы         : {0}  (сейчас {1})").format(' '.join(hw.profile_choices()) or _('нет'), hw.profile()))
    print(_("Процессор      : {0}, EPP: {1}, Turbo Boost: {2}, температура: {3} °C").format(hw.cpu_driver(), ' '.join(hw.epp_choices()) or _('нет'), _('нет') if hw.turbo() is None else _('есть'), hw.cpu_temp()))
    print(_("Вентиляторы    : {0}").format(', '.join(_("{0} {1} об/мин").format(f, v) for f, v in hw.fan_rpm().items()) or _('нет')))
    print(_("Свои кривые    : {0}").format(', '.join(hw.curve_fans()) or _('нет')))
    lim = hw.power_limits()
    print(_("Лимиты мощности: ").format() + (", ".join(f"{a} {v['min']}–{v['max']}" for a, v in lim.items()) or _("нет")))
    print(_("Переключатели  : ").format() + (", ".join(a for a in hw.TOGGLE_ATTRS if hw.armoury_attr(a)) or _("нет")))
    print(_("Видеокарта     : {0}{1}").format(_('Eco поддерживается') if gpu.supported() else _('нет NVIDIA / нет dgpu_disable'), '' if gpu.mux_hybrid() else _(', MUX: только NVIDIA')))
    cards = gpu.display_gpus()
    print(_("Видеокарты     : встроенная {0}; дискретная {1}").format(
        (cards["igpu"] or {}).get("model") or _("нет"),
        (cards["dgpu"] or {}).get("model") or _remembered_dgpu() or (_("выключена (Eco)") if gpu.bios_off() else _("нет"))))
    try:
        from .app.hotkey import rog_key
        print(_("Клавиша окна   : {0}").format(_("ROG (Launch 1)") if rog_key() else _("нет — назначается в настройках KDE")))
    except ImportError:
        pass
    b = aura.brightness()
    print(_("Подсветка клав.: яркость {0}, цвет: {1}").format('0–' + str(b['max']) if b else _('нет'), aura.rgb_method() or _('нет')))
    sl = slash.find_device()
    print(f"Slash          : {_("{0}, отчёт {1:#x}, {2} сегм.").format(sl[0], sl[1], slash.segments()) if sl else _('нет')}")
    bat = hw.battery()
    print(_("Батарея        : ") + (_("здоровье {0}%, лимит заряда {1}%").format(bat['health'], bat['charge_limit']) if bat else _("нет")))
    print("HID ASUS       : " + ("; ".join(_("{0} {1:04x} отчёты ").format(d['dev'], d['product']) + ",".join(f"{k:#x}" for k in d["features"])
                                         for d in hid.devices()) or _("нет")))


def cmd_language(cl, args):
    from . import i18n
    if not args or args[0] not in i18n.LANGUAGES:
        print(i18n.LANG)
        return
    if "--local" in args:
        # прямо в файл настроек (root, демон ещё не запущен — так делает установщик)
        from .daemon.config import Config
        cfg = Config().load()
        cfg.data["language"] = args[0]
        cfg.save()
        return
    cl.call("SetLanguage", "s", args[0])


def cmd_restore(cl, args):
    cl.call("RestoreFactory")
    print(_("Заводские лимиты мощности, кривые вентиляторов BIOS и Turbo Boost возвращены"))


COMMANDS = {"restore": cmd_restore, "language": cmd_language, "diag": cmd_diag, "slash": cmd_slash, "boost": cmd_boost, "gpu": cmd_gpu, "kbd": cmd_kbd, "aura": cmd_aura, "status": cmd_status, "profile": cmd_profile, "auto": cmd_auto, "charge": cmd_charge,
            "epp": cmd_epp, "fan": cmd_fan, "power": cmd_power, "import-asusd": cmd_import}


def main() -> int:
    argv = sys.argv[1:]
    session = "--session" in argv
    argv = [a for a in argv if a != "--session"]
    if argv and argv[0] in ("-h", "--help", "help"):
        print(_(__doc__))
        return 0
    cmd = COMMANDS.get(argv[0] if argv else "status")
    if cmd is None:
        print(_(__doc__))
        return 2
    try:
        local = cmd in (cmd_import, cmd_diag) or (cmd is cmd_language and "--local" in argv)
        cmd(None if local else Client(session), argv[1:])
    except Error as e:
        print(_("ошибка: {0}").format(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
