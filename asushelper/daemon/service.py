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
from . import idle
from . import slash
from .config import Config
from .modes import Modes
from ..i18n import _

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
    <!-- перед удалением: заводские лимиты, кривые вентиляторов BIOS, Turbo Boost включён -->
    <method name="RestoreFactory"/>
    <method name="SetGpuMode">
      <arg type="s" direction="in" name="mode"/><arg type="b" direction="in" name="force"/>
    </method>
    <!-- flags: 1 — закрыть программы на NVIDIA, 2 — выключить, даже если к ней подключён монитор -->
    <method name="SetGpuModeFlags">
      <arg type="s" direction="in" name="mode"/><arg type="u" direction="in" name="flags"/>
    </method>
    <method name="SetGpuAutoEco"><arg type="b" direction="in" name="enabled"/></method>
    <!-- ответ на вопрос Eco (сигнал GpuAutoAsk): close — закрыть программы и выключить, wait — подождать,
         cancel — не выключать -->
    <method name="SetGpuAutoAnswer"><arg type="s" direction="in" name="answer"/></method>
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
    <!-- язык интерфейса (ru, en); демон и окно перезапускаются на новом языке -->
    <method name="SetLanguage"><arg type="s" direction="in" name="lang"/></method>
    <!-- гаснуть без нажатий: секунды от сети и от батареи, 0 — не гаснуть -->
    <method name="SetKeyboardTimeout">
      <arg type="u" direction="in" name="ac"/><arg type="u" direction="in" name="battery"/>
    </method>
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
    <!-- Eco (вручную или «Авто» без зарядки), а на NVIDIA работают программы (первая — самая «тяжёлая»):
         закрыть или подождать? manual — Eco выбрал человек -->
    <signal name="GpuAutoAsk"><arg type="as" name="programs"/><arg type="b" name="manual"/></signal>
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
        self._auto_settle = 0       # «Авто» ждёт, пока после смены питания успокоятся события ACPI
        self.auto_waiting: list[str] | None = None   # Eco ждёт, пока закроют эти программы на NVIDIA
        self.waiting_manual = False  # ждёт ручной Eco (иначе — «Авто»)
        self._wait_ignore_displays = False
        self._auto_watch = 0
        self.idle = None
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
            # из кэша — только то, что читается через BIOS; настройки, процессор, Slash — как есть сейчас
            st = dict(self._state_cache, **self._live_state(), gpu=self._gpu_state())
            if kbd := st.get("keyboard"):
                st["keyboard"] = {**kbd, **self.config.data["keyboard"]}   # яркость — последняя заданная
            return st
        self._state_cache = self._read_state()
        return self._state_cache

    def _live_state(self) -> dict:
        """Части состояния, которые не обращаются к BIOS (WMI) и шине PCI — их можно читать всегда."""
        return {
            "profile": self.modes.current,
            "ac": self.modes.ac,
            "auto_profile": self.config.data["auto_profile"],
            "profile_on_ac": self.config.data["profile_on_ac"],
            "profile_on_battery": self.config.data["profile_on_battery"],
            "epp": hw.epp(),
            "epp_choices": hw.epp_choices(),
            "cpu_temp": hw.cpu_temp(),
            "cpu_boost": hw.turbo(),
            "slash": {**self.config.data["slash"], "supported": slash.supported(),
                      "modes": [{"id": k, "name": v[1]} for k, v in slash.MODES.items()]},
        }

    def _read_state(self) -> dict:
        return {
            "version": __version__,
            "model": hw.model(),
            "profiles": [p for p in PROFILES if p in hw.profile_choices()],
            **self._live_state(),
            "fans": hw.fan_rpm(),
            "fan_curves": {f: hw.fan_curve(f) for f in hw.curve_fans()} or None,
            "battery": hw.battery(),
            "power_limits": hw.power_limits(),
            "toggles": {a: v["value"] == 1 for a in hw.TOGGLE_ATTRS if (v := hw.armoury_attr(a))},
            "gpu": self._gpu_state(),
            "keyboard": {**self.config.data["keyboard"], "rgb": aura.rgb_method(),
                         **({"brightness": b["value"], "max": b["max"]} if (b := aura.brightness()) else {})}
                        if aura.brightness() or aura.rgb_method() else None,
        }

    def _gpu_state(self) -> dict:
        # Во время переключения шину PCI не читаем: при её пересканировании (включение NVIDIA) чтение
        # /sys/bus/pci ждёт до 10 с, и демон перестал бы отвечать. Отдаём последнее известное + цель.
        if self.gpu.busy:
            return dict(self._gpu_cache, switching=True, target=self.gpu.target, auto_waiting=None,
                        auto_eco=self.config.data["gpu"]["auto_eco"], error=None)
        supported = gpu.supported()
        cards = gpu.display_gpus()
        g = self.config.data["gpu"]
        if cards["dgpu"] and g.get("dgpu") != cards["dgpu"]:
            g["dgpu"] = cards["dgpu"]          # запомнить: в Eco карты на шине нет, а название нужно
            self.config.save()
        dgpu = cards["dgpu"] or g.get("dgpu") or {}
        igpu = cards["igpu"] or {}
        self._gpu_cache = {
            "supported": supported,
            "state": gpu.state() if supported else None,
            "mux_hybrid": gpu.mux_hybrid(),
            "auto_eco": self.config.data["gpu"]["auto_eco"],
            "switching": False,
            "target": None,
            "error": gpu.stuck_message() if gpu.is_stuck() else self.gpu.last_error,
            "stuck": gpu.is_stuck(),
            "external": gpu.external_displays() if supported and not gpu.bios_off() else [],
            "dgpu_name": dgpu.get("vendor") or "NVIDIA",
            "dgpu_model": dgpu.get("model"),
            "igpu_model": igpu.get("model"),
            "auto_waiting": self.auto_waiting,
            "waiting_manual": self.waiting_manual,
            "igpu_name": igpu.get("vendor") or gpu.igpu_name(),
        }
        return self._gpu_cache

    def full_state(self) -> dict:
        """state() и то, что дорого считать для каждого сигнала (кто держит NVIDIA)."""
        s = self.state()
        if s["gpu"]["state"] not in (None, "off") and not s["gpu"]["switching"]:
            s["gpu"]["holders"] = gpu.names([(p, gpu.program_name(p, c)) for p, c in gpu.holders()])
        return s

    # ---------- события ----------
    def startup(self) -> None:
        gpu.write_kwin_env()
        if gpu.supported():
            gpu.fixup()
        self.apply_keyboard()
        self.apply_slash(wake=True)
        self.history.start()
        self.idle = idle.KeyboardIdle(self.config, lambda: self.modes.ac) if aura.brightness() else None
        # «Заряд батареи» на Slash — обновлять раз в минуту
        GLib.timeout_add_seconds(60, self._slash_battery_tick)
        self.modes.startup()
        self._auto_eco_later()      # при загрузке BIOS тоже рассылает события питания
        self._watch_brightness()

    def before_sleep(self) -> None:
        """Во сне — заводские кривые вентиляторов BIOS. Своя кривая остаётся в контроллере и во сне, и с её
        минимумом (даже 1–2 %) вентиляторы крутились бы при закрытой крышке; BIOS на холодную их
        останавливает. После пробуждения resumed() вернёт свою кривую."""
        self.modes._cancel_timers()
        if hw.has_fan_curves() and any((hw.fan_curve(f) or {}).get("enabled") for f in hw.curve_fans()):
            for f in hw.curve_fans():
                hw.set_fan_curve_mode(f, hw.CURVE_BIOS)
            log.info(_("сон: вентиляторы — по кривой BIOS"))

    def resumed(self) -> None:
        self.modes.ac = hw.on_ac()
        if self.idle:
            self.idle.reset()
        self.apply_keyboard()
        self.apply_slash(wake=True)
        self.modes.reapply(_("выход из сна"))
        self._auto_eco_later()

    def power_source_changed(self, ac: bool) -> None:
        if ac == self.modes.ac:
            return
        self.modes.power_source_changed(ac)
        self._auto_eco_later()

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

    # После подключения зарядки, выхода из сна и загрузки BIOS несколько секунд рассылает события ACPI о
    # питании, и драйвер NVIDIA их обрабатывает. Переключать в этот момент — риск зависания в ядре, поэтому
    # «Авто» ждёт. Попытка одна: не получилось — ошибка в окне, следующая — при следующей смене питания.
    AUTO_SETTLE_S = 10

    def _auto_eco_later(self) -> None:
        if self._auto_settle:
            GLib.source_remove(self._auto_settle)

        def run():
            self._auto_settle = 0
            self._auto_eco()
            return GLib.SOURCE_REMOVE
        self._auto_settle = GLib.timeout_add_seconds(self.AUTO_SETTLE_S, run)

    AUTO_WATCH_S = 3

    def _auto_eco(self) -> None:
        """«Авто»: от сети NVIDIA включена, без сети — Eco. Если на NVIDIA работают программы, сначала
        спрашиваем (уведомление: закрыть или подождать) и ждём, пока их закроют."""
        if self.waiting_manual:
            return                          # человек сам выбрал Eco и ждёт закрытия программ — не мешаем
        if not (self.config.data["gpu"]["auto_eco"] and gpu.supported()) or self.gpu.busy or gpu.is_stuck():
            return self._stop_waiting()
        if self.modes.ac:
            self._stop_waiting()
            if gpu.bios_off():
                log.info(_("«Авто»: сеть → включаю NVIDIA"))
                self.gpu.start(False)
                self._changed()
            return
        if gpu.bios_off():
            return self._stop_waiting()
        if gpu.external_displays():
            log.info(_("«Авто»: к NVIDIA подключён монитор — не выключаю"))
            return self._stop_waiting()
        self._eco_when_free(manual=False)

    def _eco_when_free(self, manual: bool) -> None:
        """Eco, но программы на NVIDIA без спроса не закрываем: есть такие — спросить и ждать, пока закроют."""
        if programs := gpu.user_programs():
            return self._wait_for(programs, manual)
        self._stop_waiting(manual=True)
        log.info(_("Eco: NVIDIA свободна — выключаю") if manual else _("«Авто»: батарея → Eco"))
        self.gpu.start(True, ignore_displays=manual and self._wait_ignore_displays)
        self._changed()

    def _wait_for(self, programs: list[str], manual: bool) -> None:
        """Программы на NVIDIA работают — спросить один раз и проверять, не закрыли ли их."""
        asked = self.auto_waiting is not None
        if programs != self.auto_waiting or manual != self.waiting_manual:
            self.auto_waiting = programs
            self.waiting_manual = manual
            self._changed()
        if not asked:
            log.info(_("Eco: на NVIDIA работают %s — спрашиваю, закрыть или подождать"), ", ".join(programs))
            self.bus.emit_signal(None, OBJECT_PATH, INTERFACE, "GpuAutoAsk",
                                 GLib.Variant("(asb)", (programs, manual)))
        if not self._auto_watch:
            self._auto_watch = GLib.timeout_add_seconds(self.AUTO_WATCH_S, self._auto_watch_tick)

    def _auto_watch_tick(self) -> bool:
        self._auto_watch = 0
        if not self.waiting_manual:
            self._auto_eco()                # закрыли — Eco; нет — снова поставит проверку
        elif self.gpu.busy or gpu.is_stuck() or gpu.bios_off():
            self._stop_waiting(manual=True)
        else:
            self._eco_when_free(manual=True)
        return GLib.SOURCE_REMOVE

    def _stop_waiting(self, manual: bool = False) -> None:
        """Перестать ждать. Ожидание, которое начал сам человек (ручной Eco), снимает только он сам
        (Стандарт, «Авто», «Отмена») — не смена питания."""
        if self.waiting_manual and not manual:
            return
        if self._auto_watch:
            GLib.source_remove(self._auto_watch)
            self._auto_watch = 0
        if self.auto_waiting is not None:
            self.auto_waiting = None
            self.waiting_manual = False
            self._changed()

    def _gpu_done(self, error) -> None:
        self.modes._nvidia_powerd(self.modes.ac)   # после включения карты сервис мог запуститься на батарее
        self.bus.emit_signal(None, OBJECT_PATH, INTERFACE, "GpuSwitchFinished",
                             GLib.Variant("(ss)", (gpu.state(), error or "")))
        self._changed()
        if not error:
            # питание могло смениться, пока карта переключалась, — «Авто» тогда событие пропустило
            self._auto_eco()

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
                      else invocation.return_dbus_error(ERROR + ".NotAuthorized", _("нет прав (polkit)")))

    def _dispatch(self, method, args, invocation):
        try:
            result = getattr(self, "do_" + method)(*args)
        except Failed as e:
            invocation.return_dbus_error(ERROR + ".Failed", str(e))
            return
        except Exception as e:  # демон не должен падать из-за одного неудачного вызова
            log.exception("%s%s", method, args)
            invocation.return_dbus_error(ERROR + ".Failed", _("внутренняя ошибка: {0}").format(e))
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
            raise Failed(_("лимит заряда — от 20 до 100 %"))
        if not hw.set_charge_limit(percent):
            raise Failed(_("ядро не приняло лимит заряда"))
        self.config.data["charge_limit"] = percent
        self.config.save()
        self._changed()

    def do_SetEpp(self, profile, epp):
        check_profile(profile)
        if epp and epp not in hw.epp_choices():
            raise Failed(_("EPP «{0}» не поддерживается: {1}").format(epp, ' '.join(hw.epp_choices())))
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
            raise Failed(_("ядро не поддерживает свои кривые вентиляторов"))
        curves = {f: hw.factory_fan_curve(f) for f in hw.curve_fans()}
        cache = self.config.data.setdefault("factory_curves", {}).setdefault(self.modes.current, {})
        cache.update({f: {"temp": c["temp"], "pwm": c["pwm"]} for f, c in curves.items() if c})
        self.config.save()
        self.modes.reapply(_("после чтения заводских кривых"))   # вернуть свои кривые, если были
        return json.dumps({"profile": self.modes.current, "curves": curves})

    def do_SetPowerLimit(self, profile, attr, value):
        check_profile(profile)
        if attr not in hw.POWER_ATTRS:
            raise Failed(_("неизвестный параметр «{0}»").format(attr))
        if hw.armoury_attr(attr) is None:
            raise Failed(_("параметра «{0}» нет на этом ноутбуке").format(attr))
        limits = self.config.profile(profile)["power_limits"]
        if value < 0:
            limits.pop(attr, None)     # -1 — вернуть управление BIOS
        else:
            limits[attr] = value
        self._save_and_reapply(profile)

    def do_ResetPowerLimits(self, profile):
        check_profile(profile)
        self.config.profile(profile)["power_limits"] = {}
        self._save_and_reapply(profile)      # лимиты без своего значения — заводские

    def do_RestoreFactory(self):
        """Вернуть ноутбуку заводское поведение — то, что демон менял в BIOS и ядре, без него не вернулось бы
        до перезагрузки (а лимиты мощности BIOS может и помнить)."""
        for attr, a in hw.power_limits().items():
            if a["default"] is not None and a["min"] is not None and a["max"] is not None and a["max"] > a["min"]:
                hw.set_armoury(attr, a["default"])
        for f in hw.curve_fans():
            hw.set_fan_curve_mode(f, hw.CURVE_BIOS)
        if hw.turbo() is False:
            hw.set_turbo(True)
        if not gpu.bios_off():
            gpu._start_services()          # nvidia-powerd и др., если демон их останавливал
        log.info(_("заводские настройки возвращены (перед удалением)"))

    def do_SetGpuMode(self, mode, force):
        self.do_SetGpuModeFlags(mode, 1 if force else 0)

    def do_SetGpuModeFlags(self, mode, flags):
        force, ignore_displays = bool(flags & 1), bool(flags & 2)
        if not gpu.supported():
            raise Failed(_("на этом ноутбуке нельзя выключать видеокарту через BIOS"))
        if mode not in ("eco", "standard"):
            raise Failed(_("режим видеокарты: eco или standard"))
        if self.gpu.busy:
            raise Failed(_("видеокарта уже переключается"))
        if gpu.is_stuck():
            raise Failed(gpu.stuck_message())
        if mode == "eco" and not gpu.mux_hybrid():
            raise Failed(_("MUX в режиме «только NVIDIA» — выключать её нельзя"))
        if self.config.data["gpu"]["auto_eco"]:
            # ручной выбор отменяет «Оптимальный», иначе при смене питания карта переключится сама
            self.config.data["gpu"]["auto_eco"] = False
            self.config.save()
        self._stop_waiting(manual=True)      # новый выбор отменяет прежнее ожидание
        self._wait_ignore_displays = ignore_displays
        if mode == "eco" and not force and not gpu.bios_off():
            self._eco_when_free(manual=True)   # программы на NVIDIA без спроса не закрываем
            return
        self.gpu.start(mode == "eco", force, ignore_displays)
        self._changed()

    def do_SetGpuAutoAnswer(self, answer):
        """Ответ на вопрос (уведомление или окно): close — закрыть программы и выключить, wait — подождать,
        cancel — не выключать (только для ручного Eco; «Авто» просто ждёт дальше)."""
        if answer not in ("close", "wait", "cancel"):
            raise Failed(_("ответ: close, wait или cancel"))
        if answer == "wait" or self.auto_waiting is None:
            return
        if answer == "cancel" and not self.waiting_manual:
            return                          # «Авто» не отменяется: дождётся, пока программы закроют, и выключит
        ignore_displays = self.waiting_manual and self._wait_ignore_displays
        self._stop_waiting(manual=True)
        if answer == "cancel":
            log.info(_("Eco отменён — NVIDIA остаётся включённой"))
            return
        log.info(_("Eco: закрыть программы на NVIDIA и выключить её — так ответили"))
        if not self.gpu.busy:
            self.gpu.start(True, ignore_displays=ignore_displays)
            self._changed()

    def do_SetGpuAutoEco(self, enabled):
        self._stop_waiting(manual=True)
        self.config.data["gpu"]["auto_eco"] = bool(enabled)
        self.config.save()
        self._auto_eco()
        self._changed()

    def do_SetToggle(self, attr, enabled):
        if attr not in hw.TOGGLE_ATTRS or hw.armoury_attr(attr) is None:
            raise Failed(_("переключателя «{0}» нет").format(attr))
        from . import sysfs
        if not sysfs.write(f"{hw.ARMOURY}/{attr}/current_value", 1 if enabled else 0):
            raise Failed(_("BIOS не принял значение"))
        self._changed()

    def do_SetCpuBoost(self, profile, enabled):
        check_profile(profile)
        if hw.turbo() is None:
            raise Failed(_("Turbo Boost не управляется (нет intel_pstate)"))
        self.config.profile(profile)["cpu_boost"] = bool(enabled)
        self._save_and_reapply(profile)

    def do_SetSlash(self, mode, brightness, interval):
        if not slash.supported():
            raise Failed(_("полоса Slash не найдена"))
        if mode not in slash.MODES:
            raise Failed(_("анимация: {0}").format(', '.join(slash.MODES)))
        if brightness > 3 or interval > 5:
            raise Failed(_("яркость 0–3, пауза 0–5"))
        self.config.data["slash"].update(mode=mode, brightness=int(brightness), interval=int(interval))
        if not self.apply_slash():
            raise Failed(_("Slash не ответила (журнал демона)"))
        self.config.save()
        self._changed()

    def do_SetSlashOptions(self, on_battery, lid_closed):
        self.config.data["slash"].update(on_battery=bool(on_battery), lid_closed=bool(lid_closed))
        if not self.apply_slash():
            raise Failed(_("Slash не ответила (журнал демона)"))
        self.config.save()
        self._changed()

    def do_GetHistory(self):
        return json.dumps(self.history.dump())

    def do_SetLanguage(self, lang):
        from .. import i18n
        if lang not in i18n.LANGUAGES:
            raise Failed(_("язык: {0}").format(", ".join(i18n.LANGUAGES)))
        self.config.data["language"] = lang
        self.config.save()
        self._changed()
        if lang != i18n.LANG:
            log.info(_("язык → %s, перезапускаю демон"), lang)
            GLib.timeout_add(300, self._restart_self)    # когда ответ клиенту уже ушёл

    def _restart_self(self):
        """Перезапуск на новом языке. Под systemd — через systemd (служба типа dbus: если процесс сам
        отпустит имя на шине, systemd сочтёт её завершённой и остановит). Без systemd — exec себя."""
        import os
        import sys
        if os.environ.get("INVOCATION_ID"):
            self.bus.call("org.freedesktop.systemd1", "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager",
                          "RestartUnit", GLib.Variant("(ss)", ("asus-helperd.service", "replace")),
                          None, Gio.DBusCallFlags.NONE, -1, None, None)
        else:
            os.execv(sys.executable, [sys.executable, "-m", "asushelper.daemon", *sys.argv[1:]])
        return GLib.SOURCE_REMOVE

    def do_SetKeyboardTimeout(self, ac, battery):
        if ac > 3600 or battery > 3600:
            raise Failed(_("не больше часа (3600 с)"))
        self.config.data["keyboard"].update(timeout_ac=int(ac), timeout_battery=int(battery))
        self.config.save()
        if self.idle:
            self.idle.activity()
        self._changed()

    def do_SetKeyboardBrightness(self, level):
        if not aura.set_brightness(level):
            raise Failed(_("подсветка клавиатуры не найдена"))
        self.config.data["keyboard"]["brightness"] = (aura.brightness() or {}).get("value", level)
        self.config.save()
        self._changed()

    def do_SetAura(self, mode, color, color2, speed):
        if mode not in aura.MODES:
            raise Failed(_("эффект: {0}").format(', '.join(aura.MODES)))
        if speed not in aura.SPEEDS:
            raise Failed(_("скорость: {0}").format(', '.join(aura.SPEEDS)))
        try:
            aura.parse_color(color)
            aura.parse_color(color2 or "#000000")
        except ValueError as e:
            raise Failed(str(e))
        k = self.config.data["keyboard"]
        k.update(mode=mode, color=color.upper(), color2=(color2 or "#000000").upper(), speed=speed)
        if not aura.apply(k):
            raise Failed(_("клавиатура Aura не ответила (журнал демона)"))
        self.config.save()
        self._changed()

    def do_SetAuraPower(self, awake, boot, sleep, shutdown):
        k = self.config.data["keyboard"]
        k.update(awake=awake, boot=boot, sleep=sleep, shutdown=shutdown)
        if not aura.apply(k):
            raise Failed(_("клавиатура Aura не ответила (журнал демона)"))
        self.config.save()
        self._changed()

    def _save_and_reapply(self, profile):
        self.config.save()
        if profile == self.modes.current:
            self.modes.reapply(_("изменены настройки режима {0}").format(profile))
        else:
            self._changed()


def sysfs_path(p: str) -> str:
    from . import sysfs
    return sysfs.path(p)


def check_profile(p):
    if p not in PROFILES:
        raise Failed(_("неизвестный режим «{0}» (есть: {1})").format(p, ', '.join(PROFILES)))


def check_fan(f):
    if f not in hw.curve_fans():
        raise Failed(_("неизвестный вентилятор «{0}» (есть: {1})").format(f, ', '.join(hw.curve_fans())))


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
            log.warning(_("polkit недоступен: %s"), e.message)
            ok = False
        done(ok)

    bus.call("org.freedesktop.PolicyKit1", "/org/freedesktop/PolicyKit1/Authority",
             "org.freedesktop.PolicyKit1.Authority", "CheckAuthorization",
             GLib.Variant("((sa{sv})sa{ss}us)", (subject, action, {}, 1, "")),
             GLib.VariantType("((bba{ss}))"), Gio.DBusCallFlags.NONE, -1, None, finish)
