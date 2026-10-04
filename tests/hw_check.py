"""Полная проверка всех функций на живом ноутбуке через установленный демон (как это делает окно).

  python3 -m tests.hw_check            всё, кроме видеокарты
  python3 -m tests.hw_check --gpu      и переключение видеокарты (~1 мин)

Каждая проверка вызывает метод демона и смотрит, что реально записалось в ядро / устройство.
В конце всё возвращается как было до проверки (режимы, кривые, лимиты, подсветка, Slash, видеокарта).
"""
import copy
import json
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

from asushelper import BUS_NAME, INTERFACE, OBJECT_PATH, PROFILES

bus = Gio.bus_get_sync(Gio.BusType.SYSTEM)
results = []
ARM = "/sys/class/firmware-attributes/asus-armoury/attributes"
EPP = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"
LED = "/sys/class/leds/asus::kbd_backlight"
NAMES = {"quiet": "Тихий", "balanced": "Баланс", "performance": "Турбо"}


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
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  — {detail}" if detail else ""), flush=True)


def expect_error(name, fn):
    try:
        fn()
        check(name, False, "ошибки не было")
    except GLib.Error as e:
        check(name, True, e.message.split(": ", 1)[-1][:80])


def wait(cond, timeout=4.0):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if cond():
                return True
        except (OSError, KeyError):
            pass
        time.sleep(0.1)
    return cond()


def curve_dir():
    for i in range(30):
        try:
            if read(f"/sys/class/hwmon/hwmon{i}/name") == "asus_custom_fan_curve":
                return f"/sys/class/hwmon/hwmon{i}"
        except OSError:
            pass


CD = curve_dir()


def kernel_curve(i):
    return [int(read(f"{CD}/pwm{i}_auto_point{p}_temp")) for p in range(1, 9)], \
           [int(read(f"{CD}/pwm{i}_auto_point{p}_pwm")) for p in range(1, 9)], read(f"{CD}/pwm{i}_enable")


def set_profile(p):
    call("SetProfile", "s", p)
    return wait(lambda: read("/sys/firmware/acpi/platform_profile") == p and state()["profile"] == p, 5)


