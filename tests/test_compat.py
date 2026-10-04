"""Другие ноутбуки и системы: поддельный sysfs GU605MZ, переделанный под другую модель.
Запуск: python -m unittest tests.test_compat -v
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

ROOT = os.environ.setdefault("ASUSHELPER_SYSROOT", tempfile.mkdtemp(prefix="asushelper-sys-"))
CONF = os.environ.setdefault("ASUSHELPER_CONFIG_DIR", tempfile.mkdtemp(prefix="asushelper-conf-"))

import gi  # noqa: E402
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

from asushelper.daemon import aura, gpu, hid, slash  # noqa: E402
from asushelper.daemon import hardware as hw  # noqa: E402
from asushelper.daemon.config import Config  # noqa: E402
from asushelper.daemon.modes import Modes  # noqa: E402
from tests import fakesys  # noqa: E402

ARM = "/sys/class/firmware-attributes/asus-armoury/attributes"
EPP0 = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"
PL1 = ARM + "/ppt_pl1_spl/current_value"
CURVE = "/sys/class/hwmon/hwmon7"
NV = "/sys/bus/pci/devices/0000:01:00.0"
BAT = "/sys/class/power_supply/BAT1"


def w(p, v):
    fakesys._w(ROOT, p, v)


def rm(p):
    full = ROOT + p
    if os.path.isdir(full):
        shutil.rmtree(full)
    elif os.path.exists(full):
        os.remove(full)


def read(p):
    return fakesys.read(ROOT, p)


def run_loop(ms):
    loop = GLib.MainLoop()
    GLib.timeout_add(ms, loop.quit)
    loop.run()


def new_bus():
    addr = Gio.dbus_address_get_for_bus_sync(Gio.BusType.SESSION, None)
    return Gio.DBusConnection.new_for_address_sync(
        addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
        None, None)


def add_nvidia():
    w(NV + "/vendor", "0x10de")
    w(NV + "/class", "0x030000")


def tooltip(state):
    """Подсказка значка в трее для состояния state (Tray.update без Qt-окна)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from asushelper.app.__main__ import Tray
    tooltip.app = QApplication.instance() or QApplication([])     # значок рисуется на QPixmap
    t = mock.MagicMock()
    t.backend.state = state
    t.backend.connected = True
    t.mode_actions = {}
    Tray.update(t)
    return t.icon.setToolTip.call_args[0][0]


class Base(unittest.TestCase):
    def setUp(self):
        fakesys.build(ROOT)
        self.cfg = Config(os.path.join(CONF, f"{self.id()}.json"))


# ---------- вентиляторы ----------
class FansTest(Base):
    """TUF, Vivobook, Zenbook: один вентилятор или ядро не показывает их вовсе."""

    def one_fan(self):
        rm("/sys/class/hwmon/hwmon6/fan2_input")
        for f in os.listdir(ROOT + CURVE):
            if f.startswith("pwm2"):
                rm(f"{CURVE}/{f}")

    def test_single_fan_detected(self):
        self.one_fan()
        self.assertEqual(hw.fans(), ["cpu"])
        self.assertEqual(hw.curve_fans(), ["cpu"])
        self.assertEqual(hw.fan_rpm(), {"cpu": 1900})

    def test_single_fan_curves_apply(self):
        self.one_fan()
        self.cfg.data["profiles"]["performance"]["fan_curves"]["cpu"] = {
            "enabled": True, "temp": [40, 50, 55, 60, 65, 70, 75, 80], "pwm": [50, 60, 90, 110, 140, 160, 210, 220]}
        m = Modes(self.cfg, lambda: None)
        m.learn_factory_curves()
        m.set_profile("performance")
        run_loop(300)
        self.assertEqual(read(CURVE + "/pwm1_enable"), "1")

    def test_tray_tooltip_single_fan(self):
        text = tooltip({"profile": "balanced", "cpu_temp": 50.0, "fans": {"cpu": 2100}, "gpu": {}})
        self.assertIn("2100", text)

    def test_tray_tooltip_no_fans(self):
        text = tooltip({"profile": "quiet", "cpu_temp": 45.0, "fans": {}, "gpu": {}})
        self.assertIn("45", text)

    def test_no_fan_curves_kernel(self):
        """Старые ядра/модели без asus_custom_fan_curve: режимы и мощность работают, кривых просто нет."""
        rm(CURVE)
        self.assertFalse(hw.has_fan_curves())
        m = Modes(self.cfg, lambda: None)
        m.learn_factory_curves()
        m.set_profile("performance")
        run_loop(1300)
        self.assertEqual(read(EPP0), "performance")
        self.assertEqual(self.cfg.data["factory_curves"], {})


