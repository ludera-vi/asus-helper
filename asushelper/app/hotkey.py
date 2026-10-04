"""Клавиша, которая открывает окно: регистрируется в KDE (KGlobalAccel) или GNOME (gsettings) самой программой.

Клавиша ROG / Armoury Crate на ноутбуках ASUS приходит как KEY_PROG1 (так её отображают драйверы
hid-asus и asus-wmi), в KDE это «Launch (1)». Есть ли такая кнопка физически, Linux не знает —
знает только, объявляет ли устройство ASUS этот код. Если объявляет — назначаем; если нет — действие
«Открыть Asus-helper» всё равно появляется в «Настройки → Комбинации клавиш», и его можно повесить на
любую клавишу. Назначенное пользователем KDE запоминает и при следующем запуске не трогаем.
"""
import logging

from gi.repository import Gio, GLib

from ..i18n import _

log = logging.getLogger(__name__)

COMPONENT, ACTION = "asus-helper", "toggle"
KEY_PROG1 = 148
QT_KEY_LAUNCH1 = 0x010000A3
# флаги KGlobalAccel::setShortcutKeys
SET_PRESENT, IS_DEFAULT = 2, 8
KGA = ("org.kde.kglobalaccel", "/kglobalaccel", "org.kde.KGlobalAccel")


def _keys_of(block: str) -> int:
    words = next((l.split("=", 1)[1].split() for l in block.splitlines() if l.startswith("B: KEY=")), [])
    bits = 0
    for i, w in enumerate(reversed(words)):
        bits |= int(w, 16) << (64 * i)
    return bits


def rog_key() -> int | None:
    """Qt-код клавиши ROG, если устройство ASUS её объявляет, иначе None."""
    try:
        with open("/proc/bus/input/devices") as f:
            blocks = f.read().split("\n\n")
    except OSError:
        return None
    for b in blocks:
        ident = next((l for l in b.splitlines() if l.startswith("I:")), "")
        name = next((l for l in b.splitlines() if l.startswith("N:")), "").lower()
        if "vendor=0b05" in ident.lower() or "asus" in name:
            if _keys_of(b) >> KEY_PROG1 & 1:
                return QT_KEY_LAUNCH1
    return None


class GlobalShortcut:
    def __init__(self, session: Gio.DBusConnection, on_pressed):
        self.bus = session
        self.on_pressed = on_pressed
        try:
            self._register()
        except GLib.Error as e:
            log.info(_("горячая клавиша не зарегистрирована (нет KDE?): %s"), e.message)

    def _call(self, method, sig, *args):
        return self.bus.call_sync(*KGA, method, GLib.Variant(f"({sig})", args), None,
                                  Gio.DBusCallFlags.NO_AUTO_START, 3000, None)

    def _register(self):
        # прежние версии вешали клавишу через ярлык (X-KDE-Shortcuts) — убираем, иначе две привязки
        try:
            self._call("unregister", "ss", "asus-helper.desktop", "_launch")
        except GLib.Error:
            pass
        action = [COMPONENT, ACTION, "Asus-helper", _("Открыть Asus-helper")]
        self._call("doRegister", "as", action)
        key = rog_key()
        keys = [([key],)] if key else []
        self._call("setShortcutKeys", "asa(ai)u", action, keys, IS_DEFAULT)
        # SET_PRESENT без NoAutoloading: если пользователь уже назначил свою клавишу — KDE вернёт её
        got = self._call("setShortcutKeys", "asa(ai)u", action, keys, SET_PRESENT).unpack()[0]
        path = self._call("getComponent", "s", COMPONENT).unpack()[0]
        self.bus.signal_subscribe(KGA[0], "org.kde.kglobalaccel.Component", "globalShortcutPressed", path, None,
                                  Gio.DBusSignalFlags.NONE, self._on_signal)
        codes = [k for (combo,) in got for k in combo if k]
        log.info(_("клавиша окна: %s"), ", ".join(hex(k) for k in codes) or _("не назначена"))

    def _on_signal(self, _c, _s, _p, _i, _sig, params):
        component, action, _ts = params.unpack()
        if component == COMPONENT and action == ACTION:
            self.on_pressed()


# GNOME: своя комбинация в «Настройки → Клавиатура → Свои комбинации клавиш» — команда asus-helper
# (второй запуск открывает окно уже запущенной программы). Клавиша ROG там называется XF86Launch1.
# Комбинацию создаём один раз; если человек её изменил или удалил клавишу — больше не трогаем.
GNOME_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_PATH = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/asus-helper/"


def gnome_shortcut() -> None:
    import shutil
    src = Gio.SettingsSchemaSource.get_default()
    if not src or not src.lookup(GNOME_KEYS, True) or not src.lookup(GNOME_KEYS + ".custom-keybinding", True):
        return
    keys = Gio.Settings.new(GNOME_KEYS)
    paths = keys.get_strv("custom-keybindings")
    if GNOME_PATH in paths:
        return
    entry = Gio.Settings.new_with_path(GNOME_KEYS + ".custom-keybinding", GNOME_PATH)
    entry.set_string("name", _("Открыть Asus-helper"))
    entry.set_string("command", shutil.which("asus-helper") or "asus-helper")
    entry.set_string("binding", "XF86Launch1" if rog_key() else "")
    keys.set_strv("custom-keybindings", paths + [GNOME_PATH])
    Gio.Settings.sync()
    log.info(_("клавиша окна: %s"), "XF86Launch1" if rog_key() else _("не назначена"))
