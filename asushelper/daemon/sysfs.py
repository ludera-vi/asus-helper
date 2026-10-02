"""Чтение и запись файлов sysfs.

Все пути проходят через path(): переменная окружения ASUSHELPER_SYSROOT подменяет корень,
чтобы тесты работали на поддельном дереве sysfs, не трогая железо.
"""
import glob
import logging
import os

log = logging.getLogger(__name__)

ROOT = os.environ.get("ASUSHELPER_SYSROOT", "")


def path(p: str) -> str:
    return ROOT + p


def exists(p: str) -> bool:
    return os.path.exists(path(p))


def read(p: str, default: str | None = None) -> str | None:
    try:
        with open(path(p)) as f:
            return f.read().strip()
    except OSError:
        return default


def read_int(p: str, default: int | None = None) -> int | None:
    v = read(p)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


def write(p: str, value) -> bool:
    """Пишет значение; False и запись в журнал, если ядро отказало."""
    try:
        with open(path(p), "w") as f:
            f.write(str(value))
        return True
    except OSError as e:
        log.warning("запись %s = %s не удалась: %s", p, value, e)
        return False


def find(pattern: str) -> list[str]:
    """glob по дереву sysfs; возвращает пути без префикса ROOT."""
    return sorted(m[len(ROOT):] for m in glob.glob(path(pattern)))


def hwmon(name: str) -> str | None:
    """Каталог hwmon с заданным name, например «asus_custom_fan_curve»."""
    for d in find("/sys/class/hwmon/hwmon*"):
        if read(d + "/name") == name:
            return d
    return None
