"""Проверка всех функций на живом ноутбуке через запущенный демон (как это делает окно).

  python3 -m tests.hw_check            всё, кроме видеокарты
  python3 -m tests.hw_check --gpu      и переключение видеокарты (занимает ~20 с)

Каждая проверка вызывает метод демона и смотрит, что реально записалось в ядро / устройство.
В конце всё возвращается как было до проверки.
"""
import json
import subprocess
import sys
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from asushelper import BUS_NAME, INTERFACE, OBJECT_PATH

bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
results = []

ARM = "/sys/class/firmware-attributes/asus-armoury/attributes"
CURVE = None


def read(p):
    with open(p) as f:
        return f.read().strip()


def call(method, sig=None, *args):
    r = bus.call_sync(BUS_NAME, OBJECT_PATH, INTERFACE, method,
                      GLib.Variant(f"({sig})", args) if sig else None, None, Gio.DBusCallFlags.NONE, 60000, None)
    v = r.unpack()
    return v[0] if v else None


def state():
    return json.loads(call("GetState"))


def config():
    return json.loads(call("GetConfig"))


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail else ""))


def expect_error(name, fn):
    try:
        fn()
        check(name, False, "ошибки не было")
    except GLib.Error as e:
        check(name, True, e.message.split(": ", 1)[-1][:70])


