"""Видеокарта NVIDIA: Eco (выключена через BIOS) и Стандарт (гибрид) — без перезагрузки.

Перенос gpu-eco из gpu-switch. Выключение: проверить MUX и программы на NVIDIA → остановить
nvidia-powerd/persistenced → выгрузить драйвер → убрать карту с шины PCI → dgpu_disable=1.
Включение: dgpu_disable=0 → пересканировать шину → загрузить драйвер → запустить сервисы.
Если шаг не удался, всё возвращается как было.

«Призрак»: если ноутбук включили в Eco, BIOS всё равно показывает обесточенную карту на шине,
и ядро ждёт её по 65 с при каждом выходе из сна. fixup() убирает её с шины.
"""
import fcntl
import functools
import logging
import os
import signal
import subprocess
import threading
import time

from . import sysfs
from ..i18n import _

log = logging.getLogger(__name__)

ARMOURY = "/sys/class/firmware-attributes/asus-armoury/attributes"
PCI = "/sys/bus/pci/devices"
SERVICES = ("nvidia-powerd", "nvidia-persistenced")
MODULES_UNLOAD = ("nvidia_drm", "nvidia_modeset", "nvidia_uvm", "nvidia")
MODULES_LOAD = ("nvidia", "nvidia_modeset", "nvidia_drm", "nvidia_uvm")
# общий с gpu-eco замок: пока старый скрипт установлен, они не должны переключать одновременно
LOCK = "/run/gpu-eco.lock"


class GpuError(Exception):
    """can_force — карту держат обычные программы пользователя, их можно закрыть и выключить."""
    def __init__(self, text: str, can_force: bool = False, busy: bool = False):
        super().__init__(text)
        self.can_force = can_force
        self.busy = busy            # карту кто-то занял — позже может освободиться, можно повторить


# Рабочий стол и система: их нельзя закрывать никогда — это обрушит сеанс или всю систему.
# Если NVIDIA держат они, значит рабочий стол запущен не только на встроенной видеокарте.
DESKTOP = {"kwin_wayland", "kwin_x11", "kwin_wayland_wrapper", "Xwayland", "Xorg", "X", "plasmashell",
           "ksmserver", "startplasma-wayland", "startplasma-x11", "gnome-shell", "mutter", "sway", "Hyprland",
           "sddm", "sddm-helper", "sddm-greeter", "gdm", "gdm-wayland-session", "systemd", "systemd-logind"}


def is_protected(pid: int, comm: str) -> bool:
    """Процесс, который нельзя закрыть: системный (root, PID 1) или часть рабочего стола."""
    if pid == 1 or comm in DESKTOP:
        return True
    try:
        return os.stat(f"/proc/{pid}").st_uid == 0
    except OSError:
        return False


def _attr(name: str) -> str:
    """Путь к dgpu_disable / gpu_mux_mode: asus-armoury (новые ядра) или asus-nb-wmi."""
    p = f"{ARMOURY}/{name}/current_value"
    return p if sysfs.exists(p) else f"/sys/devices/platform/asus-nb-wmi/{name}"


def supported() -> bool:
    """Есть флаг BIOS и есть что выключать: NVIDIA на шине или уже выключена (Eco).
    Видеокарты AMD не поддерживаются: их драйвер общий со встроенной — выгрузить его нельзя."""
    return sysfs.exists(_attr("dgpu_disable")) and (bios_off() or find_gpu() is not None)


def bios_off() -> bool:
    return sysfs.read(_attr("dgpu_disable")) == "1"


def mux_hybrid() -> bool:
    """MUX в гибриде (Optimus). 0 — только NVIDIA (Ultimate): выключать карту нельзя."""
    return sysfs.read(_attr("gpu_mux_mode"), "1") != "0"


VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}
PCI_IDS = ("/usr/share/hwdata/pci.ids", "/usr/share/misc/pci.ids")