# ---------- режимы ----------
class ProfileTest(Base):
    def test_no_platform_profile_still_applies_cpu_and_limits(self):
        """Нет platform_profile (старая прошивка, другой драйвер): EPP, Turbo и лимиты всё равно применяются."""
        rm("/sys/firmware/acpi")             # в настоящем sysfs файл не создать — запись не удастся
        self.cfg.data["profiles"]["performance"]["power_limits"] = {"ppt_pl1_spl": 30}
        m = Modes(self.cfg, lambda: None)
        m.set_profile("performance")
        run_loop(1300)
        self.assertEqual(read(EPP0), "performance")
        self.assertEqual(read(PL1), "30")
        self.assertEqual(m.current, "performance")

    def test_low_power_name(self):
        """Ядро называет тихий режим low-power (новые ядра, драйверы amd-pmf и др.)."""
        w(hw.PROFILE_CHOICES, "low-power balanced performance")
        w(hw.PROFILE, "low-power")
        self.assertEqual(hw.profile(), "quiet")
        self.assertEqual(hw.profile_choices(), ["quiet", "balanced", "performance"])
        self.assertTrue(hw.set_profile("balanced"))
        self.assertTrue(hw.set_profile("quiet"))
        self.assertEqual(read(hw.PROFILE), "low-power")

    def test_low_power_hotkey(self):
        w(hw.PROFILE_CHOICES, "low-power balanced performance")
        w(hw.PROFILE, "balanced")
        m = Modes(self.cfg, lambda: None)
        w(hw.PROFILE, "low-power")            # Fn+F5
        m._on_profile_event(os.open(ROOT + hw.PROFILE, os.O_RDONLY), None)
        self.assertEqual(m.current, "quiet")

    def test_only_two_profiles(self):
        """Режима нет в списке ядра — EPP/Turbo применяются, ошибки нет."""
        w(hw.PROFILE_CHOICES, "balanced performance")
        w(hw.PROFILE, "balanced")
        m = Modes(self.cfg, lambda: None)
        m.set_profile("quiet")
        run_loop(1300)
        self.assertEqual(read(EPP0), "power")
        self.assertEqual(hw.profile(), "balanced")


# ---------- процессор ----------
class CpuTest(Base):
    def test_amd_pstate(self):
        rm(hw.NO_TURBO)
        w(hw.BOOST, 1)
        rm("/sys/class/hwmon/hwmon9")
        w("/sys/class/hwmon/hwmon9/name", "k10temp")
        w("/sys/class/hwmon/hwmon9/temp1_label", "Tctl")
        w("/sys/class/hwmon/hwmon9/temp1_input", 70500)
        m = Modes(self.cfg, lambda: None)
        m._apply_power("quiet")
        self.assertEqual(read(hw.BOOST), "0")
        self.assertEqual(read(EPP0), "power")
        self.assertEqual(hw.cpu_temp(), 70.5)

    def test_acpi_cpufreq_without_epp_and_turbo(self):
        for c in range(4):
            rm(f"/sys/devices/system/cpu/cpu{c}/cpufreq/energy_performance_preference")
            rm(f"/sys/devices/system/cpu/cpu{c}/cpufreq/energy_performance_available_preferences")
        rm(hw.NO_TURBO)
        self.assertIsNone(hw.turbo())
        self.assertFalse(hw.set_epp("performance"))
        Modes(self.cfg, lambda: None)._apply_power("performance")    # без исключений

    def test_no_cpu_sensor(self):
        rm("/sys/class/hwmon/hwmon9")
        self.assertIsNone(hw.cpu_temp())


