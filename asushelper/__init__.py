"""Asus-helper — управление ноутбуком ASUS ROG в Linux (замена asusd / rog-control-center)."""

__version__ = "0.1.0"

PROFILES = ("quiet", "balanced", "performance")
FANS = ("cpu", "gpu", "mid")   # какие есть у ноутбука — hardware.fans() / curve_fans()

# D-Bus
BUS_NAME = "org.asushelper.Daemon"
OBJECT_PATH = "/org/asushelper/Daemon"
INTERFACE = "org.asushelper.Daemon1"
