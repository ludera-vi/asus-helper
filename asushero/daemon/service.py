"""D-Bus API демона: org.asushero.Daemon на системной шине.

Сложные данные (состояние, настройки) передаются строкой JSON: так их одинаково легко читать
из QML, Python и busctl. Методы, которые что-то меняют, проверяют право через polkit
(действие org.asushero.manage: активному пользователю — без пароля).
"""
import json
import logging

from gi.repository import Gio, GLib

from .. import BUS_NAME, FANS, INTERFACE, OBJECT_PATH, PROFILES, __version__
from . import hardware as hw
from .config import Config
from .modes import Modes

log = logging.getLogger(__name__)

POLKIT_ACTION = "org.asushero.manage"
# False только при разработке на сессионной шине (там нет polkit)
USE_POLKIT = True
ERROR = "org.asushero.Error"

XML = f"""
<node>
  <interface name="{INTERFACE}">
    <method name="GetState"><arg type="s" direction="out" name="json"/></method>
    <method name="GetConfig"><arg type="s" direction="out" name="json"/></method>
    <method name="SetProfile"><arg type="s" direction="in" name="profile"/></method>
    <method name="CycleProfile"><arg type="s" direction="out" name="profile"/></method>
    <method name="SetAutoProfile"><arg type="b" direction="in" name="enabled"/></method>
    <method name="SetChargeLimit"><arg type="u" direction="in" name="percent"/></method>
    <method name="SetEpp">
      <arg type="s" direction="in" name="profile"/><arg type="s" direction="in" name="epp"/>
    </method>
    <method name="SetFanCurve">
      <arg type="s" direction="in" name="profile"/><arg type="s" direction="in" name="fan"/>
      <arg type="ai" direction="in" name="temp"/><arg type="ai" direction="in" name="pwm"/>
    </method>
    <method name="ResetFanCurve">
      <arg type="s" direction="in" name="profile"/><arg type="s" direction="in" name="fan"/>
    </method>
    <method name="GetFactoryFanCurves"><arg type="s" direction="out" name="json"/></method>
    <method name="SetPowerLimit">
      <arg type="s" direction="in" name="profile"/><arg type="s" direction="in" name="attr"/>
      <arg type="i" direction="in" name="value"/>
    </method>
    <method name="ResetPowerLimits"><arg type="s" direction="in" name="profile"/></method>
    <signal name="StateChanged"><arg type="s" name="json"/></signal>
    <property name="Profile" type="s" access="read"/>
    <property name="Version" type="s" access="read"/>
  </interface>
</node>
"""

# Методы, которые только читают — без polkit
READ_ONLY = {"GetState", "GetConfig"}


class Failed(Exception):
    """Ошибка для клиента: текст уходит ему как org.asushero.Error.Failed."""