# ---------- видеокарта ----------
class GpuCompatTest(Base):
    def test_no_nvidia(self):
        rm(ARM + "/dgpu_disable")
        self.assertFalse(gpu.supported())
        self.assertEqual(gpu.kwin_env_lines(), [])

    def test_amd_dgpu_not_supported(self):
        w(ARM + "/dgpu_disable/current_value", 0)
        w(NV + "/vendor", "0x1002")
        w(NV + "/class", "0x030000")
        self.assertFalse(gpu.supported())

    def test_legacy_wmi_paths(self):
        """Ядро без asus-armoury (LTS): dgpu_disable и MUX — в asus-nb-wmi."""
        rm("/sys/class/firmware-attributes")
        add_nvidia()
        w("/sys/devices/platform/asus-nb-wmi/dgpu_disable", 0)
        w("/sys/devices/platform/asus-nb-wmi/gpu_mux_mode", 1)
        self.assertTrue(gpu.supported())
        self.assertTrue(gpu.mux_hybrid())
        self.assertEqual(hw.power_limits(), {})
        Modes(self.cfg, lambda: None)._apply_power("balanced")

    def test_mux_nvidia_only(self):
        add_nvidia()
        w(ARM + "/dgpu_disable/current_value", 0)
        w(ARM + "/gpu_mux_mode/current_value", 0)
        self.assertEqual(gpu.kwin_env_lines(), [])
        with mock.patch.object(gpu, "holders", return_value=[]):
            with self.assertRaises(gpu.GpuError) as e:
                gpu.turn_off()
        self.assertIn("MUX", str(e.exception))

    def test_nouveau_is_not_unloaded(self):
        """NVIDIA на nouveau: Eco не трогает драйвер и шину, а объясняет, что нужно."""
        add_nvidia()
        w(ARM + "/dgpu_disable/current_value", 0)
        os.makedirs(ROOT + "/sys/bus/pci/drivers/nouveau", exist_ok=True)
        os.symlink(ROOT + "/sys/bus/pci/drivers/nouveau", ROOT + NV + "/driver")
        self.assertEqual(gpu.driver(), "nouveau")
        with mock.patch.object(gpu, "holders", return_value=[]), \
             mock.patch.object(gpu, "_remove_from_bus") as unload, \
             mock.patch.object(gpu.sysfs, "write") as write:
            with self.assertRaises(gpu.GpuError) as e:
                gpu.turn_off()
        self.assertIn("nouveau", str(e.exception))
        unload.assert_not_called()
        write.assert_not_called()

    def test_desktop_names_cut_to_15_chars(self):
        """В /proc/*/comm имя обрезано до 15 символов — защита рабочего стола должна это учитывать."""
        nobody = 2 ** 22 + 1                    # такого PID нет — защищает только имя
        for comm in ("kwin_wayland_wr", "startplasma-way", "gdm-wayland-ses", "plasma-login-gr"):
            self.assertTrue(gpu.is_protected(nobody, comm), comm)

    def test_other_compositors_protected(self):
        nobody = 2 ** 22 + 1
        for comm in ("niri", "cosmic-comp", "gamescope", "labwc", "wayfire", "river", "Hyprland", "sway"):
            self.assertTrue(gpu.is_protected(nobody, comm), comm)
        self.assertFalse(gpu.is_protected(nobody, "steam"))

    def test_greeter_system_user_protected(self):
        """Экран входа работает от системного пользователя (sddm, gdm, plasmalogin…) — его не закрываем."""
        st = mock.Mock(st_uid=957)
        with mock.patch.object(gpu.os, "stat", return_value=st):
            self.assertTrue(gpu.is_protected(4242, "some-greeter"))
        st.st_uid = 1000
        with mock.patch.object(gpu.os, "stat", return_value=st):
            self.assertFalse(gpu.is_protected(4242, "brave"))