@functools.lru_cache(maxsize=16)
def pci_model(vendor: str, device: str) -> str | None:
    """Название из базы pci.ids: «GeForce RTX 4080 Max-Q / Mobile», «Intel Arc Graphics»…"""
    v, d = vendor.replace("0x", "").lower(), device.replace("0x", "").lower()
    for path in PCI_IDS:
        try:
            with open(sysfs.path(path), encoding="utf-8", errors="replace") as f:
                in_vendor = False
                for line in f:
                    if line.startswith("#") or not line.strip():
                        continue
                    if not line.startswith("\t"):
                        in_vendor = line[:4].lower() == v
                    elif in_vendor and not line.startswith("\t\t") and line[1:5].lower() == d:
                        name = line[5:].strip()
                        # «AD104M [GeForce RTX 4080 Max-Q / Mobile]» → то, что в скобках
                        return name[name.index("[") + 1:name.rindex("]")] if "[" in name and "]" in name else name
        except OSError:
            continue
    return None


def display_gpus() -> dict:
    """{"igpu": {vendor, model}, "dgpu": {vendor, model} | None} — видеокарты на шине PCI сейчас."""
    out = {"igpu": None, "dgpu": None}
    for d in sysfs.find(PCI + "/*"):
        if not (sysfs.read(d + "/class") or "").startswith("0x03"):
            continue
        vendor, device = sysfs.read(d + "/vendor") or "", sysfs.read(d + "/device") or ""
        name = VENDORS.get(vendor, vendor)
        model = pci_model(vendor, device) or ""
        # «Intel Arc Graphics» — как есть; «Phoenix1» → «AMD Phoenix1»; «GeForce RTX 4080» → «NVIDIA GeForce…»
        full = model if name.lower() in model.lower() else f"{name} {model}".strip()
        info = {"vendor": name, "model": full}
        key = "igpu" if sysfs.read(d + "/boot_vga") == "1" else "dgpu"
        if out[key] is None:
            out[key] = info
    return out


def igpu_name() -> str:
    """Встроенная видеокарта (та, что ведёт экран при загрузке): Intel или AMD."""
    for d in sysfs.find(PCI + "/*"):
        if (sysfs.read(d + "/class") or "").startswith("0x03") and sysfs.read(d + "/boot_vga") == "1":
            return VENDORS.get(sysfs.read(d + "/vendor") or "", _("встроенная"))
    for d in sysfs.find(PCI + "/*"):
        if (sysfs.read(d + "/class") or "").startswith("0x03") and sysfs.read(d + "/vendor") != "0x10de":
            return VENDORS.get(sysfs.read(d + "/vendor") or "", _("встроенная"))
    return _("встроенная")


def find_gpu() -> str | None:
    """PCI-адрес NVIDIA (например 0000:01:00.0) или None."""
    for d in sysfs.find(PCI + "/*"):
        if sysfs.read(d + "/vendor") == "0x10de" and (sysfs.read(d + "/class") or "").startswith("0x03"):
            return os.path.basename(d)
    return None


def state() -> str:
    """off — выключена в BIOS; suspended/active — включена (спит/работает); missing — нет на шине."""
    if bios_off():
        return "off"
    gpu = find_gpu()
    if gpu is None:
        return "missing"
    return sysfs.read(f"{PCI}/{gpu}/power/runtime_status", "unknown")


def external_displays(gpu: str | None = None) -> list[str]:
    """Мониторы, подключённые к выходам NVIDIA (HDMI, DP). Встроенный экран (eDP) через MUX не считаем:
    им всё равно управляет встроенная видеокарта. После Eco такие мониторы погаснут."""
    gpu = gpu or find_gpu()
    if gpu is None:
        return []
    out = []
    for card in sysfs.find(f"{PCI}/{gpu}/drm/card*"):
        for conn in sysfs.find(card + "/card*-*"):
            name = os.path.basename(conn).split("-", 1)[1]
            if not name.startswith("eDP") and sysfs.read(conn + "/status") == "connected":
                out.append(name)
    return out


# systemd и systemd-logind держат видеокарту не для себя, а за рабочий стол (logind выдаёт KWin доступ к
# устройству и хранит его копию). Человеку в списке «кто занял NVIDIA» они только мешают.
SESSION_KEEPERS = ("systemd", "systemd-logind")


def names(busy: list[tuple[int, str]]) -> list[str]:
    """Имена для показа: без служебных хранителей сеанса, если есть кто-то ещё."""
    all_ = sorted({c for _, c in busy})
    shown = [c for c in all_ if c not in SESSION_KEEPERS]
    return shown or all_