class Service:
    def __init__(self, bus: Gio.DBusConnection, config: Config):
        self.bus = bus
        self.config = config
        self.listeners = []   # другие интерфейсы (эмуляция PPD) — тоже хотят знать о смене режима
        self.modes = Modes(config, self._changed)
        self._last_profile = None
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        bus.register_object(OBJECT_PATH, node.interfaces[0], self._on_call, self._on_get_property, None)

    # ---------- состояние ----------
    def state(self) -> dict:
        return {
            "version": __version__,
            "profile": self.modes.current,
            "profiles": [p for p in PROFILES if p in hw.profile_choices()],
            "ac": self.modes.ac,
            "auto_profile": self.config.data["auto_profile"],
            "profile_on_ac": self.config.data["profile_on_ac"],
            "profile_on_battery": self.config.data["profile_on_battery"],
            "epp": hw.epp(),
            "epp_choices": hw.epp_choices(),
            "fans": hw.fan_rpm(),
            "fan_curves": {f: hw.fan_curve(f) for f in FANS} if hw.has_fan_curves() else None,
            "cpu_temp": hw.cpu_temp(),
            "battery": hw.battery(),
            "power_limits": hw.power_limits(),
        }

    def _changed(self) -> None:
        """Режим или настройки изменились — оповестить подписчиков."""
        self.bus.emit_signal(None, OBJECT_PATH, INTERFACE, "StateChanged",
                             GLib.Variant("(s)", (json.dumps(self.state()),)))
        if self.modes.current != self._last_profile:
            self._last_profile = self.modes.current
            self.bus.emit_signal(None, OBJECT_PATH, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                 GLib.Variant("(sa{sv}as)", (INTERFACE, {"Profile": GLib.Variant("s", self.modes.current or "")}, [])))
            for fn in self.listeners:
                fn(self.modes.current)

    # ---------- вызовы ----------
    def _on_get_property(self, _conn, _sender, _path, _iface, name):
        if name == "Profile":
            return GLib.Variant("s", self.modes.current or "")
        if name == "Version":
            return GLib.Variant("s", __version__)
        return None

    def _on_call(self, _conn, sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method in READ_ONLY:
            self._dispatch(method, args, invocation)
        else:
            authorize(self.bus, sender, POLKIT_ACTION,
                      lambda ok: self._dispatch(method, args, invocation) if ok
                      else invocation.return_dbus_error(ERROR + ".NotAuthorized", "нет прав (polkit)"))

    def _dispatch(self, method, args, invocation):
        try:
            result = getattr(self, "do_" + method)(*args)
        except Failed as e:
            invocation.return_dbus_error(ERROR + ".Failed", str(e))
            return
        except Exception as e:  # демон не должен падать из-за одного неудачного вызова
            log.exception("%s%s", method, args)
            invocation.return_dbus_error(ERROR + ".Failed", f"внутренняя ошибка: {e}")
            return
        invocation.return_value(None if result is None else GLib.Variant("(s)", (result,)))

    # ---------- методы ----------
    def do_GetState(self):
        return json.dumps(self.state())

    def do_GetConfig(self):
        return json.dumps(self.config.data)

    def do_SetProfile(self, profile):
        check_profile(profile)
        self.modes.set_profile(profile)

    def do_CycleProfile(self):
        return self.modes.cycle_profile()

    def do_SetAutoProfile(self, enabled):
        self.config.data["auto_profile"] = bool(enabled)
        self.config.save()
        self._changed()

    def do_SetChargeLimit(self, percent):
        if not 20 <= percent <= 100:
            raise Failed("лимит заряда — от 20 до 100 %")
        if not hw.set_charge_limit(percent):
            raise Failed("ядро не приняло лимит заряда")
        self.config.data["charge_limit"] = percent
        self.config.save()
        self._changed()

    def do_SetEpp(self, profile, epp):
        check_profile(profile)
        if epp and epp not in hw.epp_choices():
            raise Failed(f"EPP «{epp}» не поддерживается: {' '.join(hw.epp_choices())}")
        self.config.profile(profile)["epp"] = epp or None
        self._save_and_reapply(profile)

    def do_SetFanCurve(self, profile, fan, temp, pwm):
        check_profile(profile)
        check_fan(fan)
        if err := hw.validate_curve(list(temp), list(pwm)):
            raise Failed(err)
        self.config.profile(profile)["fan_curves"][fan] = {"enabled": True, "temp": list(temp), "pwm": list(pwm)}
        self._save_and_reapply(profile)

    def do_ResetFanCurve(self, profile, fan):
        check_profile(profile)
        check_fan(fan)
        self.config.profile(profile)["fan_curves"][fan] = None
        self._save_and_reapply(profile)

    def do_GetFactoryFanCurves(self):
        """Заводские кривые BIOS для текущего режима — чтобы приложение показало их как отправную точку."""
        if not hw.has_fan_curves():
            raise Failed("ядро не поддерживает свои кривые вентиляторов")
        curves = {f: hw.factory_fan_curve(f) for f in FANS}
        self.modes.reapply("после чтения заводских кривых")   # вернуть свои кривые, если были
        return json.dumps({"profile": self.modes.current, "curves": curves})

    def do_SetPowerLimit(self, profile, attr, value):
        check_profile(profile)
        if attr not in hw.POWER_ATTRS:
            raise Failed(f"неизвестный параметр «{attr}»")
        if hw.armoury_attr(attr) is None:
            raise Failed(f"параметра «{attr}» нет на этом ноутбуке")
        limits = self.config.profile(profile)["power_limits"]
        if value < 0:
            limits.pop(attr, None)     # -1 — вернуть управление BIOS
        else:
            limits[attr] = value
        self._save_and_reapply(profile)

    def do_ResetPowerLimits(self, profile):
        check_profile(profile)
        self.config.profile(profile)["power_limits"] = {}
        self.config.save()
        if profile == self.modes.current:
            # BIOS возвращает свои лимиты только при смене режима
            self.modes.set_profile("balanced" if profile != "balanced" else "quiet", remember=False)
            self.modes.set_profile(profile, remember=False)
        self._changed()

    def _save_and_reapply(self, profile):
        self.config.save()
        if profile == self.modes.current:
            self.modes.reapply(f"изменены настройки режима {profile}")
        else:
            self._changed()


def check_profile(p):
    if p not in PROFILES:
        raise Failed(f"неизвестный режим «{p}» (есть: {', '.join(PROFILES)})")


def check_fan(f):
    if f not in FANS:
        raise Failed(f"неизвестный вентилятор «{f}» (есть: {', '.join(FANS)})")


def authorize(bus: Gio.DBusConnection, sender: str, action: str, done) -> None:
    """Асинхронно спрашивает polkit, можно ли sender выполнить action; done(bool)."""
    if not USE_POLKIT:
        done(True)
        return
    subject = ("system-bus-name", {"name": GLib.Variant("s", sender)})

    def finish(conn, res):
        try:
            ok = conn.call_finish(res).unpack()[0][0]
        except GLib.Error as e:
            log.warning("polkit недоступен: %s", e.message)
            ok = False
        done(ok)

    bus.call("org.freedesktop.PolicyKit1", "/org/freedesktop/PolicyKit1/Authority",
             "org.freedesktop.PolicyKit1.Authority", "CheckAuthorization",
             GLib.Variant("((sa{sv})sa{ss}us)", (subject, action, {}, 1, "")),
             GLib.VariantType("((bba{ss}))"), Gio.DBusCallFlags.NONE, -1, None, finish)
