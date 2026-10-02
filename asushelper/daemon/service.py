"""D-Bus API демона: org.asushelper.Daemon на системной шине.

Сложные данные (состояние, настройки) передаются строкой JSON: так их одинаково легко читать
из QML, Python и busctl. Методы, которые что-то меняют, проверяют право через polkit
(действие org.asushelper.manage: активному пользователю — без пароля).
"""
import json
import logging

from gi.repository import Gio, GLib

from .. import BUS_NAME, INTERFACE, OBJECT_PATH, PROFILES, __version__
from . import aura
from . import gpu
from . import hardware as hw
from . import history
from . import slash
from .config import Config
from .modes import Modes

log = logging.getLogger(__name__)

POLKIT_ACTION = "org.asushelper.manage"
# False только при разработке на сессионной шине (там нет polkit)
USE_POLKIT = True
ERROR = "org.asushelper.Error"

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
    <method name="SetGpuMode">
      <arg type="s" direction="in" name="mode"/><arg type="b" direction="in" name="force"/>
    </method>
    <!-- flags: 1 — закрыть программы на NVIDIA, 2 — выключить, даже если к ней подключён монитор -->
    <method name="SetGpuModeFlags">
      <arg type="s" direction="in" name="mode"/><arg type="u" direction="in" name="flags"/>
    </method>
    <method name="SetGpuAutoEco"><arg type="b" direction="in" name="enabled"/></method>
    <!-- переключатели BIOS: panel_overdrive, boot_sound -->
    <method name="SetToggle">
      <arg type="s" direction="in" name="attr"/><arg type="b" direction="in" name="enabled"/>
    </method>
    <method name="SetCpuBoost">
      <arg type="s" direction="in" name="profile"/><arg type="b" direction="in" name="enabled"/>
    </method>
    <method name="SetSlash">
      <arg type="s" direction="in" name="mode"/><arg type="u" direction="in" name="brightness"/>
      <arg type="u" direction="in" name="interval"/>
    </method>
    <method name="SetSlashOptions">
      <arg type="b" direction="in" name="on_battery"/><arg type="b" direction="in" name="lid_closed"/>
    </method>
    <!-- датчики за последний час (раз в 5 с) и здоровье батареи по дням -->
    <method name="GetHistory"><arg type="s" direction="out" name="json"/></method>
    <method name="SetKeyboardBrightness"><arg type="u" direction="in" name="level"/></method>
    <method name="SetAura">
      <arg type="s" direction="in" name="mode"/><arg type="s" direction="in" name="color"/>
      <arg type="s" direction="in" name="color2"/><arg type="s" direction="in" name="speed"/>
    </method>
    <method name="SetAuraPower">
      <arg type="b" direction="in" name="awake"/><arg type="b" direction="in" name="boot"/>
      <arg type="b" direction="in" name="sleep"/><arg type="b" direction="in" name="shutdown"/>
    </method>
    <signal name="StateChanged"><arg type="s" name="json"/></signal>
    <!-- яркость сменили клавишами — для карточки KDE -->
    <signal name="KeyboardBrightnessChanged"><arg type="i" name="level"/><arg type="i" name="max"/></signal>
    <!-- переключение видеокарты закончилось; error пустой — успешно -->
    <signal name="GpuSwitchFinished"><arg type="s" name="state"/><arg type="s" name="error"/></signal>
    <property name="Profile" type="s" access="read"/>
    <property name="Version" type="s" access="read"/>
  </interface>