# ---------- питание ----------
class PowerSupplyTest(Base):
    def test_usb_c_charging_counts_as_ac(self):
        d = "/sys/class/power_supply/ucsi-source-psy-USBC000:001"
        w(d + "/type", "USB")
        w(d + "/online", 1)
        self.assertTrue(hw.on_ac())
        w(d + "/online", 0)
        self.assertFalse(hw.on_ac())

    def test_peripheral_battery_ignored(self):
        rm(BAT)
        d = "/sys/class/power_supply/hidpp_battery_0"
        w(d + "/type", "Battery")
        w(d + "/scope", "Device")
        w(d + "/capacity", 40)
        self.assertIsNone(hw.battery())

    def test_peripheral_usb_device_not_ac(self):
        d = "/sys/class/power_supply/hid-controller-battery"
        w(d + "/type", "USB")
        w(d + "/scope", "Device")
        w(d + "/online", 1)
        self.assertFalse(hw.on_ac())

    def test_power_now_battery(self):
        rm(BAT + "/current_now")
        w(BAT + "/power_now", 21500000)
        self.assertEqual(hw.battery()["power_w"], 21.5)

    def test_energy_based_health(self):
        rm(BAT + "/charge_full")
        rm(BAT + "/charge_full_design")
        w(BAT + "/energy_full", 60000000)
        w(BAT + "/energy_full_design", 75000000)
        self.assertEqual(hw.battery()["health"], 80)

    def test_no_charge_limit(self):
        rm(BAT + "/charge_control_end_threshold")
        self.assertIsNone(hw.battery()["charge_limit"])
        self.assertFalse(hw.set_charge_limit(80))


# ---------- подсветка ----------
class KeyboardTest(Base):
    def test_no_backlight_at_all(self):
        rm("/sys/class/leds/asus::kbd_backlight")
        rm("/sys/class/hidraw/hidraw0")
        self.assertIsNone(aura.brightness())
        self.assertIsNone(aura.rgb_method())
        self.assertFalse(aura.apply({"mode": "static", "color": "#FFFFFF", "speed": "normal",
                                     "awake": True, "boot": False, "sleep": False, "shutdown": False}))

    def test_hidraw_numeric_order(self):
        for n in (2, 10):
            h = f"hidraw{n}"
            w(f"/sys/class/hidraw/{h}/device/uevent", "HID_ID=0003:00000B05:00001866")
            with open(f"{ROOT}/sys/class/hidraw/{h}/device/report_descriptor", "wb") as f:
                f.write(bytes([0x85, 0x5A, 0x75, 0x08, 0x95, 16, 0xB1, 0x00]))
        self.assertEqual([d["dev"] for d in hid.devices()],
                         ["/dev/hidraw0", "/dev/hidraw1", "/dev/hidraw2", "/dev/hidraw10"])

    def test_non_asus_hid_ignored(self):
        w("/sys/class/hidraw/hidraw0/device/uevent", "HID_ID=0003:0000046D:0000C52B")   # Logitech
        self.assertNotIn("/dev/hidraw0", [d["dev"] for d in hid.devices()])

    def test_slash_long_model(self):
        w("/sys/class/dmi/id/product_name", "ROG Zephyrus G14 GA405UV_GA405UV")
        self.assertEqual(slash.segments(), 35)
        w("/sys/class/dmi/id/product_name", "ROG Zephyrus G16 GU605MZ_GU605MZ")
        self.assertEqual(slash.segments(), 7)


# ---------- настройки ----------
class ConfigTest(unittest.TestCase):
    def load(self, text):
        p = os.path.join(CONF, "cfg-test.json")
        with open(p, "w") as f:
            f.write(text)
        return Config(p).load()

    def test_broken_json(self):
        self.assertEqual(self.load("{").data["profile_on_ac"], "balanced")

    def test_not_a_dict(self):
        self.assertEqual(self.load("[]").data["profile_on_ac"], "balanced")

    def test_wrong_nested_type(self):
        c = self.load(json.dumps({"profiles": [], "keyboard": "x", "charge_limit": 80}))
        self.assertEqual(set(c.data["profiles"]), {"quiet", "balanced", "performance"})
        self.assertIsInstance(c.data["keyboard"], dict)
        self.assertEqual(c.data["charge_limit"], 80)

    def test_unknown_profile_name(self):
        c = self.load(json.dumps({"profile_on_ac": "turbo"}))
        self.assertEqual(c.profile_for(True), "balanced")

    def test_old_config_gets_new_keys_and_keeps_unknown(self):
        c = self.load(json.dumps({"version": 1, "charge_limit": 60, "my_note": "x"}))
        self.assertEqual(c.data["charge_limit"], 60)
        self.assertIn("slash", c.data)
        self.assertEqual(c.data["my_note"], "x")