def wait(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return cond()


def curve_dir():
    for i in range(20):
        try:
            if read(f"/sys/class/hwmon/hwmon{i}/name") == "asus_custom_fan_curve":
                return f"/sys/class/hwmon/hwmon{i}"
        except OSError:
            pass


def main():
    do_gpu = "--gpu" in sys.argv
    s0, c0 = state(), config()
    led = "/sys/class/leds/asus::kbd_backlight"
    epp_path = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"
    cd = curve_dir()
    print(f"Начальное состояние: режим {s0['profile']}, GPU {s0['gpu']['state']}, подсветка {s0['keyboard']['mode']} "
          f"{s0['keyboard']['color']}, яркость {s0['keyboard']['brightness']}, заряд до {s0['battery']['charge_limit']}%")

    try:
        print("\n— Режимы")
        for p, epp in (("performance", "performance"), ("balanced", "balance_power"), ("quiet", "power")):
            call("SetProfile", "s", p)
            ok = wait(lambda: read("/sys/firmware/acpi/platform_profile") == p and read(epp_path) == epp
                      and read(f"{cd}/pwm1_enable") == "1" and read(f"{cd}/pwm2_enable") == "1")
            check(f"режим {p}: ядро, EPP {epp}, обе кривые свои", ok,
                  f"{read('/sys/firmware/acpi/platform_profile')} / {read(epp_path)} / {read(f'{cd}/pwm1_enable')}{read(f'{cd}/pwm2_enable')}")
        from asushelper import PROFILES
        r = call("CycleProfile")
        nxt = PROFILES[(PROFILES.index("quiet") + 1) % 3]
        check("CycleProfile (как Fn+F5 из программы)", r == nxt and wait(lambda: state()["profile"] == r), r)
        call("SetProfile", "s", s0["profile"])
        expect_error("неизвестный режим отклоняется", lambda: call("SetProfile", "s", "turbo"))

        print("\n— KDE (power-profiles-daemon)")
        ppd = bus.call_sync("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "org.freedesktop.DBus.Properties",
                            "Get", GLib.Variant("(ss)", ("net.hadess.PowerProfiles", "ActiveProfile")), None,
                            Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        check("KDE видит текущий режим", ppd == {"quiet": "power-saver", "balanced": "balanced",
                                                  "performance": "performance"}[s0["profile"]], ppd)

        print("\n— Автоматика по питанию")
        call("SetAutoProfile", "b", not s0["auto_profile"])
        check("переключатель «Сам по питанию»", config()["auto_profile"] == (not s0["auto_profile"]))
        call("SetAutoProfile", "b", s0["auto_profile"])

        print("\n— EPP режима")
        call("SetEpp", "ss", s0["profile"], "balance_performance")
        check("свой EPP для режима", wait(lambda: read(epp_path) == "balance_performance"), read(epp_path))
        call("SetEpp", "ss", s0["profile"], c0["profiles"][s0["profile"]]["epp"] or "")
        expect_error("неверный EPP отклоняется", lambda: call("SetEpp", "ss", "quiet", "turbo"))

        print("\n— Кривые вентиляторов")
        prof = s0["profile"]
        old = c0["profiles"][prof]["fan_curves"]["cpu"]
        test = {"temp": [35, 45, 55, 62, 70, 78, 85, 92], "pwm": [10, 20, 40, 70, 110, 150, 200, 240]}
        call("SetFanCurve", "ssaiai", prof, "cpu", test["temp"], test["pwm"])
        got = [int(read(f"{cd}/pwm1_auto_point{i}_temp")) for i in range(1, 9)]
        check("своя кривая CPU записана в ядро", wait(lambda: [int(read(f"{cd}/pwm1_auto_point{i}_temp"))
                                                                  for i in range(1, 9)] == test["temp"]), str(got))
        check("кривая GPU осталась своей", read(f"{cd}/pwm2_enable") == "1")
        expect_error("убывающая кривая отклоняется",
                     lambda: call("SetFanCurve", "ssaiai", prof, "cpu", test["temp"], [50, 20, 40, 70, 110, 150, 200, 240]))
        f = json.loads(call("GetFactoryFanCurves"))
        check("заводские кривые BIOS читаются", f["curves"]["cpu"] and len(f["curves"]["cpu"]["temp"]) == 8,
              " ".join(map(str, f["curves"]["cpu"]["temp"])))
        check("после чтения заводских свои кривые вернулись",
              wait(lambda: read(f"{cd}/pwm1_enable") == "1" and read(f"{cd}/pwm2_enable") == "1"))
        call("ResetFanCurve", "ss", prof, "cpu")
        check("кривая CPU отдана BIOS", wait(lambda: read(f"{cd}/pwm1_enable") == "2"))
        check("а кривая GPU осталась своей (порядок записи)", read(f"{cd}/pwm2_enable") == "1")
        if old:
            call("SetFanCurve", "ssaiai", prof, "cpu", old["temp"], old["pwm"])
        rpm = state()["fans"]
        check("обороты вентиляторов читаются", rpm["cpu"] is not None and rpm["gpu"] is not None, str(rpm))

        print("\n— Лимиты мощности")
        lim = s0["power_limits"]["ppt_pl1_spl"]
        target = lim["min"] + 2
        call("SetPowerLimit", "ssi", prof, "ppt_pl1_spl", target)
        check(f"PL1 = {target} Вт", wait(lambda: int(read(f"{ARM}/ppt_pl1_spl/current_value")) == target),
              read(f"{ARM}/ppt_pl1_spl/current_value"))
        call("SetPowerLimit", "ssi", prof, "ppt_pl1_spl", 500)
        check(f"PL1 500 Вт обрезан до максимума {lim['max']}",
              wait(lambda: int(read(f"{ARM}/ppt_pl1_spl/current_value")) == lim["max"]))
        call("ResetPowerLimits", "s", prof)
        check("сброс лимитов к BIOS", wait(lambda: int(read(f"{ARM}/ppt_pl1_spl/current_value")) == lim["value"], 4)
              and not config()["profiles"][prof]["power_limits"])
        expect_error("несуществующий лимит отклоняется", lambda: call("SetPowerLimit", "ssi", prof, "nv_tgp", 50))

        print("\n— Батарея")
        call("SetChargeLimit", "u", 70)
        check("лимит заряда 70%", read("/sys/class/power_supply/BAT1/charge_control_end_threshold") == "70")
        expect_error("лимит 10% отклоняется", lambda: call("SetChargeLimit", "u", 10))
        call("SetChargeLimit", "u", s0["battery"]["charge_limit"])

        print("\n— Переключатели BIOS")
        for attr in ("panel_overdrive", "boot_sound"):
            v = s0.get("toggles", {}).get(attr)
            if v is None:
                continue
            call("SetToggle", "sb", attr, not v)
            check(f"{attr} → {int(not v)}", read(f"{ARM}/{attr}/current_value") == str(int(not v)))
            call("SetToggle", "sb", attr, v)

        print("\n— Подсветка")
        for lvl in (1, 3):
            call("SetKeyboardBrightness", "u", lvl)
            check(f"яркость {lvl}", read(f"{led}/brightness") == str(lvl) and state()["keyboard"]["brightness"] == lvl)
        for mode in ("breathe", "cycle", "strobe", "static"):
            call("SetAura", "ssss", mode, "#FF0000", "#0000FF", "normal")
            check(f"эффект {mode} принят клавиатурой", state()["keyboard"]["mode"] == mode)
            time.sleep(1)
        call("SetAuraPower", "bbbb", True, True, False, False)
        k = config()["keyboard"]
        check("«когда светиться» сохранено", (k["awake"], k["boot"], k["sleep"], k["shutdown"]) == (True, True, False, False))
        expect_error("неверный цвет отклоняется", lambda: call("SetAura", "ssss", "static", "red", "#000000", "normal"))
        kb = s0["keyboard"]
        call("SetAuraPower", "bbbb", kb["awake"], kb["boot"], kb["sleep"], kb["shutdown"])
        call("SetAura", "ssss", kb["mode"], kb["color"], kb["color2"], kb["speed"])
        call("SetKeyboardBrightness", "u", kb["brightness"])

        print("\n— Экран (KDE)")
        j = json.loads(subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True).stdout)
        edp = next(o for o in j["outputs"] if o["name"].startswith("eDP"))
        cur = next(m for m in edp["modes"] if m["id"] == edp["currentModeId"])
        check("частота экрана читается", round(cur["refreshRate"]) in (60, 240), f"{round(cur['refreshRate'])} Гц")

        if do_gpu:
            print("\n— Видеокарта (медленно)")
            for mode, want in (("eco", "off"), ("standard", None), ("eco", "off")) if s0["gpu"]["state"] != "off" \
                    else (("standard", None), ("eco", "off")):
                call("SetGpuMode", "sb", mode, False)
                ok = wait(lambda: not state()["gpu"]["switching"], 40)
                g = state()["gpu"]
                good = ok and not g["error"] and (g["state"] == want if want else g["state"] != "off")
                check(f"видеокарта → {mode}", good, g["error"] or g["state"])
            call("SetGpuAutoEco", "b", True)
            check("«Оптимальный» включается", config()["gpu"]["auto_eco"])
            call("SetGpuAutoEco", "b", False)
            if s0["gpu"]["state"] != "off":
                call("SetGpuMode", "sb", "standard", False)
                wait(lambda: not state()["gpu"]["switching"], 40)
    finally:
        # вернуть как было
        call("SetProfile", "s", s0["profile"])
        call("SetChargeLimit", "u", s0["battery"]["charge_limit"])

    bad = [r for r in results if not r[1]]
    print(f"\nИтого: {len(results) - len(bad)} из {len(results)} проверок прошли")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
