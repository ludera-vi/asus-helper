"""Режимы производительности: что и в каком порядке применять.

Порядок как в G-Helper (ModeControl.SetPerformanceMode): сначала режим BIOS, через 100 мс кривые
вентиляторов, ещё через секунду лимиты мощности. Если писать всё сразу, BIOS при смене режима
затирает только что записанные кривые и лимиты.

Ядро само переключает режим по Fn+F5 и при этом выключает свои кривые вентиляторов, поэтому
демон следит за platform_profile и после любой смены режима применяет его настройки заново.
"""
import logging
import time
import os
import subprocess

from gi.repository import GLib

from .. import PROFILES
from . import hardware as hw
from . import sysfs
from .config import Config
from ..i18n import _

log = logging.getLogger(__name__)

FANS_DELAY_MS = 100
POWER_DELAY_MS = 1000
# Fn+F5 жмут несколько раз подряд — применяем, когда нажатия закончились
HOTKEY_DEBOUNCE_MS = 600


class Modes:
    def __init__(self, config: Config, on_change):
        self.config = config
        self.on_change = on_change   # вызывается после любой смены состояния (для сигналов D-Bus)
        self.ac = hw.on_ac()
        self.current = hw.profile()
        self._expected = None        # режим, который записали мы сами (его уведомление не обрабатываем)
        self._timers: list[int] = []
        self._debounce = 0
        self._watch_profile()

    # ---------- публичное ----------
    def set_profile(self, name: str, remember: bool = True) -> None:
        """Включить режим вручную (из приложения, CLI или KDE). Запоминается для текущего питания."""
        if name not in PROFILES:
            raise ValueError(_("неизвестный режим «{0}»").format(name))
        if remember:
            self.config.remember_profile(self.ac, name)
            self.config.save()
        self._apply(name, write_profile=True)

    def cycle_profile(self) -> str:
        i = PROFILES.index(self.current) if self.current in PROFILES else 0
        name = PROFILES[(i + 1) % len(PROFILES)]
        self.set_profile(name)
        return name

    def reapply(self, reason: str) -> None:
        """Применить текущий режим заново (после сна, после изменения настроек режима)."""
        log.info(_("применяю режим заново: %s"), reason)
        self._apply(hw.profile() or "balanced", write_profile=False)

    def power_source_changed(self, ac: bool) -> None:
        if ac == self.ac:
            return
        self.ac = ac
        log.info(_("питание: %s"), _("сеть") if ac else _("батарея"))
        self._nvidia_powerd(ac)
        if self.config.data["auto_profile"]:
            self._apply(self.config.profile_for(ac), write_profile=True)
        else:
            # min/max лимитов мощности на сети и батарее разные — пересчитываем
            self._schedule(POWER_DELAY_MS, self._apply_power, self.current)
        self.on_change()

    def startup(self) -> None:
        name = self.config.profile_for(self.ac) if self.config.data["auto_profile"] else (hw.profile() or "balanced")
        log.info(_("старт: питание %s, режим %s"), _("сеть") if self.ac else _("батарея"), name)
        self._nvidia_powerd(self.ac)
        self.learn_factory_curves()
        self._apply(name, write_profile=True)

    def learn_factory_curves(self) -> None:
        """Заводские кривые вентиляторов всех режимов — сразу при старте, а не когда режим впервые включат:
        иначе редактору кривых «Турбо» не с чего начать. BIOS отдаёт кривую только текущего режима, поэтому
        на долю секунды включаем каждый ещё не изученный режим; нужный режим ставится сразу после."""
        if not hw.has_fan_curves():
            return
        fans = hw.curve_fans()
        cache = self.config.data.setdefault("factory_curves", {})
        missing = [p for p in PROFILES if p in hw.profile_choices() and any(f not in cache.get(p, {}) for f in fans)]
        for name in missing:
            if hw.profile() != name and not hw.set_profile(name):
                continue
            time.sleep(FANS_DELAY_MS / 1000)
            for fan in fans:
                if c := hw.factory_fan_curve(fan):
                    cache.setdefault(name, {})[fan] = {"temp": c["temp"], "pwm": c["pwm"]}
            log.info(_("%s: запомнены заводские кривые %s"), name, ", ".join(cache.get(name, {})))
        if missing:
            self.config.save()

    # ---------- применение ----------
    def _apply(self, name: str, write_profile: bool) -> None:
        self._cancel_timers()
        if write_profile and hw.profile() != name:
            if self._write_profile(name):
                self._schedule(FANS_DELAY_MS, self._apply_fans, name)
                self._schedule(FANS_DELAY_MS + POWER_DELAY_MS, self._apply_power, name)
            else:
                # режима BIOS нет у ноутбука: кривые вентиляторов — от другого режима, их не трогаем
                self._apply_power(name)
        else:
            # режим BIOS уже нужный — ждать нечего
            self._apply_fans(name)
            self._apply_power(name)
        self.current = name
        self.on_change()

    def _write_profile(self, name: str) -> bool:
        log.info(_("режим → %s"), name)
        self._expected = name
        if hw.set_profile(name):
            return True
        self._expected = None
        log.warning(_("режим BIOS «%s» не включился — применяю только настройки процессора и мощности"), name)
        return False

    def _apply_fans(self, name: str) -> None:
        if not hw.has_fan_curves():
            return
        present = hw.curve_fans()
        curves = {f: c for f in present
                  if (c := self.config.profile(name)["fan_curves"].get(f)) and c.get("enabled", True)}
        # Сначала вернуть BIOS-кривые, потом ставить свои: ядро при pwmN_enable=2 заново пишет режим
        # в BIOS, а это сбрасывает свою кривую и у другого вентилятора.
        factory = self.config.data.setdefault("factory_curves", {}).setdefault(name, {})
        learned = False
        for fan in present:
            if fan not in factory:
                # запомнить заводскую кривую этого режима (сброс точек в ядре → чтение → кривая BIOS);
                # и у вентиляторов со своей кривой — она будет записана ниже, после всех сбросов
                if c := hw.factory_fan_curve(fan):
                    factory[fan] = {"temp": c["temp"], "pwm": c["pwm"]}
                    learned = True
            elif fan not in curves and (hw.fan_curve(fan) or {}).get("enabled"):
                hw.set_fan_curve_mode(fan, hw.CURVE_BIOS)
        if learned:
            log.info(_("%s: запомнены заводские кривые %s"), name, ", ".join(factory))
            self.config.save()
        for fan, c in curves.items():
            hw.set_fan_curve(fan, c["temp"], c["pwm"])
        log.info(_("%s: кривые вентиляторов применены"), name)

    def _apply_power(self, name: str) -> None:
        self._nvidia_powerd(self.ac)
        hw.set_epp(self.config.epp(name))
        hw.set_turbo(self.config.cpu_boost(name))
        # Каждый лимит: заданный для этого режима или заводской (default_value от BIOS). BIOS сам их при смене
        # режима не возвращает — без этого лимит одного режима «перетекал» бы в другой.
        mine = self.config.profile(name)["power_limits"]
        for attr, a in hw.power_limits().items():
            if a["min"] is None or a["max"] is None or a["max"] <= a["min"]:
                continue
            want = mine.get(attr)
            if want is None:
                want = a["default"]
            if want is not None:
                hw.set_armoury(attr, want)
        self.on_change()

    # ---------- таймеры ----------
    def _schedule(self, delay_ms: int, fn, *args) -> None:
        def run():
            self._timers.remove(tid)
            fn(*args)
            return GLib.SOURCE_REMOVE
        tid = GLib.timeout_add(delay_ms, run)
        self._timers.append(tid)

    def _cancel_timers(self) -> None:
        for t in self._timers:
            GLib.source_remove(t)
        self._timers.clear()

    # ---------- Fn+F5: ядро меняет режим само ----------
    def _watch_profile(self) -> None:
        # ядро вызывает sysfs_notify для platform_profile → POLLPRI
        try:
            self._profile_fd = os.open(sysfs.path(hw.PROFILE), os.O_RDONLY)
        except OSError as e:
            log.error(_("не могу следить за %s: %s"), hw.PROFILE, e)
            return
        os.read(self._profile_fd, 64)
        GLib.io_add_watch(self._profile_fd, GLib.PRIORITY_DEFAULT,
                          GLib.IOCondition.PRI | GLib.IOCondition.ERR, self._on_profile_event)

    def _on_profile_event(self, fd, _cond) -> bool:
        os.lseek(fd, 0, os.SEEK_SET)
        name = os.read(fd, 64).decode().strip()
        name = hw.FROM_KERNEL.get(name, name)
        if name == self._expected:
            self._expected = None
            return True
        if name == self.current or name not in PROFILES:
            return True
        log.info(_("режим сменился снаружи (Fn+F5?): %s"), name)
        self.current = name
        self._cancel_timers()   # не применять настройки прошлого режима
        self.on_change()        # приложение сразу показывает новый режим
        if self._debounce:
            GLib.source_remove(self._debounce)
        self._debounce = GLib.timeout_add(HOTKEY_DEBOUNCE_MS, self._hotkey_settled)
        return True

    def _hotkey_settled(self) -> bool:
        self._debounce = 0
        name = hw.profile()
        if name in PROFILES:
            self.config.remember_profile(self.ac, name)
            self.config.save()
            self._apply(name, write_profile=False)
        return GLib.SOURCE_REMOVE

    # ---------- nvidia-powerd ----------
    def _nvidia_powerd(self, ac: bool) -> None:
        if not self.config.data["stop_nvidia_powerd_on_battery"] or sysfs.ROOT:
            return
        if subprocess.run(["systemctl", "is-enabled", "-q", "nvidia-powerd"]).returncode != 0:
            return
        # Dynamic Boost нужен только в Турбо от сети. В остальное время nvidia-powerd постоянно опрашивает
        # видеокарту и не даёт ей уснуть (D3cold) — это лишние ватты при простое.
        dgpu_off = (hw.armoury_attr("dgpu_disable") or {}).get("value") == 1
        want = ac and not dgpu_off and self.current == "performance"
        running = subprocess.run(["systemctl", "is-active", "-q", "nvidia-powerd"]).returncode == 0
        if want != running:
            log.info("nvidia-powerd: %s", _("запускаю (Турбо от сети)") if want else _("останавливаю — NVIDIA сможет уснуть"))
            subprocess.run(["systemctl", "reset-failed", "nvidia-powerd"], capture_output=True)
            subprocess.Popen(["systemctl", "--no-block", "start" if want else "stop", "nvidia-powerd"])
