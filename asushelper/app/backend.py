"""Мост между окном (QML) и демоном (D-Bus).

D-Bus — через Gio: Qt в Linux крутит цикл событий GLib, поэтому асинхронные ответы Gio
приходят в том же потоке, что и интерфейс, без своих потоков и блокировок.
Датчики (обороты, температуры, ватты) опрашиваются, только пока окно открыто.
"""
import json
import logging
import os
from pathlib import Path

from gi.repository import Gio, GLib
from PySide6.QtCore import Property, QObject, QProcess, QTimer, Signal, Slot

from .. import BUS_NAME, INTERFACE, OBJECT_PATH
from . import display

log = logging.getLogger(__name__)

POLL_MS = 2000
# настройки самого приложения (не демона): то, что делает сеанс пользователя
SETTINGS = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "asus-helper" / "app.json"


def load_settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text())
    except (OSError, ValueError):
        return {}


class Backend(QObject):
    stateChanged = Signal()
    configChanged = Signal()
    displayChanged = Signal()
    nvidiaChanged = Signal()
    connectedChanged = Signal()
    activeChanged = Signal()
    screenAutoChanged = Signal()
    factoryCurves = Signal("QVariant")   # ответ на requestFactoryCurves
    message = Signal(str, bool)          # текст, ошибка ли

    def __init__(self, bus: Gio.DBusConnection):
        super().__init__()
        self.bus = bus
        self._state = {}
        self._config = {}
        self._display = {}
        self._nvidia = {}
        self._connected = False
        self._active = False
        self._settings = load_settings()
        self._last_ac = None
        self._timer = QTimer(self, interval=POLL_MS, timeout=self.refresh)
        bus.signal_subscribe(BUS_NAME, INTERFACE, "StateChanged", OBJECT_PATH, None,
                             Gio.DBusSignalFlags.NONE, self._on_state_signal)
        bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                             "/org/freedesktop/DBus", BUS_NAME, Gio.DBusSignalFlags.NONE,
                             lambda *a: self.refresh(config=True))
        self.refresh(config=True)
        self.refreshDisplay()

    # ---------- свойства для QML ----------
    def _get_state(self): return self._state
    def _get_config(self): return self._config
    def _get_display(self): return self._display
    def _get_nvidia(self): return self._nvidia
    def _get_connected(self): return self._connected
    def _get_active(self): return self._active
    def _get_screen_auto(self): return bool(self._settings.get("screen_auto", False))

    def _set_active(self, v: bool):
        """Окно открыто — опрашиваем датчики; закрыто — только сигналы демона."""
        if v == self._active:
            return
        self._active = v
        self.activeChanged.emit()
        if v:
            self.refresh(config=True)
            self.refreshDisplay()
            self._timer.start()
        else:
            self._timer.stop()

    state = Property("QVariant", _get_state, notify=stateChanged)
    config = Property("QVariant", _get_config, notify=configChanged)
    display = Property("QVariant", _get_display, notify=displayChanged)
    nvidia = Property("QVariant", _get_nvidia, notify=nvidiaChanged)
    connected = Property(bool, _get_connected, notify=connectedChanged)
    active = Property(bool, _get_active, _set_active, notify=activeChanged)
    screenAuto = Property(bool, _get_screen_auto, notify=screenAutoChanged)

    # ---------- D-Bus ----------
    def _call(self, method: str, sig: str | None = None, args: tuple = (), done=None, quiet=False):
        def finish(conn, res):
            try:
                v = conn.call_finish(res).unpack()
            except GLib.Error as e:
                self._set_connected("ServiceUnknown" not in e.message and "NameHasNoOwner" not in e.message)
                if not quiet:
                    text = e.message.split(": ", 1)[-1] if "GDBus.Error" in e.message else e.message
                    self.message.emit(text if self._connected else "Демон Asus-helper не запущен", True)
                return
            self._set_connected(True)
            if done:
                done(v[0] if v else None)
        self.bus.call(BUS_NAME, OBJECT_PATH, INTERFACE, method,
                      GLib.Variant(f"({sig})", args) if sig else None, None,
                      Gio.DBusCallFlags.NO_AUTO_START, 30000, None, finish)

    def _set_connected(self, v: bool):
        if v != self._connected:
            self._connected = v
            self.connectedChanged.emit()

    def _set_state(self, s: dict):
        self._state = s
        self.stateChanged.emit()
        if s.get("ac") is not None and s["ac"] != self._last_ac:
            self._last_ac = s["ac"]
            if self._get_screen_auto():
                self._screen_auto_apply()
        if self._active and (s.get("gpu") or {}).get("state") == "active":
            self._poll_nvidia()
        elif self._nvidia:
            self._nvidia = {}
            self.nvidiaChanged.emit()

    def _on_state_signal(self, *args):
        s = json.loads(args[5].unpack()[0])
        # в сигнале нет списка программ на NVIDIA (дорого считать) — сохраняем прошлый
        if "holders" not in s.get("gpu", {}) and "holders" in self._state.get("gpu", {}):
            s["gpu"]["holders"] = self._state["gpu"]["holders"]
        self._set_state(s)
        self._call("GetConfig", done=self._set_config, quiet=True)

    def _set_config(self, text):
        self._config = json.loads(text)
        self.configChanged.emit()

    @Slot()
    def refresh(self, config: bool = False):
        self._call("GetState", done=lambda t: self._set_state(json.loads(t)), quiet=True)
        if config:
            self._call("GetConfig", done=self._set_config, quiet=True)

    # ---------- команды ----------
    @Slot(str)
    def setProfile(self, p): self._call("SetProfile", "s", (p,))

    @Slot(bool)
    def setAutoProfile(self, v): self._call("SetAutoProfile", "b", (v,))

    @Slot(int)
    def setChargeLimit(self, v): self._call("SetChargeLimit", "u", (v,))

    @Slot(str, str)
    def setEpp(self, profile, epp): self._call("SetEpp", "ss", (profile, epp))

    @Slot(str, str, "QVariantList", "QVariantList")
    def setFanCurve(self, profile, fan, temp, pwm):
        self._call("SetFanCurve", "ssaiai", (profile, fan, [int(t) for t in temp], [int(p) for p in pwm]),
                   done=lambda _: self.message.emit("Кривая сохранена", False))

    @Slot(str, str)
    def resetFanCurve(self, profile, fan): self._call("ResetFanCurve", "ss", (profile, fan))

    @Slot()
    def requestFactoryCurves(self):
        self._call("GetFactoryFanCurves", done=lambda t: self.factoryCurves.emit(json.loads(t)))

    @Slot(str, str, int)
    def setPowerLimit(self, profile, attr, value): self._call("SetPowerLimit", "ssi", (profile, attr, value))

    @Slot(str)
    def resetPowerLimits(self, profile): self._call("ResetPowerLimits", "s", (profile,))

    @Slot(str, bool)
    def setGpuMode(self, mode, force): self._call("SetGpuMode", "sb", (mode, force))

    @Slot(bool)
    def setGpuAutoEco(self, v): self._call("SetGpuAutoEco", "b", (v,))

    @Slot(str, bool)
    def setToggle(self, attr, v): self._call("SetToggle", "sb", (attr, v))

    @Slot(int)
    def setKeyboardBrightness(self, v): self._call("SetKeyboardBrightness", "u", (v,))

    @Slot(str, str, str, str)
    def setAura(self, mode, color, color2, speed): self._call("SetAura", "ssss", (mode, color, color2, speed))

    @Slot(bool, bool, bool, bool)
    def setAuraPower(self, awake, boot, sleep, shutdown):
        self._call("SetAuraPower", "bbbb", (awake, boot, sleep, shutdown))

    # ---------- экран (KDE, без демона) ----------
    @Slot()
    def refreshDisplay(self):
        display.query(self._on_display)

    def _on_display(self, info: dict):
        self._display = info
        self.displayChanged.emit()

    @Slot(bool)
    def setScreenAuto(self, v):
        self._settings["screen_auto"] = bool(v)
        try:
            SETTINGS.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS.write_text(json.dumps(self._settings, indent=2))
        except OSError as e:
            log.warning("не сохранить %s: %s", SETTINGS, e)
        self.screenAutoChanged.emit()
        if v:
            self._screen_auto_apply()

    def _screen_auto_apply(self):
        """Авто, как в G-Helper: от сети — максимальная частота, на батарее — минимальная."""
        def got(info):
            self._on_display(info)
            rates = info.get("rates") or []
            if len(rates) > 1 and self._last_ac is not None:
                want = rates[-1] if self._last_ac else rates[0]
                if info.get("hz") != want:
                    log.info("экран авто: %s Гц", want)
                    self.setRefreshRate(want)
        display.query(got)

    @Slot(int)
    def setRefreshRate(self, hz):
        display.set_rate(self._display, hz, lambda err: (self.message.emit(err, True) if err else None,
                                                         self.refreshDisplay()))

    # ---------- NVIDIA (только когда карта и так работает и окно открыто) ----------
    def _poll_nvidia(self):
        p = QProcess(self)

        def done():
            out = bytes(p.readAllStandardOutput()).decode().strip().split(", ")
            if len(out) == 4:
                self._nvidia = {"load": int(out[0]), "power": float(out[1]), "memory": int(out[2]), "temp": int(out[3])}
                self.nvidiaChanged.emit()
            p.deleteLater()
        p.finished.connect(done)
        p.start("nvidia-smi", ["--query-gpu=utilization.gpu,power.draw,memory.used,temperature.gpu",
                               "--format=csv,noheader,nounits"])
