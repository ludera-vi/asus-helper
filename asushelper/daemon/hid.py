"""Поиск HID-устройств ASUS и их feature-отчётов (по дескриптору отчётов из sysfs).

Нужен, чтобы не держать списки моделей: клавиатура Aura — это устройство ASUS с feature-отчётом 0x5d,
полоса Slash — с отчётом 0x5e (или 0x5d длиной ≥ 128 на новых моделях), как определяет G-Helper.
"""
import os

from . import sysfs

ASUS_VENDOR = 0x0B05


def feature_lengths(descriptor: bytes) -> dict[int, int]:
    """{id отчёта: длина feature-отчёта в байтах без id} — разбор коротких элементов дескриптора HID."""
    out: dict[int, int] = {}
    report_id = 0
    size = count = 0
    i = 0
    while i < len(descriptor):
        prefix = descriptor[i]
        if prefix == 0xFE:                      # длинный элемент — пропускаем
            i += 3 + (descriptor[i + 1] if i + 1 < len(descriptor) else 0)
            continue
        n = (0, 1, 2, 4)[prefix & 0x03]
        data = int.from_bytes(descriptor[i + 1:i + 1 + n], "little")
        tag_type = prefix & 0xFC
        if tag_type == 0x84:                    # Report ID
            report_id = data
        elif tag_type == 0x74:                  # Report Size (бит)
            size = data
        elif tag_type == 0x94:                  # Report Count
            count = data
        elif tag_type == 0xB0:                  # Feature
            out[report_id] = out.get(report_id, 0) + size * count // 8
        i += 1 + n
    return out


def devices() -> list[dict]:
    """Все hidraw-устройства ASUS: [{dev, product, features: {id: длина}}]."""
    out = []
    for h in sysfs.find("/sys/class/hidraw/hidraw*"):
        uevent = sysfs.read(h + "/device/uevent") or ""
        hid_id = next((line.split("=", 1)[1] for line in uevent.splitlines() if line.startswith("HID_ID=")), "")
        parts = hid_id.split(":")
        if len(parts) != 3 or int(parts[1], 16) != ASUS_VENDOR:
            continue
        try:
            with open(sysfs.path(h + "/device/report_descriptor"), "rb") as f:
                features = feature_lengths(f.read())
        except OSError:
            features = {}
        out.append({"dev": "/dev/" + os.path.basename(h), "product": int(parts[2], 16), "features": features})
    return out


def find(report: int, min_len: int = 1) -> dict | None:
    """Первое устройство ASUS с feature-отчётом report длиной не меньше min_len."""
    for d in devices():
        if d["features"].get(report, 0) >= min_len:
            return d
    return None
