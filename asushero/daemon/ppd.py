"""Эмуляция power-profiles-daemon для KDE.

KDE (PowerDevil, виджет батареи) знает о режимах только через power-profiles-daemon.
Демон отвечает на его имена net.hadess.PowerProfiles и org.freedesktop.UPower.PowerProfiles,
поэтому переключатель режима в виджете батареи и карточка при смене режима работают сами.
Сам power-profiles-daemon при этом должен быть выключен (он замаскирован в системе).

Режимы: quiet ↔ power-saver, balanced ↔ balanced, performance ↔ performance.
"""
import logging

from gi.repository import Gio, GLib

from .service import POLKIT_ACTION, Service, authorize

log = logging.getLogger(__name__)

TO_PPD = {"quiet": "power-saver", "balanced": "balanced", "performance": "performance"}
FROM_PPD = {v: k for k, v in TO_PPD.items()}

# Совместим с power-profiles-daemon 0.30
NAMES = [
    ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles"),
    ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles"),
]


def xml(iface: str) -> str:
    return f"""
<node>
  <interface name="{iface}">
    <method name="HoldProfile">
      <arg type="s" direction="in" name="profile"/><arg type="s" direction="in" name="reason"/>
      <arg type="s" direction="in" name="application_id"/><arg type="u" direction="out" name="cookie"/>
    </method>
    <method name="ReleaseProfile"><arg type="u" direction="in" name="cookie"/></method>
    <method name="SetActionEnabled">
      <arg type="s" direction="in" name="action"/><arg type="b" direction="in" name="enabled"/>
    </method>
    <signal name="ProfileReleased"><arg type="u" name="cookie"/></signal>
    <property name="ActiveProfile" type="s" access="readwrite"/>
    <property name="PerformanceInhibited" type="s" access="read"/>
    <property name="PerformanceDegraded" type="s" access="read"/>
    <property name="Profiles" type="aa{{sv}}" access="read"/>
    <property name="Actions" type="as" access="read"/>
    <property name="ActionsInfo" type="aa{{sv}}" access="read"/>
    <property name="ActiveProfileHolds" type="aa{{sv}}" access="read"/>
    <property name="Version" type="s" access="read"/>
    <property name="BatteryAware" type="b" access="readwrite"/>
  </interface>
</node>"""


