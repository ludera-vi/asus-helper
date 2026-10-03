"""Тесты демона на поддельном sysfs. Запуск: python -m unittest discover -s tests -t ."""
import json
import os
import tempfile
import unittest

ROOT = tempfile.mkdtemp(prefix="asushelper-sys-")
CONF = tempfile.mkdtemp(prefix="asushelper-conf-")
os.environ["ASUSHELPER_SYSROOT"] = ROOT
os.environ["ASUSHELPER_CONFIG_DIR"] = CONF

import gi  # noqa: E402
gi.require_version("Gio", "2.0")
from gi.repository import GLib  # noqa: E402

from asushelper import asusd_import  # noqa: E402
from asushelper.daemon import hardware as hw  # noqa: E402
from asushelper.daemon import sysfs  # noqa: E402
from asushelper.daemon.config import Config  # noqa: E402
from asushelper.daemon.modes import Modes  # noqa: E402
from tests import fakesys  # noqa: E402

CURVE = "/sys/class/hwmon/hwmon7"
EPP0 = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"
PL1 = "/sys/class/firmware-attributes/asus-armoury/attributes/ppt_pl1_spl/current_value"

FAN_CURVES_RON = """(
    profiles: (
        balanced: [
            (
                fan: CPU,
                pwm: (4, 4, 27, 62, 98, 121, 150, 164),
                temp: (22, 51, 62, 69, 74, 78, 83, 88),
                enabled: true,
            ),
            (
                fan: GPU,
                pwm: (5, 6, 17, 41, 65, 95, 125, 146),
                temp: (20, 52, 58, 62, 66, 71, 76, 83),
                enabled: false,
            ),
        ],
        performance: [],
        quiet: [
            (
                fan: CPU,
                pwm: (5, 6, 17, 51, 84, 102, 102, 105),
                temp: (30, 53, 62, 68, 73, 78, 78, 78),
                enabled: true,
            ),
        ],
        custom: [],
    ),
)"""

ASUSD_RON = """(
    charge_control_end_threshold: 80,
    disable_nvidia_powerd_on_battery: true,
    platform_profile_linked_epp: true,
    platform_profile_on_battery: Quiet,
    platform_profile_on_ac: Performance,
    profile_quiet_epp: Power,
    profile_balanced_epp: BalancePower,
    profile_performance_epp: Performance,
)"""


def run_loop(ms: int) -> None:
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, loop.quit)
    loop.run()


class HardwareTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)

    def test_read(self):
        self.assertEqual(hw.profile(), "quiet")
        self.assertFalse(hw.on_ac())
        self.assertEqual(hw.fan_rpm(), {"cpu": 1900, "gpu": 1800})
        self.assertEqual(hw.cpu_temp(), 52.0)
        b = hw.battery()
        self.assertEqual(b["health"], 82)
        self.assertEqual(b["power_w"], 16.0)

    def test_armoury_clamped_to_range(self):
        self.assertTrue(hw.set_armoury("ppt_pl1_spl", 90))
        self.assertEqual(fakesys.read(ROOT, PL1), "35")
        self.assertTrue(hw.set_armoury("ppt_pl1_spl", 10))
        self.assertEqual(fakesys.read(ROOT, PL1), "25")
        self.assertFalse(hw.set_armoury("nv_tgp", 10))   # такого параметра нет

    def test_curve_validation(self):
        ok = ([30, 40, 50, 60, 70, 80, 90, 100], [0, 10, 20, 40, 80, 120, 200, 255])
        self.assertIsNone(hw.validate_curve(*ok))
        self.assertIsNotNone(hw.validate_curve(ok[0][:7], ok[1][:7]))
        self.assertIsNotNone(hw.validate_curve([30, 20, 50, 60, 70, 80, 90, 100], ok[1]))
        self.assertIsNotNone(hw.validate_curve(ok[0], [0, 10, 5, 40, 80, 120, 200, 255]))
        self.assertIsNotNone(hw.validate_curve(ok[0], [0, 10, 20, 40, 80, 120, 200, 300]))

    def test_set_curve_enables_after_points(self):
        temp, pwm = [30, 40, 50, 60, 70, 80, 90, 100], [0, 10, 20, 40, 80, 120, 200, 255]
        self.assertTrue(hw.set_fan_curve("gpu", temp, pwm))
        c = hw.fan_curve("gpu")
        self.assertEqual((c["temp"], c["pwm"], c["enabled"]), (temp, pwm, True))
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "2")   # CPU не тронут

    def test_epp_rejects_unknown(self):
        self.assertFalse(hw.set_epp("turbo"))
        self.assertTrue(hw.set_epp("performance"))
        self.assertEqual(fakesys.read(ROOT, EPP0), "performance")