def holders(gpu: str | None = None) -> list[tuple[int, str]]:
    """Процессы, у которых открыта NVIDIA: [(pid, имя)]. Карту не будит — смотрит только /proc."""
    gpu = gpu or find_gpu()
    if gpu is None:
        return []
    nodes = {f"/dev/{n}" for n in os.listdir(sysfs.path("/dev")) if n.startswith("nvidia")} \
        if os.path.isdir(sysfs.path("/dev")) else set()
    drm = sysfs.path(f"{PCI}/{gpu}/drm")
    if os.path.isdir(drm):
        nodes |= {f"/dev/dri/{n}" for n in os.listdir(drm)}
    if not nodes:
        return []
    out = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            if comm in SERVICES:
                continue
            for fd in os.listdir(f"/proc/{pid}/fd"):
                if os.readlink(f"/proc/{pid}/fd/{fd}") in nodes:
                    out.append((int(pid), comm))
                    break
        except OSError:
            continue
    return out


# ---------- ложная клавиша «переключить дисплей» ----------
# Когда видеокарта выключается или включается, BIOS сообщает ACPI-видео о смене вывода, и устройство
# «Video Bus» шлёт клавишу KEY_SWITCHVIDEOMODE (как Meta+P) — KDE в ответ открывает выбор экрана.
# На время переключения забираем такие устройства себе (EVIOCGRAB): клавиша до рабочего стола не дойдёт.
EVIOCGRAB = 0x40044590
SWALLOW_DEVICES = ("Video Bus", "Asus WMI hotkeys")


class HotkeyGuard:
    """Захват устройств, которые шлют ложную клавишу дисплея; отпускает с задержкой.
    Один на все переключения: если новое началось, пока прежнее ещё не отпустило устройства, —
    захват продолжается, а не обрывается посреди нового переключения."""
    _current: "HotkeyGuard | None" = None
    _lock = threading.Lock()

    def __init__(self):
        self.fds: dict[str, int] = {}     # event-узел → дескриптор
        self.users = 0

    @classmethod
    def acquire(cls) -> "HotkeyGuard":
        with cls._lock:
            g = cls._current = cls._current or cls()
            g.users += 1
            g.grab_new()
            return g

    def grab_new(self) -> None:
        for e in sysfs.find("/sys/class/input/event*"):
            node = os.path.basename(e)
            if node in self.fds or sysfs.read(e + "/device/name") not in SWALLOW_DEVICES:
                continue
            try:
                fd = os.open("/dev/input/" + node, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as err:
                log.info(_("не захватить %s: %s"), node, err)
                continue
            try:
                fcntl.ioctl(fd, EVIOCGRAB, 1)
                self.fds[node] = fd
            except OSError as err:
                os.close(fd)
                log.info(_("не захватить %s: %s"), node, err)

    def release_later(self, delay: float = 2.0) -> None:
        """Событие от BIOS приходит с задержкой, а при включении NVIDIA появляется новый «Video Bus» —
        его тоже держим, потом отпускаем всё (если других переключений уже нет)."""
        def run():
            time.sleep(delay)
            with self._lock:
                self.grab_new()
            time.sleep(delay)
            with self._lock:
                self.users -= 1
                if self.users > 0:
                    return
                for fd in self.fds.values():
                    try:
                        os.read(fd, 4096 * 24)      # выбросить накопленное
                    except OSError:
                        pass
                    os.close(fd)                    # закрытие снимает захват
                self.fds.clear()
                if HotkeyGuard._current is self:
                    HotkeyGuard._current = None
        threading.Thread(target=run, daemon=True).start()


def _run(*cmd) -> bool:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning("%s: %s", " ".join(cmd), (r.stderr or r.stdout).strip())
    return r.returncode == 0


# Выгрузка драйвера может навсегда застрять в ядре (процесс в состоянии D: драйвер ждёт событий ACPI,
# которые ядро так и не обработало). Убить такой процесс нельзя, ждать его — тоже: демон вечно
# «переключался» бы. Ждём разумное время, дальше — ошибка, а новые переключения до перезагрузки не начинаем.
UNLOAD_TIMEOUT = 60
stuck: subprocess.Popen | None = None


def is_stuck() -> bool:
    return stuck is not None and stuck.poll() is None


def _unload_driver() -> bool:
    global stuck
    cmd = ["modprobe", "-r", *MODULES_UNLOAD]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        p.wait(UNLOAD_TIMEOUT)
    except subprocess.TimeoutExpired:
        stuck = p
        log.error(_("выгрузка драйвера NVIDIA зависла в ядре (%s с)"), UNLOAD_TIMEOUT)
        raise GpuError(_("драйвер NVIDIA завис при выгрузке (ошибка в ядре или драйвере). Нужна перезагрузка; "
                         "до неё видеокарту не переключаю"))
    if p.returncode != 0:
        log.warning("%s: %s", " ".join(cmd), p.stderr.read().strip())
    return p.returncode == 0


# После включения или выключения BIOS ещё несколько секунд обрабатывает событие (подключает карту к шине
# или снимает с неё питание через ACPI), а драйвер запускает прошивку видеокарты. Новое переключение в этот
# момент может намертво застрять в ядре (так и было: выключение сразу после включения). Поэтому между
# любыми двумя переключениями — пауза.
SETTLE_S = 20
_changed_at: float | None = None      # только настоящие переключения; при старте демона паузы нет


def _now() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)   # вместе со временем сна, в отличие от monotonic