# ---------- power-profiles-daemon ----------
class PpdTest(unittest.TestCase):
    """Игры и KDE просят режим через power-profiles-daemon: удержания и их снятие."""

    def setUp(self):
        fakesys.build(ROOT)
        from asushelper.daemon import ppd
        self.ppd_mod = ppd
        self.set = []
        svc = mock.Mock()
        svc.listeners = []
        svc.modes.current = "balanced"

        def set_profile(p, remember=True):
            self.set.append(p)
            svc.modes.current = p
        svc.modes.set_profile = set_profile
        self.p = ppd.PowerProfiles(new_bus(), svc)

    def call(self, method, *args):
        inv = mock.Mock()
        self.p._on_call(None, ":1.5", "/", "net.hadess.PowerProfiles", method, GLib.Variant(
            {"HoldProfile": "(sss)", "ReleaseProfile": "(u)"}[method], args), inv)
        return inv

    def test_hold_and_release(self):
        inv = self.call("HoldProfile", "performance", "game", "steam")
        cookie = inv.return_value.call_args[0][0].unpack()[0]
        self.assertEqual(self.set, ["performance"])
        self.call("ReleaseProfile", cookie)
        self.assertEqual(self.set, ["performance", "balanced"])

    def test_power_saver_wins(self):
        self.call("HoldProfile", "performance", "game", "steam")
        self.call("HoldProfile", "power-saver", "low battery", "kde")
        self.assertEqual(self.set[-1], "quiet")

    def test_holder_exit_releases(self):
        self.call("HoldProfile", "performance", "game", "steam")
        self.p._on_name_owner(None, None, None, None, None, GLib.Variant("(sss)", (":1.5", ":1.5", "")))
        self.assertEqual(self.set[-1], "balanced")
        self.assertEqual(self.p.holds, {})

    def test_bad_hold_rejected(self):
        inv = self.call("HoldProfile", "balanced", "x", "y")
        inv.return_dbus_error.assert_called_once()
        self.assertEqual(self.set, [])


if __name__ == "__main__":
    unittest.main()


# ---------- зависания драйвера NVIDIA в ядре ----------
class KernelHangTest(Base):
    """Шаг, зависший внутри ядра, не убить — демон не должен висеть вместе с ним и не переключает до перезагрузки."""

    def tearDown(self):
        gpu.stuck = None
        gpu._changed_at = None        # иначе следующий тест ждал бы паузу между переключениями

    def hung_popen(self):
        import subprocess
        p = mock.Mock(pid=4242)
        p.wait.side_effect = subprocess.TimeoutExpired("x", 1)
        p.poll.return_value = None
        return p

    def test_driver_load_has_timeout(self):
        """modprobe nvidia завис (как при подключении зарядки) — не «переключается» вечно, а сообщает."""
        with mock.patch.object(gpu.subprocess, "Popen", return_value=self.hung_popen()):
            with self.assertRaises(gpu.GpuError) as e:
                gpu._load_driver()
        self.assertIn("перезагрузка", str(e.exception))
        self.assertTrue(gpu.is_stuck())

    def test_sysfs_write_has_timeout(self):
        """Запись в remove/dgpu_disable тоже делает дочерний процесс — завис он, а не демон."""
        with mock.patch.object(gpu.sysfs, "ROOT", ""), \
             mock.patch.object(gpu.subprocess, "Popen", return_value=self.hung_popen()) as popen:
            with self.assertRaises(gpu.GpuError):
                gpu._write("/sys/bus/pci/devices/0000:01:00.0/remove", 1)
        self.assertEqual(popen.call_args[0][0][:2], ["sh", "-c"])
        self.assertTrue(gpu.is_stuck())

    def test_no_new_switch_while_stuck(self):
        gpu.stuck = self.hung_popen()
        sw = gpu.Switcher(lambda err: None)
        self.assertFalse(sw.start(True))

    def test_stuck_clears_when_process_finishes(self):
        p = self.hung_popen()
        gpu.stuck = p
        self.assertTrue(gpu.is_stuck())
        p.poll.return_value = 0                           # ядро отвисло само
        self.assertFalse(gpu.is_stuck())


