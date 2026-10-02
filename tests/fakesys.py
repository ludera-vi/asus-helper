"""Поддельное дерево sysfs, похожее на GU605MZ (значения сняты с настоящего ноутбука)."""
import os


def _w(root, p, v):
    full = root + p
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(f"{v}\n")


def build(root: str, ac: bool = False) -> None:
    _w(root, "/sys/firmware/acpi/platform_profile", "quiet")
    _w(root, "/sys/firmware/acpi/platform_profile_choices", "quiet balanced performance")

    for cpu in range(4):
        d = f"/sys/devices/system/cpu/cpu{cpu}/cpufreq"
        _w(root, d + "/energy_performance_preference", "power")
        _w(root, d + "/energy_performance_available_preferences",
           "default performance balance_performance balance_power power")

    a = "/sys/class/firmware-attributes/asus-armoury/attributes"
    for name, cur, lo, hi, df in [("ppt_pl1_spl", 35, 25, 35, 35), ("ppt_pl2_sppt", 53, 38, 53, 53),
                                  ("nv_temp_target", 87, 75, 87, 87), ("nv_dynamic_boost", 0, 0, 0, 0)]:
        _w(root, f"{a}/{name}/current_value", cur)
        _w(root, f"{a}/{name}/min_value", lo)
        _w(root, f"{a}/{name}/max_value", hi)
        _w(root, f"{a}/{name}/default_value", df)
    _w(root, f"{a}/dgpu_disable/current_value", 1)
    _w(root, f"{a}/gpu_mux_mode/current_value", 1)
    _w(root, f"{a}/panel_overdrive/current_value", 1)

    _w(root, "/sys/class/hwmon/hwmon6/name", "asus")
    _w(root, "/sys/class/hwmon/hwmon6/fan1_input", 1900)
    _w(root, "/sys/class/hwmon/hwmon6/fan2_input", 1800)
    c = "/sys/class/hwmon/hwmon7"
    _w(root, c + "/name", "asus_custom_fan_curve")
    for i in (1, 2):
        _w(root, f"{c}/pwm{i}_enable", 2)
        for p in range(1, 9):
            _w(root, f"{c}/pwm{i}_auto_point{p}_temp", 30 + p * 7)
            _w(root, f"{c}/pwm{i}_auto_point{p}_pwm", p * 25)
    _w(root, "/sys/class/hwmon/hwmon9/name", "coretemp")
    _w(root, "/sys/class/hwmon/hwmon9/temp1_label", "Package id 0")
    _w(root, "/sys/class/hwmon/hwmon9/temp1_input", 52000)

    _w(root, "/sys/class/power_supply/ACAD/type", "Mains")
    _w(root, "/sys/class/power_supply/ACAD/online", 1 if ac else 0)
    b = "/sys/class/power_supply/BAT1"
    for k, v in {"type": "Battery", "capacity": 74, "status": "Discharging", "current_now": 1000000,
                 "voltage_now": 16000000, "charge_full": 4641000, "charge_full_design": 5650000,
                 "charge_control_end_threshold": 100}.items():
        _w(root, f"{b}/{k}", v)


    led = "/sys/class/leds/asus::kbd_backlight"
    _w(root, led + "/brightness", 2)
    _w(root, led + "/max_brightness", 3)
    _w(root, "/sys/class/hidraw/hidraw0/device/uevent", "HID_ID=0003:00000B05:000019B6\nHID_NAME=ITE")
    _w(root, "/sys/class/hidraw/hidraw1/device/uevent", "HID_ID=0003:00000B05:0000193B")
    _w(root, "/dev/hidraw0", "")
    os.makedirs(root + "/sys/bus/pci/devices/0000:00:02.0", exist_ok=True)
    _w(root, "/sys/bus/pci/devices/0000:00:02.0/vendor", "0x8086")
    _w(root, "/sys/bus/pci/devices/0000:00:02.0/class", "0x030000")


def read(root: str, p: str) -> str:
    with open(root + p) as f:
        return f.read().strip()