class PowerProfiles:
    def __init__(self, bus: Gio.DBusConnection, service: Service):
        self.bus = bus
        self.service = service
        # Удержания режима (например, игра просит performance). cookie → {profile, reason, app, sender}
        self.holds: dict[int, dict] = {}
        self.next_cookie = 1
        self.before_hold: str | None = None
        for name, path in NAMES:
            iface = name
            node = Gio.DBusNodeInfo.new_for_xml(xml(iface))
            bus.register_object(path, node.interfaces[0], self._on_call, self._on_get, self._on_set)
        service.listeners.append(self._profile_changed)
        # программа, державшая режим, закрылась — снять её удержания
        bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                             "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self._on_name_owner)

    def own_names(self) -> None:
        for name, _ in NAMES:
            Gio.bus_own_name_on_connection(self.bus, name, Gio.BusNameOwnerFlags.NONE,
                                           lambda _c, n: log.info("KDE видит режимы через %s", n),
                                           lambda _c, n: log.warning("имя %s занято — работает power-profiles-daemon?", n))

    # ---------- свойства ----------
    def active(self) -> str:
        return TO_PPD.get(self.service.modes.current or "", "balanced")

    def _props(self) -> dict:
        profiles = [{"Profile": GLib.Variant("s", TO_PPD[p]), "Driver": GLib.Variant("s", "asushero"),
                     "PlatformDriver": GLib.Variant("s", "asushero"), "CpuDriver": GLib.Variant("s", "intel_pstate")}
                    for p in ("quiet", "balanced", "performance")]
        holds = [{"Profile": GLib.Variant("s", h["profile"]), "Reason": GLib.Variant("s", h["reason"]),
                  "ApplicationId": GLib.Variant("s", h["app"])} for h in self.holds.values()]
        return {
            "ActiveProfile": GLib.Variant("s", self.active()),
            "PerformanceInhibited": GLib.Variant("s", ""),
            "PerformanceDegraded": GLib.Variant("s", ""),
            "Profiles": GLib.Variant("aa{sv}", profiles),
            "Actions": GLib.Variant("as", []),
            "ActionsInfo": GLib.Variant("aa{sv}", []),
            "ActiveProfileHolds": GLib.Variant("aa{sv}", holds),
            "Version": GLib.Variant("s", "0.30"),
            "BatteryAware": GLib.Variant("b", False),
        }

    def _on_get(self, _conn, _sender, _path, _iface, name):
        return self._props().get(name)

    def _on_set(self, _conn, sender, _path, _iface, name, value):
        if name != "ActiveProfile":
            return True   # BatteryAware и т. п. — игнорируем, автоматикой управляет asushero
        profile = FROM_PPD.get(value.unpack())
        if profile is None:
            return False

        # запись свойства синхронная, а polkit — асинхронный: проверяем и меняем режим после ответа
        def done(ok):
            if ok:
                log.info("KDE переключил режим: %s", profile)
                self.service.modes.set_profile(profile)
        authorize(self.bus, sender, POLKIT_ACTION, done)
        return True

    def _emit(self, names: list[str]) -> None:
        props = self._props()
        for iface, path in NAMES:
            self.bus.emit_signal(None, path, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                 GLib.Variant("(sa{sv}as)", (iface, {n: props[n] for n in names}, [])))

    def _profile_changed(self, _profile) -> None:
        self._emit(["ActiveProfile"])

    # ---------- методы ----------
    def _on_call(self, _conn, sender, _path, iface, method, params, invocation):
        args = params.unpack()
        if method == "HoldProfile":
            profile, reason, app = args
            if profile not in ("performance", "power-saver"):
                invocation.return_dbus_error(iface + ".Error.InvalidArgs", "можно удерживать только performance или power-saver")
                return
            cookie = self.next_cookie
            self.next_cookie += 1
            if not self.holds:
                self.before_hold = self.service.modes.current
            self.holds[cookie] = {"profile": profile, "reason": reason, "app": app, "sender": sender}
            log.info("%s удерживает режим %s: %s", app, profile, reason)
            self._apply_holds()
            invocation.return_value(GLib.Variant("(u)", (cookie,)))
        elif method == "ReleaseProfile":
            if self._release(args[0]):
                invocation.return_value(None)
            else:
                invocation.return_dbus_error(iface + ".Error.InvalidArgs", "нет такого удержания")
        elif method == "SetActionEnabled":
            invocation.return_value(None)

    def _apply_holds(self) -> None:
        # как в power-profiles-daemon: power-saver важнее performance
        wanted = {h["profile"] for h in self.holds.values()}
        if wanted:
            target = "power-saver" if "power-saver" in wanted else "performance"
            self.service.modes.set_profile(FROM_PPD[target], remember=False)
        elif self.before_hold:
            self.service.modes.set_profile(self.before_hold, remember=False)
            self.before_hold = None
        self._emit(["ActiveProfileHolds"])

    def _release(self, cookie: int) -> bool:
        if self.holds.pop(cookie, None) is None:
            return False
        for _iface, path in NAMES:
            self.bus.emit_signal(None, path, _iface, "ProfileReleased", GLib.Variant("(u)", (cookie,)))
        self._apply_holds()
        return True

    def _on_name_owner(self, _conn, _sender, _path, _iface, _signal, params):
        name, _old, new = params.unpack()
        if new == "":
            for cookie in [c for c, h in self.holds.items() if h["sender"] == name]:
                self._release(cookie)