class ImportTest(unittest.TestCase):
    def test_parse_fan_curves(self):
        c = asusd_import.parse_fan_curves(FAN_CURVES_RON)
        self.assertEqual(c["balanced"]["cpu"]["pwm"], [4, 4, 27, 62, 98, 121, 150, 164])
        self.assertFalse(c["balanced"]["gpu"]["enabled"])
        self.assertEqual(c["quiet"]["cpu"]["temp"], [30, 53, 62, 68, 73, 78, 78, 78])
        self.assertNotIn("performance", c)

    def test_parse_asusd(self):
        a = asusd_import.parse_asusd(ASUSD_RON)
        self.assertEqual(a["charge_limit"], 80)
        self.assertEqual(a["profile_on_ac"], "performance")
        self.assertEqual(a["profile_on_battery"], "quiet")
        self.assertEqual(a["profiles"]["balanced"]["epp"], "balance_power")

    def test_real_asusd_files_if_present(self):
        if not os.path.exists("/etc/asusd/fan_curves.ron"):
            self.skipTest("нет /etc/asusd")
        cfg = Config(os.path.join(CONF, "import.json"))
        done = asusd_import.import_into(cfg)
        self.assertTrue(done)
        for p in cfg.data["profiles"].values():
            for c in p["fan_curves"].values():
                if c:
                    self.assertIsNone(hw.validate_curve(c["temp"], c["pwm"]))


class ModesTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)
        self.cfg = Config(os.path.join(CONF, "modes.json"))
        self.cfg.data["profiles"]["performance"]["fan_curves"]["cpu"] = {
            "enabled": True, "temp": [40, 50, 55, 60, 65, 70, 75, 80], "pwm": [50, 60, 90, 110, 140, 160, 210, 220]}
        self.cfg.data["profiles"]["performance"]["power_limits"] = {"ppt_pl1_spl": 30}
        self.changes = 0
        self.modes = Modes(self.cfg, self._changed)

    def _changed(self):
        self.changes += 1

    def test_set_profile_applies_in_order(self):
        self.modes.set_profile("performance")
        self.assertEqual(hw.profile(), "performance")
        # кривые и лимиты — не сразу, а после задержки (BIOS иначе их затрёт)
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "2")
        run_loop(300)
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "1")
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm2_enable"), "2")
        self.assertEqual(fakesys.read(ROOT, EPP0), "power")
        run_loop(1000)
        self.assertEqual(fakesys.read(ROOT, EPP0), "performance")
        self.assertEqual(fakesys.read(ROOT, PL1), "30")
        # выбор запомнен для батареи
        self.assertEqual(self.cfg.data["profile_on_battery"], "performance")

    def test_bios_curves_reset_before_custom(self):
        # у GPU сейчас своя кривая, а в режиме performance она должна стать BIOS-кривой
        hw.set_fan_curve_mode("gpu", hw.CURVE_ON)
        writes = []
        orig = sysfs.write
        sysfs.write = lambda p, v: writes.append((p.rsplit("/", 1)[1], str(v))) or orig(p, v)
        try:
            self.modes._apply_fans("performance")
        finally:
            sysfs.write = orig
        enables = [w for w in writes if w[0].endswith("_enable")]
        # при первом включении режима — узнать заводские обоих (3 → 2); своя CPU — последней
        self.assertEqual(enables, [("pwm1_enable", "3"), ("pwm1_enable", "2"),
                                   ("pwm2_enable", "3"), ("pwm2_enable", "2"), ("pwm1_enable", "1")])
        # второй раз заводская уже известна — только вернуть BIOS, потом своя
        writes.clear()
        hw.set_fan_curve_mode("gpu", hw.CURVE_ON)
        sysfs.write = lambda p, v: writes.append((p.rsplit("/", 1)[1], str(v))) or orig(p, v)
        try:
            self.modes._apply_fans("performance")
        finally:
            sysfs.write = orig
        enables = [w for w in writes if w[0].endswith("_enable")]
        self.assertEqual(enables, [("pwm2_enable", "2"), ("pwm1_enable", "1")])

    def test_quick_switch_cancels_previous(self):
        self.modes.set_profile("performance")
        self.modes.set_profile("balanced")
        run_loop(1300)
        self.assertEqual(hw.profile(), "balanced")
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "2")
        self.assertEqual(fakesys.read(ROOT, EPP0), "balance_power")
        self.assertEqual(fakesys.read(ROOT, PL1), "35")

    def test_hotkey_change_reapplies(self):
        # ядро сменило режим само (Fn+F5) — эмулируем уведомление
        with open(ROOT + hw.PROFILE, "w") as f:
            f.write("performance\n")
        self.modes._on_profile_event(os.open(ROOT + hw.PROFILE, os.O_RDONLY), None)
        self.assertEqual(self.modes.current, "performance")
        run_loop(800)
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "1")
        self.assertEqual(fakesys.read(ROOT, PL1), "30")
        self.assertEqual(self.cfg.data["profile_on_battery"], "performance")

    def test_power_source_switches_profile(self):
        self.cfg.data["profile_on_ac"] = "performance"
        self.cfg.data["profile_on_battery"] = "quiet"
        self.modes.power_source_changed(True)
        self.assertEqual(hw.profile(), "performance")
        self.modes.power_source_changed(False)
        self.assertEqual(hw.profile(), "quiet")

    def test_config_roundtrip(self):
        self.modes.set_profile("balanced")
        with open(self.cfg.path) as f:
            data = json.load(f)
        self.assertEqual(data["profile_on_battery"], "balanced")
        self.assertEqual(Config(self.cfg.path).load().data["profiles"]["performance"]["power_limits"],
                         {"ppt_pl1_spl": 30})