# ---------------------------------------------------------------------------------------------
def test_profiles(s0, c0):
    print("\n— Режимы: ядро, EPP, Turbo Boost, кривые")
    boost_default = {"quiet": False, "balanced": True, "performance": True}
    epp_default = {"quiet": "power", "balanced": "balance_power", "performance": "performance"}
    for p in PROFILES:
        ok = set_profile(p)
        time.sleep(1.5)       # кривые через 0,1 с, лимиты и EPP через 1,1 с
        cfg = c0["profiles"][p]
        want_epp = cfg.get("epp") or epp_default[p]
        want_boost = boost_default[p] if cfg.get("cpu_boost") is None else cfg["cpu_boost"]
        st = state()
        check(f"{NAMES[p]}: режим в ядре", ok)
        check(f"{NAMES[p]}: EPP {want_epp}", read(EPP) == want_epp, read(EPP))
        check(f"{NAMES[p]}: Turbo Boost {'вкл' if want_boost else 'выкл'}", st["cpu_boost"] == want_boost)
        for i, fan in ((1, "cpu"), (2, "gpu")):
            mine = (cfg["fan_curves"] or {}).get(fan)
            _, _, en = kernel_curve(i)
            check(f"{NAMES[p]}: кривая {fan.upper()} — {'своя' if mine else 'BIOS'}", en == ("1" if mine else "2"), f"pwm_enable={en}")
    st = state()
    f = config().get("factory_curves", {})
    check("заводские кривые запомнены для всех режимов", all(set(f.get(p, {})) >= {"cpu", "gpu"} for p in PROFILES),
          ", ".join(f"{NAMES[p]}: {len(f.get(p, {}))}" for p in PROFILES))
    r = call("CycleProfile")
    check("CycleProfile (как Fn+F5 из программы)", r in PROFILES and wait(lambda: state()["profile"] == r), r)
    expect_error("неизвестный режим отклоняется", lambda: call("SetProfile", "s", "turbo"))
    ppd = bus.call_sync("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "org.freedesktop.DBus.Properties",
                        "Get", GLib.Variant("(ss)", ("net.hadess.PowerProfiles", "ActiveProfile")), None,
                        Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    gnome = "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    check("GNOME видит режим" if gnome else "KDE видит режим",
          ppd == {"quiet": "power-saver", "balanced": "balanced", "performance": "performance"}[r], ppd)
    if gnome:
        # меню питания GNOME берёт список режимов из свойства Profiles
        profiles = bus.call_sync("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "org.freedesktop.DBus.Properties",
                                 "Get", GLib.Variant("(ss)", ("net.hadess.PowerProfiles", "Profiles")), None,
                                 Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
        names = [p["Profile"] for p in profiles]
        check("меню питания GNOME видит все три режима", len(names) == 3, " ".join(names))
    else:
        kde = subprocess.run(["qdbus6", "org.kde.Solid.PowerManagement", "/org/kde/Solid/PowerManagement/Actions/PowerProfile",
                              "profileChoices"], capture_output=True, text=True).stdout.split()
        check("виджет батареи KDE видит все три режима", len(kde) == 3, " ".join(kde))


def test_curves_independent(s0, c0):
    print("\n— Кривые вентиляторов: у каждого режима своя")
    cq = {"temp": [35, 45, 55, 62, 70, 78, 85, 92], "pwm": [10, 20, 40, 70, 110, 150, 200, 240]}
    cb = {"temp": [40, 50, 58, 64, 70, 76, 84, 90], "pwm": [30, 40, 60, 90, 120, 160, 210, 250]}
    call("SetFanCurve", "ssaiai", "quiet", "cpu", cq["temp"], cq["pwm"])
    call("SetFanCurve", "ssaiai", "balanced", "cpu", cb["temp"], cb["pwm"])
    cfg = config()["profiles"]
    check("Тихий и Баланс хранят разные кривые CPU",
          cfg["quiet"]["fan_curves"]["cpu"]["temp"] == cq["temp"] and cfg["balanced"]["fan_curves"]["cpu"]["temp"] == cb["temp"])
    check("у Турбо кривая CPU не изменилась", cfg["performance"]["fan_curves"]["cpu"] == c0["profiles"]["performance"]["fan_curves"]["cpu"])
    for p, c in (("quiet", cq), ("balanced", cb)):
        set_profile(p)
        ok = wait(lambda: kernel_curve(1)[0] == c["temp"] and kernel_curve(1)[2] == "1", 3)
        check(f"{NAMES[p]}: в ядре своя кривая этого режима", ok, str(kernel_curve(1)[0]))
    set_profile("performance")
    mine = c0["profiles"]["performance"]["fan_curves"]["cpu"]
    check("Турбо: кривая не из других режимов", wait(lambda: kernel_curve(1)[2] == ("1" if mine else "2"), 3))
    expect_error("убывающая кривая отклоняется",
                 lambda: call("SetFanCurve", "ssaiai", "quiet", "cpu", cq["temp"], [50, 20, 40, 70, 110, 150, 200, 240]))
    set_profile("quiet")
    f = json.loads(call("GetFactoryFanCurves"))
    check("заводские кривые текущего режима читаются", len(f["curves"].get("cpu", {}).get("temp", [])) == 8)
    check("после чтения заводских своя кривая вернулась", wait(lambda: kernel_curve(1)[2] == "1", 3))
    call("ResetFanCurve", "ss", "quiet", "cpu")
    check("кривую CPU можно отдать BIOS", wait(lambda: kernel_curve(1)[2] == "2", 3))
    gpu_mine = config()["profiles"]["quiet"]["fan_curves"]["gpu"]
    check("при этом кривая GPU не сбросилась", kernel_curve(2)[2] == ("1" if gpu_mine else "2"))
    # вернуть кривые
    for p in PROFILES:
        for fan in ("cpu", "gpu"):
            old = c0["profiles"][p]["fan_curves"].get(fan)
            if old:
                call("SetFanCurve", "ssaiai", p, fan, old["temp"], old["pwm"])
            else:
                call("ResetFanCurve", "ss", p, fan)


def test_power(s0, c0):
    print("\n— Лимиты мощности, EPP, Turbo Boost по режимам")
    set_profile("balanced")
    lims = state()["power_limits"]
    for attr, lim in lims.items():
        if lim["min"] is None or lim["max"] is None or lim["max"] <= lim["min"]:
            continue
        target = lim["min"] + 1
        call("SetPowerLimit", "ssi", "balanced", attr, target)
        check(f"{attr} = {target}", wait(lambda: int(read(f"{ARM}/{attr}/current_value")) == target, 3))
    call("SetPowerLimit", "ssi", "balanced", "ppt_pl1_spl", 999)
    check("PL1 999 Вт обрезан до максимума", wait(lambda: int(read(f"{ARM}/ppt_pl1_spl/current_value")) == lims["ppt_pl1_spl"]["max"], 3))
    check("лимиты Баланса не попали в другие режимы (настройки)",
          not config()["profiles"]["quiet"]["power_limits"] and not config()["profiles"]["performance"]["power_limits"])
    set_profile("quiet")
    time.sleep(1.5)
    q = state()["power_limits"]
    leaked = [a for a, v in q.items() if v["min"] is not None and v["max"] is not None and v["max"] > v["min"]
              and v["value"] != v["default"]]
    check("в Тихом заводские лимиты — Баланс не перетёк (железо)", not leaked, ", ".join(leaked))
    set_profile("balanced")
    time.sleep(1.5)
    call("ResetPowerLimits", "s", "balanced")
    check("сброс лимитов к BIOS", wait(lambda: int(read(f"{ARM}/ppt_pl1_spl/current_value")) == lims["ppt_pl1_spl"]["default"], 5),
          read(f"{ARM}/ppt_pl1_spl/current_value"))
    expect_error("несуществующий лимит отклоняется", lambda: call("SetPowerLimit", "ssi", "balanced", "nv_tgp", 50))
    call("SetEpp", "ss", "balanced", "balance_performance")
    check("свой EPP Баланса", wait(lambda: read(EPP) == "balance_performance", 3))
    call("SetEpp", "ss", "balanced", c0["profiles"]["balanced"].get("epp") or "")
    expect_error("неверный EPP отклоняется", lambda: call("SetEpp", "ss", "quiet", "turbo"))
    call("SetCpuBoost", "sb", "balanced", False)
    check("Turbo Boost выключается в Балансе", wait(lambda: state()["cpu_boost"] is False, 3))
    call("SetCpuBoost", "sb", "balanced", True)
    check("и включается обратно", wait(lambda: state()["cpu_boost"] is True, 3))
    old = c0["profiles"]["balanced"].get("cpu_boost")
    if old is not None:
        call("SetCpuBoost", "sb", "balanced", old)
    call("SetAutoProfile", "b", not s0["auto_profile"])
    check("переключатель «Сам по питанию»", config()["auto_profile"] == (not s0["auto_profile"]))
    call("SetAutoProfile", "b", s0["auto_profile"])


def test_battery_toggles(s0, c0):
    print("\n— Батарея и переключатели BIOS")
    for v in (60, 80, 100):
        call("SetChargeLimit", "u", v)
        check(f"лимит заряда {v}%", read("/sys/class/power_supply/BAT1/charge_control_end_threshold") == str(v))
    expect_error("лимит 10% отклоняется", lambda: call("SetChargeLimit", "u", 10))
    call("SetChargeLimit", "u", s0["battery"]["charge_limit"])
    for attr, v in s0.get("toggles", {}).items():
        call("SetToggle", "sb", attr, not v)
        check(f"{attr} → {int(not v)}", read(f"{ARM}/{attr}/current_value") == str(int(not v)))
        call("SetToggle", "sb", attr, v)
        check(f"{attr} → {int(v)} (обратно)", read(f"{ARM}/{attr}/current_value") == str(int(v)))


def test_keyboard(s0, c0):
    print("\n— Подсветка клавиатуры")
    kb = s0["keyboard"]
    for lvl in range(kb.get("max", 3) + 1):
        call("SetKeyboardBrightness", "u", lvl)
        check(f"яркость {lvl}", read(f"{LED}/brightness") == str(lvl) and state()["keyboard"]["brightness"] == lvl)
    if kb.get("rgb"):
        for mode in ("static", "breathe", "cycle", "strobe"):
            for speed in ("slow", "normal", "fast"):
                call("SetAura", "ssss", mode, "#FF3000", "#0040FF", speed)
            check(f"эффект {mode} на всех скоростях", state()["keyboard"]["mode"] == mode)
            time.sleep(0.7)
        for color in ("#FF0000", "#00FF00", "#0000FF", "#FFFFFF"):
            call("SetAura", "ssss", "static", color, "#000000", "normal")
        check("цвета применяются", state()["keyboard"]["color"] == "#FFFFFF")
        call("SetAuraPower", "bbbb", True, True, False, False)
        k = config()["keyboard"]
        check("«когда светиться» сохранено", (k["awake"], k["boot"], k["sleep"], k["shutdown"]) == (True, True, False, False))
        expect_error("неверный цвет отклоняется", lambda: call("SetAura", "ssss", "static", "red", "#000000", "normal"))
        expect_error("неверный эффект отклоняется", lambda: call("SetAura", "ssss", "rainbow", "#FF0000", "#000000", "normal"))
        call("SetAuraPower", "bbbb", kb["awake"], kb["boot"], kb["sleep"], kb["shutdown"])
        call("SetAura", "ssss", kb["mode"], kb["color"], kb["color2"], kb["speed"])
    call("SetKeyboardBrightness", "u", kb["brightness"])


def test_slash(s0, c0):
    sl = s0.get("slash") or {}
    if not sl.get("supported"):
        return
    print("\n— Подсветка крышки (Slash)")
    for m in sl["modes"]:
        try:
            call("SetSlash", "suu", m["id"], 2, 0)
            ok = state()["slash"]["mode"] == m["id"]
        except GLib.Error as e:
            ok = False
        results.append((f"Slash: {m['name']}", ok, ""))
        time.sleep(0.4)
    bad = [r[0] for r in results if r[0].startswith("Slash:") and not r[1]]
    print(f"  {'✅' if not bad else '❌'} Slash: все {len(sl['modes'])} анимаций приняты" + (f" — ошибки: {bad}" if bad else ""))
    for b in range(4):
        call("SetSlash", "suu", "bounce", b, 1)
        check(f"Slash: яркость {b}", state()["slash"]["brightness"] == b)
    for ob, lc in ((False, True), (True, False)):
        call("SetSlashOptions", "bb", ob, lc)
        c = config()["slash"]
        check(f"Slash: на батарее {ob}, с закрытой крышкой {lc}", (c["on_battery"], c["lid_closed"]) == (ob, lc))
    expect_error("Slash: яркость 9 отклоняется", lambda: call("SetSlash", "suu", "bounce", 9, 0))
    c = c0["slash"]
    call("SetSlashOptions", "bb", c["on_battery"], c["lid_closed"])
    call("SetSlash", "suu", c["mode"], c["brightness"], c["interval"])


def test_history(s0, c0):
    print("\n— История и графики")
    h = json.loads(call("GetHistory"))
    check("датчики записываются (раз в 5 с)", len(h["t"]) > 0, f"{len(h['t'])} точек")
    check("в истории температура, вентиляторы, мощность",
          all(len(h[k]) == len(h["t"]) for k in ("cpu_temp", "fan_cpu", "fan_gpu", "battery_w")))
    check("здоровье батареи записано", len(h["health"]) > 0, str(h["health"][-1:] if h["health"] else ""))
    up = bus.call_sync("org.freedesktop.UPower", "/org/freedesktop/UPower/devices/battery_BAT1",
                       "org.freedesktop.UPower.Device", "GetHistory", GLib.Variant("(suu)", ("charge", 86400, 50)),
                       None, Gio.DBusCallFlags.NONE, 5000, None).unpack()[0]
    check("история заряда за сутки (UPower)", len(up) > 0, f"{len(up)} точек")
    d = subprocess.run(["asus-helper-cli", "diag"], capture_output=True, text=True)
    check("asus-helper-cli diag", d.returncode == 0 and "Ноутбук" in d.stdout)


def test_gpu(s0, c0):
    print("\n— Видеокарта (медленно)")
    signals = []
    sub = bus.signal_subscribe(BUS_NAME, INTERFACE, "StateChanged", OBJECT_PATH, None, Gio.DBusSignalFlags.NONE,
                               lambda *a: signals.append((time.time(), json.loads(a[5].unpack()[0])["gpu"])))
    ctx = GLib.MainContext.default()

    def switch(mode):
        signals.clear()
        t0 = time.time()
        call("SetGpuModeFlags", "su", mode, 0)
        first = None
        end = t0 + 120     # с паузой после загрузки драйвера (SETTLE_S) и включением в BIOS
        while time.time() < end:
            ctx.iteration(False)
            if first is None and any(g["switching"] for _, g in signals):
                first = next(t for t, g in signals if g["switching"]) - t0
            if signals and not signals[-1][1]["switching"] and first is not None:
                break
            time.sleep(0.05)
        g = state()["gpu"]
        return first, g

    def wait_idle():
        end = time.time() + 120
        while state()["gpu"]["switching"] and time.time() < end:
            time.sleep(1)

    if state()["gpu"].get("stuck"):
        check("видеокарта переключается (драйвер не завис)", False, state()["gpu"]["error"])
        return
    wait_idle()
    osd_before = osd_count()
    seq = ["eco", "standard"] if s0["gpu"]["state"] != "off" else ["standard", "eco"]
    for mode in seq + seq:
        first, g = switch(mode)
        want_off = mode == "eco"
        good = not g["error"] and ((g["state"] == "off") == want_off)
        check(f"видеокарта → {mode}", good, g["error"] or g["state"])
        check(f"  окно сразу видит «переключаюсь» ({mode})", first is not None and first < 1.0,
              f"{first:.2f} с" if first is not None else "не пришло")
    time.sleep(3)
    check("окно выбора экрана не появлялось", osd_count() == osd_before)
    check("мониторов на NVIDIA нет (проверка Eco не мешает)", state()["gpu"].get("external") == [])
    call("SetGpuAutoEco", "b", True)
    check("«Авто» включается", config()["gpu"]["auto_eco"])
    call("SetGpuAutoEco", "b", False)
    wait_idle()           # «Авто» на батарее сразу начинает выключать NVIDIA — дождаться
    # вернуть как было
    if (state()["gpu"]["state"] == "off") != (s0["gpu"]["state"] == "off"):
        switch("eco" if s0["gpu"]["state"] == "off" else "standard")
    if s0["gpu"]["auto_eco"]:
        call("SetGpuAutoEco", "b", True)
        wait_idle()
    bus.signal_unsubscribe(sub)


def osd_count():
    out = subprocess.run(["journalctl", "--user", "-b", "--no-pager", "-o", "cat", "-u", "plasma-kscreen-osd.service"],
                         capture_output=True, text=True).stdout
    return out.count("Started KScreen OSD service")


def main():
    do_gpu = "--gpu" in sys.argv
    s0, c0 = state(), config()
    c0 = copy.deepcopy(c0)
    print(f"Ноутбук: {s0['model']['name']}. Начало: режим {s0['profile']}, видеокарта {s0['gpu']['state']}, "
          f"подсветка {s0['keyboard']['mode']} {s0['keyboard']['color']}, заряд до {s0['battery']['charge_limit']}%")
    try:
        for t in (test_profiles, test_curves_independent, test_power, test_battery_toggles, test_keyboard, test_slash,
                  test_history):
            t(s0, c0)
        if do_gpu:
            test_gpu(s0, c0)
    finally:
        call("SetProfile", "s", s0["profile"])
        call("SetChargeLimit", "u", s0["battery"]["charge_limit"])
    bad = [r for r in results if not r[1]]
    print(f"\nИтого: {len(results) - len(bad)} из {len(results)} проверок прошли")
    for r in bad:
        print(f"  ❌ {r[0]}  {r[2]}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