def _settle() -> None:
    if _changed_at is not None and (wait := _changed_at + SETTLE_S - _now()) > 0:
        log.info(_("видеокарта только что переключалась — жду %d с"), round(wait))
        time.sleep(wait)


def _mark() -> None:
    global _changed_at
    _changed_at = _now()


def _start_services() -> None:
    for s in SERVICES:
        if subprocess.run(["systemctl", "is-enabled", "-q", s]).returncode == 0:
            # после частых переключений systemd считает, что сервис «падает», и не даёт запустить
            subprocess.run(["systemctl", "reset-failed", s], capture_output=True)
            _run("systemctl", "start", s)


def _load_driver() -> bool:
    _mark()
    return _run("modprobe", "-a", *MODULES_LOAD)


def _remove_from_bus(gpu: str) -> None:
    """Сначала звук/USB-C (.1, .2 …), потом саму видеокарту (.0)."""
    base = gpu.rsplit(".", 1)[0]
    for f in sorted(sysfs.find(f"{PCI}/{base}.*"), reverse=True):
        if sysfs.exists(f + "/remove"):
            sysfs.write(f + "/remove", 1)


def fixup() -> bool:
    """Убрать с шины обесточенную в BIOS карту. True — что-то убрали."""
    gpu = find_gpu()
    if not bios_off() or gpu is None:
        return False
    if sysfs.exists(f"{PCI}/{gpu}/driver"):
        log.info(_("NVIDIA выключена в BIOS, но драйвер держит карту — не трогаю"))
        return False
    log.info(_("убираю выключенную NVIDIA с шины PCI (иначе выход из сна ждёт её 65 с)"))
    _remove_from_bus(gpu)
    return True


def _unload_and_remove(gpu: str) -> None:
    log.info(_("останавливаю сервисы NVIDIA"))
    subprocess.run(["systemctl", "stop", *SERVICES], capture_output=True)
    log.info(_("выгружаю драйвер NVIDIA"))
    if not _unload_driver():
        _load_driver()
        _start_services()
        raise GpuError(_("драйвер не выгрузился (что-то ещё использует карту) — всё возвращено как было"), busy=True)
    log.info(_("убираю NVIDIA с шины PCI"))
    _remove_from_bus(gpu)


# Устройства NVIDIA на время выключения закрыты для всех, кроме root: иначе закрытая программа (или
# перезапущенный процесс браузера) сразу открыла бы карту снова и драйвер не выгрузился бы.
def _nvidia_nodes(gpu: str) -> list[str]:
    nodes = [f"/dev/{n}" for n in os.listdir("/dev") if n.startswith("nvidia") and n != "nvidia-caps"]
    drm = sysfs.path(f"{PCI}/{gpu}/drm")
    if os.path.isdir(drm):
        nodes += [f"/dev/dri/{n}" for n in os.listdir(drm) if n.startswith(("card", "renderD"))]
    return nodes


def _block_nodes(gpu: str) -> dict[str, int]:
    if sysfs.ROOT:
        return {}
    saved = {}
    for n in _nvidia_nodes(gpu):
        try:
            saved[n] = os.stat(n).st_mode & 0o7777
            os.chmod(n, 0)
        except OSError:
            pass
    return saved


