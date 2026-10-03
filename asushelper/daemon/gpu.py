"""Видеокарта NVIDIA: Eco (выключена через BIOS) и Стандарт (гибрид) — без перезагрузки.

Перенос gpu-eco из gpu-switch. Выключение: проверить MUX и программы на NVIDIA → остановить
nvidia-powerd/persistenced → выгрузить драйвер → убрать карту с шины PCI → dgpu_disable=1.
Включение: dgpu_disable=0 → пересканировать шину → загрузить драйвер → запустить сервисы.
Если шаг не удался, всё возвращается как было.

«Призрак»: если ноутбук включили в Eco, BIOS всё равно показывает обесточенную карту на шине,
и ядро ждёт её по 65 с при каждом выходе из сна. fixup() убирает её с шины.
"""
import fcntl
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
    def __init__(self, text: str, can_force: bool = False):
        super().__init__(text)
        self.can_force = can_force


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
    """Захват устройств, которые шлют ложную клавишу дисплея; отпускает с задержкой."""

    def __init__(self):
        self.fds: dict[str, int] = {}     # event-узел → дескриптор
        self.grab_new()

    def grab_new(self) -> None:
        for e in sysfs.find("/sys/class/input/event*"):
            node = os.path.basename(e)
            if node in self.fds or sysfs.read(e + "/device/name") not in SWALLOW_DEVICES:
                continue
            try:
                fd = os.open("/dev/input/" + node, os.O_RDONLY | os.O_NONBLOCK)
                fcntl.ioctl(fd, EVIOCGRAB, 1)
                self.fds[node] = fd
            except OSError as err:
                log.info(_("не захватить %s: %s"), node, err)

    def release_later(self, delay: float = 2.0) -> None:
        """Событие от BIOS приходит с задержкой, а при включении NVIDIA появляется новый «Video Bus» —
        его тоже держим, потом отпускаем всё."""
        def run():
            time.sleep(delay)
            self.grab_new()
            time.sleep(delay)
            for fd in self.fds.values():
                try:
                    os.read(fd, 4096 * 24)      # выбросить накопленное
                except OSError:
                    pass
                os.close(fd)                    # закрытие снимает захват
            self.fds.clear()
        threading.Thread(target=run, daemon=True).start()


def _run(*cmd) -> bool:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log.warning("%s: %s", " ".join(cmd), (r.stderr or r.stdout).strip())
    return r.returncode == 0


def _start_services() -> None:
    for s in SERVICES:
        if subprocess.run(["systemctl", "is-enabled", "-q", s]).returncode == 0:
            # после частых переключений systemd считает, что сервис «падает», и не даёт запустить
            subprocess.run(["systemctl", "reset-failed", s], capture_output=True)
            _run("systemctl", "start", s)


def _load_driver() -> bool:
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


def turn_off(force: bool = False, ignore_displays: bool = False) -> None:
    """Eco. GpuError с понятным текстом, если нельзя; при ошибке всё возвращается как было."""
    gpu = find_gpu()
    if gpu and not ignore_displays and (ext := external_displays(gpu)):
        raise GpuError(_("К NVIDIA подключён монитор ({0}) — после выключения он погаснет").format(', '.join(ext)))
    if bios_off() and (gpu is None or not sysfs.exists(f"{PCI}/{gpu}/driver")):
        fixup()
        return
    if not mux_hybrid():
        raise GpuError(_("MUX в режиме «только NVIDIA» — сначала переключите MUX в гибрид и перезагрузитесь"))

    if gpu:
        busy = holders(gpu)
        if busy:
            names = ", ".join(sorted({c for _, c in busy}))
            protected = sorted({c for p, c in busy if is_protected(p, c)})
            if protected:
                # закрывать нельзя — это рабочий стол или система
                raise GpuError(_("NVIDIA держит рабочий стол ({0}). Он отпустит её после выхода из сеанса и входа снова — один раз после установки Asus-helper").format(', '.join(protected)))
            if not force:
                raise GpuError(_("NVIDIA используют: {0}").format(names), can_force=True)
            log.info(_("закрываю программы на NVIDIA: %s"), names)
            for pid, _comm in busy:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
            time.sleep(3)
            if busy := holders(gpu):
                raise GpuError(_("программы не закрылись: ") + ", ".join(sorted({c for _, c in busy})))

        log.info(_("останавливаю сервисы NVIDIA"))
        subprocess.run(["systemctl", "stop", *SERVICES], capture_output=True)
        log.info(_("выгружаю драйвер NVIDIA"))
        if not _run("modprobe", "-r", *MODULES_UNLOAD):
            _load_driver()
            _start_services()
            raise GpuError(_("драйвер не выгрузился (что-то ещё использует карту) — всё возвращено как было"))
        log.info(_("убираю NVIDIA с шины PCI"))
        _remove_from_bus(gpu)

    log.info(_("отключаю NVIDIA в BIOS"))
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
    log.info(_("включаю NVIDIA в BIOS"))
    if not sysfs.write(_attr("dgpu_disable"), 0):
        raise GpuError(_("BIOS отказал во включении"))
    for _attempt in range(10):
        time.sleep(1)
        sysfs.write("/sys/bus/pci/rescan", 1)
        if find_gpu():
            break
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
        can_force = False
        try:
            with open(sysfs.path(LOCK) if sysfs.ROOT else LOCK, "w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise GpuError(_("видеокарту уже переключает другая программа (gpu-eco?)"))
                guard = None if sysfs.ROOT else HotkeyGuard()
                try:
                    (turn_off(force, ignore_displays) if want_off else turn_on())
                finally:
                    if guard:
                        guard.release_later()
        except GpuError as e:
            err = str(e)
            can_force = e.can_force
            log.warning(_("видеокарта: %s"), err)
        except Exception as e:
            err = _("внутренняя ошибка: {0}").format(e)
            log.exception(_("видеокарта"))

        def done():
            self.busy = False
            self.last_error = err
            self.can_force = can_force
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