</node>
"""

# Методы, которые только читают — без polkit
READ_ONLY = {"GetState", "GetConfig", "GetHistory"}


class Failed(Exception):
    """Ошибка для клиента: текст уходит ему как org.asushelper.Error.Failed."""


class Service:
    def __init__(self, bus: Gio.DBusConnection, config: Config):
        self.bus = bus
        self.config = config
        self.listeners = []   # другие интерфейсы (эмуляция PPD) — тоже хотят знать о смене режима
        self.modes = Modes(config, self._changed)
        self.gpu = gpu.Switcher(self._gpu_done)
        self._gpu_cache = {}
        self._state_cache = {}
        self._gpu_state()
        self.history = history.History(paused=lambda: self.gpu.busy)
        self._last_profile = None
        self._save_brightness = 0
        node = Gio.DBusNodeInfo.new_for_xml(XML)
        bus.register_object(OBJECT_PATH, node.interfaces[0], self._on_call, self._on_get_property, None)

    # ---------- состояние ----------
    def state(self) -> dict:
        # Пока BIOS включает или выключает NVIDIA (до ~10 с), любое другое обращение к BIOS (WMI) ждёт
        # своей очереди — и демон перестал бы отвечать. Отдаём последнее состояние, меняем только видеокарту.
        if self.gpu.busy and self._state_cache:
            return dict(self._state_cache, gpu=self._gpu_state(), profile=self.modes.current)
        self._state_cache = self._read_state()
        return self._state_cache

    def _read_state(self) -> dict:
        return {
            "version": __version__,
            "model": hw.model(),
            "profile": self.modes.current,
            "profiles": [p for p in PROFILES if p in hw.profile_choices()],
            "ac": self.modes.ac,
            "auto_profile": self.config.data["auto_profile"],
            "profile_on_ac": self.config.data["profile_on_ac"],
            "profile_on_battery": self.config.data["profile_on_battery"],
            "epp": hw.epp(),
            "epp_choices": hw.epp_choices(),
            "fans": hw.fan_rpm(),
            "fan_curves": {f: hw.fan_curve(f) for f in hw.curve_fans()} or None,
            "cpu_temp": hw.cpu_temp(),
            "battery": hw.battery(),
            "power_limits": hw.power_limits(),
            "toggles": {a: v["value"] == 1 for a in hw.TOGGLE_ATTRS if (v := hw.armoury_attr(a))},
            "cpu_boost": hw.turbo(),
            "slash": {**self.config.data["slash"], "supported": slash.supported(),
                      "modes": [{"id": k, "name": v[1]} for k, v in slash.MODES.items()]},
            "gpu": self._gpu_state(),
            "keyboard": {**self.config.data["keyboard"], "rgb": aura.rgb_method(),
                         **({"brightness": b["value"], "max": b["max"]} if (b := aura.brightness()) else {})}
                        if aura.brightness() or aura.rgb_method() else None,
        }

    def _gpu_state(self) -> dict:
        # Во время переключения шину PCI не читаем: при её пересканировании (включение NVIDIA) чтение
        # /sys/bus/pci ждёт до 10 с, и демон перестал бы отвечать. Отдаём последнее известное + цель.
        if self.gpu.busy:
            return dict(self._gpu_cache, switching=True, target=self.gpu.target,
                        auto_eco=self.config.data["gpu"]["auto_eco"], error=None, can_force=False)
        supported = gpu.supported()
        self._gpu_cache = {
            "supported": supported,
            "state": gpu.state() if supported else None,
            "mux_hybrid": gpu.mux_hybrid(),
            "auto_eco": self.config.data["gpu"]["auto_eco"],
            "switching": False,
            "target": None,
            "error": self.gpu.last_error,
            "can_force": self.gpu.can_force and self.gpu.last_error is not None,
            "external": gpu.external_displays() if supported and not gpu.bios_off() else [],
        }
        return self._gpu_cache

    def full_state(self) -> dict:
        """state() и то, что дорого считать для каждого сигнала (кто держит NVIDIA)."""
        s = self.state()
        if s["gpu"]["state"] not in (None, "off") and not s["gpu"]["switching"]:
            s["gpu"]["holders"] = sorted({c for _, c in gpu.holders()})
        return s

    # ---------- события ----------
    def startup(self) -> None:
        if gpu.supported():
            gpu.fixup()
        self.apply_keyboard()
        self.apply_slash(wake=True)
        self.history.start()
        # «Заряд батареи» на Slash — обновлять раз в минуту
        GLib.timeout_add_seconds(60, self._slash_battery_tick)
        self.modes.startup()
        self._auto_eco()
        self._watch_brightness()

    def resumed(self) -> None:
        self.modes.ac = hw.on_ac()
        self.apply_keyboard()
        self.apply_slash(wake=True)
        self.modes.reapply("выход из сна")
        self._auto_eco()

    def power_source_changed(self, ac: bool) -> None:
        if ac == self.modes.ac:
            return
        self.modes.power_source_changed(ac)
        self._auto_eco()

    def apply_keyboard(self) -> None:
        k = self.config.data["keyboard"]
        aura.set_brightness(k["brightness"])
        aura.apply(k)

    def apply_slash(self, wake: bool = False) -> bool:
        if not slash.supported():
            return False
        b = hw.battery() or {}
        return slash.apply(self.config.data["slash"], b.get("capacity"), wake)

    def _slash_battery_tick(self):
        c = self.config.data["slash"]
        if c["mode"] == "battery" and c["brightness"] > 0:
            self.apply_slash()
        return GLib.SOURCE_CONTINUE

    def _auto_eco(self) -> None:
        if not (self.config.data["gpu"]["auto_eco"] and gpu.supported()):
            return
        want_off = not self.modes.ac
        if want_off and gpu.external_displays():
            log.info("«Оптимальный»: к NVIDIA подключён монитор — не выключаю")
            return
        if gpu.bios_off() != want_off and not self.gpu.busy:
            log.info("«Оптимальный»: %s", "батарея → Eco" if want_off else "сеть → NVIDIA включается")
            self.gpu.start(want_off)
            self._changed()

    def _gpu_done(self, error) -> None:
        self.modes._nvidia_powerd(self.modes.ac)   # после включения карты сервис мог запуститься на батарее
        self.bus.emit_signal(None, OBJECT_PATH, INTERFACE, "GpuSwitchFinished",
                             GLib.Variant("(ss)", (gpu.state(), error or "")))
        self._changed()

    def _watch_brightness(self) -> None:
        import os
        path = aura.brightness_hw_changed_path()
        if path is None:
            return
        fd = os.open(sysfs_path(path), os.O_RDONLY)
        try:
            os.read(fd, 16)   # без первого чтения poll сработает сразу; ENODATA до первого нажатия — норма
        except OSError:
            pass

        def changed(fd, _cond):
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                level = int(os.read(fd, 16))
            except (OSError, ValueError):
                return True
            b = aura.brightness() or {"max": 3}
            self.bus.emit_signal(None, OBJECT_PATH, INTERFACE, "KeyboardBrightnessChanged",
                                 GLib.Variant("(ii)", (level, b["max"])))
            self.config.data["keyboard"]["brightness"] = level
            self._changed()   # окно показывает новую яркость сразу
            # клавишу жмут несколько раз — на диск сохраняем, когда закончили
            if self._save_brightness:
                GLib.source_remove(self._save_brightness)
            self._save_brightness = GLib.timeout_add_seconds(3, self._save_config_later)
            return True
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT, GLib.IOCondition.PRI | GLib.IOCondition.ERR, changed)

    def _save_config_later(self):
        self._save_brightness = 0
        self.config.save()
        return GLib.SOURCE_REMOVE

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
        return json.dumps(self.full_state())

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
        curves = {f: hw.factory_fan_curve(f) for f in hw.curve_fans()}
        cache = self.config.data.setdefault("factory_curves", {}).setdefault(self.modes.current, {})
        cache.update({f: {"temp": c["temp"], "pwm": c["pwm"]} for f, c in curves.items() if c})
        self.config.save()
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

    def do_SetGpuMode(self, mode, force):
        self.do_SetGpuModeFlags(mode, 1 if force else 0)

    def do_SetGpuModeFlags(self, mode, flags):
        force, ignore_displays = bool(flags & 1), bool(flags & 2)
        if not gpu.supported():
            raise Failed("на этом ноутбуке нельзя выключать видеокарту через BIOS")
        if mode not in ("eco", "standard"):
            raise Failed("режим видеокарты: eco или standard")
        if self.gpu.busy:
            raise Failed("видеокарта уже переключается")
        if mode == "eco" and not gpu.mux_hybrid():
            raise Failed("MUX в режиме «только NVIDIA» — выключать её нельзя")
        if self.config.data["gpu"]["auto_eco"]:
            # ручной выбор отменяет «Оптимальный», иначе при смене питания карта переключится сама
            self.config.data["gpu"]["auto_eco"] = False
            self.config.save()
        self.gpu.start(mode == "eco", force, ignore_displays)
        self._changed()

    def do_SetGpuAutoEco(self, enabled):
        self.config.data["gpu"]["auto_eco"] = bool(enabled)
        self.config.save()
        self._auto_eco()
        self._changed()

    def do_SetToggle(self, attr, enabled):
        if attr not in hw.TOGGLE_ATTRS or hw.armoury_attr(attr) is None:
            raise Failed(f"переключателя «{attr}» нет")
        from . import sysfs
        if not sysfs.write(f"{hw.ARMOURY}/{attr}/current_value", 1 if enabled else 0):
            raise Failed("BIOS не принял значение")
        self._changed()

    def do_SetCpuBoost(self, profile, enabled):
        check_profile(profile)
        if hw.turbo() is None:
            raise Failed("Turbo Boost не управляется (нет intel_pstate)")
        self.config.profile(profile)["cpu_boost"] = bool(enabled)
        self._save_and_reapply(profile)

    def do_SetSlash(self, mode, brightness, interval):
        if not slash.supported():
            raise Failed("полоса Slash не найдена")
        if mode not in slash.MODES:
            raise Failed(f"анимация: {', '.join(slash.MODES)}")
        if brightness > 3 or interval > 5:
            raise Failed("яркость 0–3, пауза 0–5")
        self.config.data["slash"].update(mode=mode, brightness=int(brightness), interval=int(interval))
        if not self.apply_slash():
            raise Failed("Slash не ответила (журнал демона)")
        self.config.save()
        self._changed()

    def do_SetSlashOptions(self, on_battery, lid_closed):
        self.config.data["slash"].update(on_battery=bool(on_battery), lid_closed=bool(lid_closed))
        if not self.apply_slash():
            raise Failed("Slash не ответила (журнал демона)")
        self.config.save()
        self._changed()

    def do_GetHistory(self):
        return json.dumps(self.history.dump())

    def do_SetKeyboardBrightness(self, level):
        if not aura.set_brightness(level):
            raise Failed("подсветка клавиатуры не найдена")
        self.config.data["keyboard"]["brightness"] = (aura.brightness() or {}).get("value", level)
        self.config.save()
        self._changed()

    def do_SetAura(self, mode, color, color2, speed):
        if mode not in aura.MODES:
            raise Failed(f"эффект: {', '.join(aura.MODES)}")
        if speed not in aura.SPEEDS:
            raise Failed(f"скорость: {', '.join(aura.SPEEDS)}")
        try:
            aura.parse_color(color)
            aura.parse_color(color2 or "#000000")
        except ValueError as e:
            raise Failed(str(e))
        k = self.config.data["keyboard"]
        k.update(mode=mode, color=color.upper(), color2=(color2 or "#000000").upper(), speed=speed)
        if not aura.apply(k):
            raise Failed("клавиатура Aura не ответила (журнал демона)")
        self.config.save()
        self._changed()

    def do_SetAuraPower(self, awake, boot, sleep, shutdown):
        k = self.config.data["keyboard"]
        k.update(awake=awake, boot=boot, sleep=sleep, shutdown=shutdown)
        if not aura.apply(k):
            raise Failed("клавиатура Aura не ответила (журнал демона)")
        self.config.save()
        self._changed()

    def _save_and_reapply(self, profile):
        self.config.save()
        if profile == self.modes.current:
            self.modes.reapply(f"изменены настройки режима {profile}")
        else:
            self._changed()


def sysfs_path(p: str) -> str:
    from . import sysfs
    return sysfs.path(p)


def check_profile(p):
    if p not in PROFILES:
        raise Failed(f"неизвестный режим «{p}» (есть: {', '.join(PROFILES)})")


def check_fan(f):
    if f not in hw.curve_fans():
        raise Failed(f"неизвестный вентилятор «{f}» (есть: {', '.join(hw.curve_fans())})")


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
