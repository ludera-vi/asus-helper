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
        self.assertEqual(aura.find_device(), "/dev/hidraw0")
        cfg = {"mode": "static", "color": "#80A68E", "color2": "#000000", "speed": "normal",
               "awake": True, "boot": True, "sleep": True, "shutdown": True}
        self.assertTrue(aura.apply(cfg))
        data = open(ROOT + "/dev/hidraw0", "rb").read()
        reports = [data[i:i + aura.FEATURE_LEN] for i in range(0, len(data), aura.FEATURE_LEN)]
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
        self.assertEqual(slash.find_device(), "/dev/hidraw1")
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