if __name__ == "__main__":
    unittest.main()


class AuraTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)

    def test_effect_bytes_like_ghelper(self):
        from asushelper.daemon import aura
        m = aura.effect_message("static", "#80A68E", "#000000", "normal")
        self.assertEqual(m.hex(), "5db3000080a68eeb0000000000")
        m = aura.effect_message("breathe", "#FF0000", "#0000FF", "slow")
        self.assertEqual(m.hex(), "5db30001ff0000e1000100" + "00ff")
        # чёрный — случайные цвета
        self.assertEqual(aura.effect_message("static", "#000000")[9], 0xFF)

    def test_power_bits(self):
        from asushelper.daemon import aura
        self.assertEqual(aura.power_message(True, True, True, True).hex(), "5dbd01ff000000ff")
        self.assertEqual(aura.power_message(True, False, False, False)[3], 0b1100)

    def test_apply_writes_feature_reports(self):
        from asushelper.daemon import aura
        self.assertEqual(aura.find_device()["dev"], "/dev/hidraw0")
        self.assertEqual(aura.rgb_method(), "hid")
        cfg = {"mode": "static", "color": "#80A68E", "color2": "#000000", "speed": "normal",
               "awake": True, "boot": True, "sleep": True, "shutdown": True}
        self.assertTrue(aura.apply(cfg))
        data = open(ROOT + "/dev/hidraw0", "rb").read()
        reports = [data[i:i + 63] for i in range(0, len(data), 63)]
        self.assertEqual([r[1] for r in reports], [0xB9, ord("A"), 0xB3, 0xB5, 0xB4, 0xBD])
        self.assertTrue(all(len(r) == 63 and r[0] == 0x5D for r in reports))

    def test_brightness(self):
        from asushelper.daemon import aura
        self.assertEqual(aura.brightness(), {"value": 2, "max": 3})
        self.assertTrue(aura.set_brightness(9))
        self.assertEqual(aura.brightness()["value"], 3)

    def test_parse_real_aura_if_present(self):
        if not os.path.exists("/etc/asusd/aura_19b6.ron"):
            self.skipTest("нет /etc/asusd")
        a = asusd_import.parse_aura(open("/etc/asusd/aura_19b6.ron").read())
        self.assertIn(a["mode"], ("static", "breathe", "cycle", "strobe"))
        self.assertRegex(a["color"], r"^#[0-9A-F]{6}$")


class GpuTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)

    def test_state_off_and_no_nvidia(self):
        from asushelper.daemon import gpu
        self.assertTrue(gpu.supported())
        self.assertTrue(gpu.mux_hybrid())
        self.assertEqual(gpu.state(), "off")
        self.assertIsNone(gpu.find_gpu())     # на шине только Intel
        self.assertFalse(gpu.fixup())          # убирать нечего


class SlashTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)

    def test_battery_pattern(self):
        from asushelper.daemon import slash
        self.assertEqual(slash.battery_pattern(3, 100), [255] * 7)
        self.assertEqual(slash.battery_pattern(3, 0), [0] * 7)
        p = slash.battery_pattern(3, 50)        # 3.5 сегмента справа
        self.assertEqual(p[4:], [255, 255, 255])
        self.assertTrue(0 < p[3] < 255)
        self.assertEqual(p[:3], [0, 0, 0])

    def test_apply_sequence(self):
        from asushelper.daemon import slash
        self.assertEqual(slash.find_device(), ("/dev/hidraw1", 0x5E, 128))
        self.assertEqual(slash.segments(), 7)
        cfg = {"brightness": 2, "mode": "flow", "interval": 1, "on_battery": True, "lid_closed": False}
        self.assertTrue(slash.apply(cfg, wake=True))
        data = open(ROOT + "/dev/hidraw1", "rb").read()
        reports = [data[i:i + 128] for i in range(0, len(data), 128)]
        self.assertTrue(all(r[0] == 0x5E and len(r) == 128 for r in reports))
        cmds = [r[1] for r in reports]
        # разбудить, на батарее, крышка, включить, init ×2, режим ×2, опции, сохранить
        self.assertEqual(cmds, [ord("A"), 0xC2, 0xD1, 0xD8, 0xD8, 0xD8, 0xD7, 0xD2, 0xD2, 0xD3, 0xD3, 0xD4])
        self.assertEqual(reports[9][6], 0x19)                          # код «Течение»
        self.assertEqual((reports[10][10], reports[10][12]), (170, 1))  # яркость 2 → 170, пауза 1

    def test_off(self):
        from asushelper.daemon import slash
        cfg = {"brightness": 0, "mode": "flow", "interval": 0, "on_battery": True, "lid_closed": True}
        self.assertTrue(slash.apply(cfg))
        data = open(ROOT + "/dev/hidraw1", "rb").read()
        self.assertEqual(data[128 * 2 + 1:128 * 2 + 6], bytes([0xD8, 0x02, 0x00, 0x01, 0x80]))


class BoostTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)

    def test_quiet_turns_boost_off(self):
        cfg = Config(os.path.join(CONF, "boost.json"))
        modes = Modes(cfg, lambda: None)
        modes._apply_power("quiet")
        self.assertEqual(fakesys.read(ROOT, hw.NO_TURBO), "1")
        modes._apply_power("performance")
        self.assertEqual(fakesys.read(ROOT, hw.NO_TURBO), "0")


class GenericTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)

    def test_descriptor_parser(self):
        from asushelper.daemon import hid
        # два отчёта: input 0x5d (не считается) и feature 0x5d 62 байта, feature 0x5a 16 байт
        d = bytes([0x85, 0x5D, 0x75, 0x08, 0x95, 0x20, 0x81, 0x00, 0x95, 0x3E, 0xB1, 0x00,
                   0x85, 0x5A, 0x95, 0x10, 0xB1, 0x00])
        self.assertEqual(hid.feature_lengths(d), {0x5D: 62, 0x5A: 16})

    def test_model_and_fans(self):
        self.assertEqual(hw.model()["name"], "ROG Zephyrus G16 GU605MZ")
        self.assertEqual(hw.fans(), ["cpu", "gpu"])
        self.assertEqual(hw.curve_fans(), ["cpu", "gpu"])

    def test_amd_fallbacks(self):
        os.remove(ROOT + hw.NO_TURBO)
        fakesys._w(ROOT, hw.BOOST, 1)
        self.assertTrue(hw.turbo())
        self.assertTrue(hw.set_turbo(False))
        self.assertEqual(fakesys.read(ROOT, hw.BOOST), "0")
        import shutil
        shutil.rmtree(ROOT + "/sys/class/hwmon/hwmon9")
        fakesys._w(ROOT, "/sys/class/hwmon/hwmon9/name", "k10temp")
        fakesys._w(ROOT, "/sys/class/hwmon/hwmon9/temp1_label", "Tctl")
        fakesys._w(ROOT, "/sys/class/hwmon/hwmon9/temp1_input", 61000)
        self.assertEqual(hw.cpu_temp(), 61.0)

    def test_no_hid_keyboard_uses_wmi(self):
        from asushelper.daemon import aura
        import shutil
        shutil.rmtree(ROOT + "/sys/class/hidraw/hidraw0")
        fakesys._w(ROOT, "/sys/class/leds/asus::kbd_backlight/kbd_rgb_mode", "")
        self.assertEqual(aura.rgb_method(), "wmi")
        cfg = {"mode": "breathe", "color": "#FF8000", "color2": "#000000", "speed": "fast",
               "awake": True, "boot": True, "sleep": True, "shutdown": True}
        self.assertTrue(aura.apply(cfg))
        self.assertEqual(fakesys.read(ROOT, "/sys/class/leds/asus::kbd_backlight/kbd_rgb_mode"), "1 1 255 128 0 245")


class GpuSafetyTest(unittest.TestCase):
    """Выключение NVIDIA никогда не закрывает рабочий стол и системные процессы."""

    def setUp(self):
        fakesys.build(ROOT)
        from asushelper.daemon import gpu
        self.gpu = gpu
        self.saved = (gpu.find_gpu, gpu.bios_off, gpu.holders, gpu.os.kill, gpu.is_protected)
        self.killed = []
        gpu.find_gpu = lambda: "0000:01:00.0"
        gpu.bios_off = lambda: False
        gpu.os.kill = lambda pid, sig: self.killed.append(pid)

    def tearDown(self):
        g = self.gpu
        g.find_gpu, g.bios_off, g.holders, g.os.kill, g.is_protected = self.saved

    def test_desktop_never_killed(self):
        self.gpu.holders = lambda gpu=None: [(1, "systemd"), (900, "kwin_wayland"), (950, "Xwayland"), (4242, "steam")]
        with self.assertRaises(self.gpu.GpuError) as e:
            self.gpu.turn_off(force=True)
        self.assertFalse(e.exception.can_force)
        self.assertIn("рабочий стол", str(e.exception))
        self.assertEqual(self.killed, [])

    def test_user_apps_can_be_forced(self):
        self.gpu.holders = lambda gpu=None: [(4242, "steam")]
        self.gpu.is_protected = lambda pid, comm: False
        with self.assertRaises(self.gpu.GpuError) as e:
            self.gpu.turn_off(force=False)
        self.assertTrue(e.exception.can_force)
        self.assertEqual(self.killed, [])

    def test_root_process_protected(self):
        self.assertTrue(self.gpu.is_protected(1, "anything"))
        self.assertTrue(self.gpu.is_protected(12345, "kwin_wayland"))


class GpuDisplayTest(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)
        from asushelper.daemon import gpu
        self.gpu = gpu
        d = "/sys/bus/pci/devices/0000:01:00.0"
        fakesys._w(ROOT, d + "/vendor", "0x10de")
        fakesys._w(ROOT, d + "/class", "0x030000")
        fakesys._w(ROOT, d + "/drm/card0/card0-eDP-2/status", "connected")     # встроенный через MUX — не в счёт
        fakesys._w(ROOT, d + "/drm/card0/card0-HDMI-A-1/status", "disconnected")

    def test_internal_panel_not_external(self):
        self.assertEqual(self.gpu.external_displays(), [])

    def test_hdmi_monitor_blocks_eco(self):
        fakesys._w(ROOT, "/sys/bus/pci/devices/0000:01:00.0/drm/card0/card0-HDMI-A-1/status", "connected")
        self.assertEqual(self.gpu.external_displays(), ["HDMI-A-1"])
        saved = self.gpu.bios_off
        self.gpu.bios_off = lambda: False
        try:
            with self.assertRaises(self.gpu.GpuError) as e:
                self.gpu.turn_off()
            self.assertIn("монитор", str(e.exception))
        finally:
            self.gpu.bios_off = saved