class CleanupTest(Base):
    """Уборка до переключения: программы на NVIDIA закрываются (TERM, потом KILL), рабочий стол — никогда."""

    APP, STUBBORN = 2 ** 22 + 7, 2 ** 22 + 8

    def test_term_then_kill(self):
        held = [(self.APP, "game"), (self.STUBBORN, "stubborn"), (900, "kwin_wayland")]
        sent = []

        def kill(pid, sig):
            sent.append((pid, sig))
            if pid == self.APP or sig == gpu.signal.SIGKILL:
                held[:] = [h for h in held if h[0] != pid]
        with mock.patch.object(gpu, "holders", side_effect=lambda g=None: list(held)), \
             mock.patch.object(gpu.os, "kill", side_effect=kill), \
             mock.patch.object(gpu.time, "sleep"):
            gpu._close("0000:01:00.0")
        self.assertEqual(sent, [(self.APP, gpu.signal.SIGTERM), (self.STUBBORN, gpu.signal.SIGTERM),
                                (self.STUBBORN, gpu.signal.SIGKILL)])
        self.assertEqual(held, [(900, "kwin_wayland")])     # рабочий стол не тронут

    def test_turn_on_cleans_first(self):
        w(ARM + "/dgpu_disable/current_value", 1)
        with mock.patch.object(gpu, "_cleanup") as cleanup, \
             mock.patch.object(gpu, "_rescan", return_value=None), \
             mock.patch.object(gpu.time, "sleep"):
            with self.assertRaises(gpu.GpuError):
                gpu.turn_on()                                 # карта в поддельной системе не появится
        cleanup.assert_called_once()
        self.assertEqual(read(ARM + "/dgpu_disable/current_value"), "0")


class AutoSettleTest(Base):
    """«Авто» переключает не в момент подключения зарядки, а когда события питания закончились."""

    def setUp(self):
        super().setUp()
        from asushelper.daemon import service as svc
        add_nvidia()
        w(ARM + "/dgpu_disable/current_value", 1)
        self.cfg.data["gpu"]["auto_eco"] = True
        self.s = svc.Service(new_bus(), self.cfg)
        self.started = []
        self.s.gpu.start = lambda want_off, *a, **k: self.started.append(want_off) or True
        self.s.modes.ac = False
        self.s.AUTO_SETTLE_S = 1

    def tearDown(self):
        if self.s._auto_settle:
            GLib.source_remove(self.s._auto_settle)

    def test_charger_switch_is_delayed(self):
        with mock.patch.object(self.s.modes, "power_source_changed",
                               side_effect=lambda ac: setattr(self.s.modes, "ac", ac)):
            self.s.power_source_changed(True)
        self.assertEqual(self.started, [])                 # не в ту же секунду
        run_loop(2300)   # timeout_add_seconds срабатывает с точностью до секунды
        self.assertEqual(self.started, [False])            # через паузу — включить NVIDIA

    def test_unplugged_again_during_pause(self):
        with mock.patch.object(self.s.modes, "power_source_changed",
                               side_effect=lambda ac: setattr(self.s.modes, "ac", ac)):
            self.s.power_source_changed(True)
            self.s.power_source_changed(False)             # передумали — снова батарея
        run_loop(2300)   # timeout_add_seconds срабатывает с точностью до секунды
        self.assertEqual(self.started, [])                 # карта и так выключена — ничего не делаем
