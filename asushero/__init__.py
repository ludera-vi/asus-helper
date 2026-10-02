"""asushero — управление ноутбуком ASUS ROG в Linux (замена asusd / rog-control-center)."""

__version__ = "0.1.0"

PROFILES = ("quiet", "balanced", "performance")
FANS = ("cpu", "gpu")

# D-Bus
BUS_NAME = "org.asushero.Daemon"
OBJECT_PATH = "/org/asushero/Daemon"
INTERFACE = "org.asushero.Daemon1"