def _unblock_nodes(saved: dict[str, int]) -> None:
    for n, mode in saved.items():
        try:
            os.chmod(n, mode)        # после выгрузки драйвера части узлов уже нет — это нормально
        except OSError:
            pass


def _close(busy: list[tuple[int, str]], gpu: str) -> bool:
    """SIGTERM, до 4 с подождать, оставшимся — SIGKILL. True — карту больше никто не держит."""
    for sig, wait in ((signal.SIGTERM, 4.0), (signal.SIGKILL, 2.0)):
        for pid, _comm in busy:
            try:
                os.kill(pid, sig)
            except OSError:
                pass
        end = time.monotonic() + wait
        while time.monotonic() < end:
            time.sleep(0.25)
            busy = [(p, c) for p, c in holders(gpu) if not is_protected(p, c)]
            if not busy:
                return True
    return False


def turn_off(force: bool = False, ignore_displays: bool = False) -> None:
    """Eco: карта выключается, кто бы её ни держал (кроме рабочего стола и системы — их закрыть нельзя).
    GpuError с понятным текстом, если нельзя; при ошибке всё возвращается как было. force оставлен для
    совместимости вызовов — программы на NVIDIA закрываются всегда."""
    gpu = find_gpu()
    if gpu and not ignore_displays and (ext := external_displays(gpu)):
        raise GpuError(_("К NVIDIA подключён монитор ({0}) — после выключения он погаснет").format(', '.join(ext)))
    if bios_off() and (gpu is None or not sysfs.exists(f"{PCI}/{gpu}/driver")):
        fixup()
        return
    if not mux_hybrid():
        raise GpuError(_("MUX в режиме «только NVIDIA» — сначала переключите MUX в гибрид и перезагрузитесь"))

    if gpu:
        _settle()                   # до проверки: за время паузы карту мог занять, например, экран входа
        busy = holders(gpu)
        if busy:
            listed = ", ".join(names(busy))
            protected = names([(p, c) for p, c in busy if is_protected(p, c)])
            if protected:
                # закрывать нельзя — это рабочий стол или система
                raise GpuError(_("NVIDIA держит рабочий стол ({0}). Он отпустит её после выхода из сеанса и входа снова — один раз после установки Asus-helper").format(', '.join(protected)), busy=True)
            # Обычные программы закрываем всегда (Eco должен выключать карту, кто бы её ни держал). Сначала
            # закрываем доступ к устройствам NVIDIA: служебный процесс отрисовки браузера или Electron
            # перезапустится сам и откроет уже только Intel — вкладки и окна не пропадут.
            log.info(_("закрываю программы на NVIDIA: %s"), listed)
            blocked = _block_nodes(gpu)
            if not _close(busy, gpu):
                _unblock_nodes(blocked)
                raise GpuError(_("программы не закрылись: ") + ", ".join(names(holders(gpu))), busy=True)
        else:
            blocked = _block_nodes(gpu)
        try:
            _unload_and_remove(gpu)
        finally:
            _unblock_nodes(blocked)

    _settle()
    log.info(_("отключаю NVIDIA в BIOS"))
    _mark()
    if not sysfs.write(_attr("dgpu_disable"), 1):
        sysfs.write("/sys/bus/pci/rescan", 1)
        _load_driver()
        _start_services()
        raise GpuError(_("BIOS отказал в отключении — всё возвращено как было"))
    time.sleep(1)
    if find_gpu():
        raise GpuError(_("карта всё ещё видна после отключения"))
    log.info(_("NVIDIA выключена (Eco)"))


def turn_on() -> None:
    if not bios_off() and find_gpu():
        return
    fixup()   # «призрак» помешал бы найти карту заново
    _settle()
    log.info(_("включаю NVIDIA в BIOS"))
    _mark()
    # BIOS отвечает на команду через 6–8 с (карту на шину он подключает раньше). Включённой считаем,
    # только когда BIOS ответил: до этого любое обращение к нему ждало бы своей очереди.
    if not sysfs.write(_attr("dgpu_disable"), 0):
        raise GpuError(_("BIOS отказал во включении"))
    for _attempt in range(10):
        if find_gpu():
            break
        time.sleep(1)
        sysfs.write("/sys/bus/pci/rescan", 1)
    else:
        raise GpuError(_("карта не появилась. Перезагрузите ноутбук — BIOS уже включил её"))
    log.info(_("загружаю драйвер NVIDIA"))
    if not _load_driver():
        raise GpuError(_("драйвер не загрузился (журнал: journalctl -b -k | grep -i nvidia)"))
    _start_services()
    log.info(_("NVIDIA включена (Стандарт)"))