class FactoryCurvesTest(unittest.TestCase):
    """Кривые режимов независимы; заводская кривая запоминается для каждого режима отдельно."""

    def setUp(self):
        fakesys.build(ROOT)
        self.cfg = Config(os.path.join(CONF, "factory.json"))
        self.modes = Modes(self.cfg, lambda: None)

    def test_learns_factory_once_per_profile(self):
        self.modes._apply_fans("balanced")
        f = self.cfg.data["factory_curves"]
        self.assertEqual(set(f["balanced"]), {"cpu", "gpu"})
        self.assertNotIn("quiet", f)
        # кривая BIOS после запоминания
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "2")
        # второй раз не перечитывает (точки в ядре меняем — кэш не должен поменяться)
        fakesys._w(ROOT, CURVE + "/pwm1_auto_point1_temp", 99)
        self.modes._apply_fans("balanced")
        self.assertNotEqual(f["balanced"]["cpu"]["temp"][0], 99)

    def test_custom_curve_only_in_its_profile(self):
        quiet = {"enabled": True, "temp": [30, 40, 50, 60, 70, 80, 90, 95], "pwm": [0, 10, 20, 40, 80, 120, 200, 255]}
        self.cfg.data["profiles"]["quiet"]["fan_curves"]["cpu"] = quiet
        self.modes._apply_fans("quiet")
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "1")
        self.modes._apply_fans("balanced")
        self.assertEqual(fakesys.read(ROOT, CURVE + "/pwm1_enable"), "2")    # в Балансе — BIOS
        self.assertIsNone(self.cfg.data["profiles"]["balanced"]["fan_curves"]["cpu"])
        self.assertIsNone(self.cfg.data["profiles"]["performance"]["fan_curves"]["cpu"])


class AutoEcoTest(unittest.TestCase):
    """«Авто»: без сети NVIDIA выключается, но не пока её занимают программы."""

    def setUp(self):
        fakesys.build(ROOT)
        from gi.repository import Gio
        from asushelper.daemon import gpu, service as svc
        d = "/sys/bus/pci/devices/0000:01:00.0"
        fakesys._w(ROOT, d + "/vendor", "0x10de")
        fakesys._w(ROOT, d + "/class", "0x030000")
        fakesys._w(ROOT, "/sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value", 0)
        self.gpu, self.svc = gpu, svc
        self.saved = gpu.holders
        cfg = Config(os.path.join(CONF, "auto.json"))
        cfg.data["gpu"]["auto_eco"] = True
        # своё подключение к шине на каждый тест: один объект — одна регистрация
        addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
        bus = Gio.DBusConnection.new_for_address_sync(
            addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
            None, None)
        self.s = svc.Service(bus, cfg)
        self.started = []
        self.s.gpu.start = lambda want_off, *a: self.started.append(want_off) or True
        self.s.modes.ac = False

    def tearDown(self):
        self.gpu.holders = self.saved
        if self.s._auto_timer:
            GLib.source_remove(self.s._auto_timer)

    def test_waits_while_busy_then_turns_off(self):
        self.gpu.holders = lambda gpu=None: [(4242, "resolve")]
        self.assertTrue(self.s._auto_eco())
        self.assertEqual(self.s.auto_waiting, ["resolve"])
        self.assertEqual(self.started, [])                  # не выключаем
        self.assertEqual(self.s.state()["gpu"]["auto_waiting"], ["resolve"])
        self.gpu.holders = lambda gpu=None: []               # программа закрылась
        self.assertFalse(self.s._auto_eco())
        self.assertIsNone(self.s.auto_waiting)
        self.assertEqual(self.started, [True])              # Eco

    def test_charger_cancels_waiting(self):
        self.gpu.holders = lambda gpu=None: [(4242, "steam")]
        self.s._auto_eco()
        self.s.modes.ac = True
        self.assertFalse(self.s._auto_eco())
        self.assertIsNone(self.s.auto_waiting)
        self.assertEqual(self.started, [])                  # карта и так включена