class Switcher:
    """Переключение в отдельном потоке: главный цикл демона не ждёт modprobe и шину PCI."""

    def __init__(self, on_done):
        self.on_done = on_done      # on_done(error: str | None) — вызывается в главном потоке
        self.busy = False
        self.retryable = False      # последняя ошибка — «карту заняли», можно попробовать позже
        self.target: str | None = None
        self._error: str | None = None
        self._error_at = 0.0
        self.can_force = False

    # ошибка показывается минуту: потом она уже не про текущее состояние (вышли из сеанса, закрыли игру…)
    ERROR_TTL = 60

    @property
    def last_error(self) -> str | None:
        return self._error if time.monotonic() - self._error_at < self.ERROR_TTL else None

    @last_error.setter
    def last_error(self, v):
        self._error = v
        self._error_at = time.monotonic()

    def start(self, want_off: bool, force: bool = False, ignore_displays: bool = False) -> bool:
        if self.busy:
            return False
        self.busy = True
        self.target = "eco" if want_off else "standard"
        self.last_error = None
        self.can_force = False
        threading.Thread(target=self._work, args=(want_off, force, ignore_displays), daemon=True).start()
        return True

    def _work(self, want_off: bool, force: bool, ignore_displays: bool) -> None:
        from gi.repository import GLib
        err = None
        can_force = retryable = False
        try:
            with open(sysfs.path(LOCK) if sysfs.ROOT else LOCK, "w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise GpuError(_("видеокарту уже переключает другая программа (gpu-eco?)"))
                guard = None if sysfs.ROOT else HotkeyGuard.acquire()
                try:
                    (turn_off(force, ignore_displays) if want_off else turn_on())
                finally:
                    if guard:
                        guard.release_later()
        except GpuError as e:
            err = str(e)
            can_force, retryable = e.can_force, e.busy
            log.warning(_("видеокарта: %s"), err)
        except Exception as e:
            err = _("внутренняя ошибка: {0}").format(e)
            log.exception(_("видеокарта"))

        def done():
            self.busy = False
            self.last_error = err
            self.can_force = can_force
            self.retryable = retryable
            self.on_done(err)
            return GLib.SOURCE_REMOVE
        GLib.idle_add(done)


# ---------- рабочий стол только на встроенной видеокарте ----------
# KWin при запуске захватывает все видеокарты, и NVIDIA без выхода из сеанса уже не выключить.
# Служба KWin читает /run/asus-helper/kwin.env (EnvironmentFile в drop-in из пакета). Пишем туда
# «только встроенная» лишь когда это безопасно: есть NVIDIA, MUX в гибриде и экран ведёт встроенная
# видеокарта (/dev/dri/igpu от правила udev). Иначе файл пустой — KWin запускается как обычно,
# поэтому чёрного экрана не будет, даже если что-то пошло не так (или демон не запущен).
KWIN_ENV = "/run/asus-helper/kwin.env"
IGPU_LINK = "/dev/dri/igpu"


def kwin_env_lines() -> list[str]:
    if not (supported() and mux_hybrid()):
        return []
    link = sysfs.path(IGPU_LINK)
    if not os.path.exists(link):
        return []
    card = os.path.basename(os.path.realpath(link))
    if sysfs.read(f"/sys/class/drm/{card}/device/vendor") == "0x10de":   # «встроенная» оказалась NVIDIA
        return []
    return ["KWIN_DRM_DEVICES=" + IGPU_LINK,
            "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json",
            "__GLX_VENDOR_LIBRARY_NAME=mesa"]


def write_kwin_env() -> None:
    lines = kwin_env_lines()
    path = sysfs.path(KWIN_ENV)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(_("# Asus-helper: рабочий стол KDE только на встроенной видеокарте (см. gpu.py)\n"))
            f.write("".join(l + "\n" for l in lines))
    except OSError as e:
        log.warning(_("не записать %s: %s"), KWIN_ENV, e)
        return
    log.info(_("рабочий стол KDE: %s"), _("только встроенная видеокарта") if lines else _("как обычно (все видеокарты)"))
