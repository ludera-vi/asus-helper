"""Видеокарта NVIDIA: Eco (выключена через BIOS) и Стандарт (гибрид) — без перезагрузки.

Жёстко, как G-Helper. Выключение: закрыть программы на NVIDIA и хвосты прошлых попыток → остановить
nvidia-powerd/persistenced → снять карту с шины PCI (драйвер отпускает её, даже если его модуль занят) →
dgpu_disable=1 → выгрузить драйвер, если получится. Включение: dgpu_disable=0 → пересканировать шину →
драйвер (если не подхватил карту сам) → сервисы. Не получилось — всё возвращается как было.
Каждый шаг, который трогает ядро, ограничен по времени: зависнуть может ядро, но не демон.

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
    """Переключение не удалось; текст — для человека."""
    def __init__(self, text: str):
        super().__init__(text)


# Рабочий стол и система: их нельзя закрывать никогда — это обрушит сеанс или всю систему.
# Если NVIDIA держат они, значит рабочий стол запущен не только на встроенной видеокарте.
DESKTOP = {
    # KDE
    "kwin_wayland", "kwin_x11", "kwin_wayland_wrapper", "plasmashell", "ksmserver",
    "startplasma-wayland", "startplasma-x11",
    # X и Xwayland
    "Xwayland", "Xorg", "X",
    # другие рабочие столы и композиторы
    "gnome-shell", "mutter", "sway", "Hyprland", "niri", "cosmic-comp", "gamescope", "gamescope-wl",
    "labwc", "wayfire", "weston", "river", "hyprland", "dwl", "Xfwm4", "xfwm4", "marco",
    "muffin", "cinnamon", "budgie-wm", "openbox", "i3",
    # экраны входа
    "sddm", "sddm-helper", "sddm-greeter", "sddm-greeter-qt6", "gdm", "gdm-wayland-session", "gdm-x-session",
    "plasmalogin", "plasmalogin-helper", "plasma-login-greeter", "startplasma-login-wayland",
    "lightdm", "lightdm-gtk-greeter", "greetd", "ly", "regreet", "tuigreet",
    "systemd", "systemd-logind"}
# Ядро хранит имя процесса (/proc/PID/comm) обрезанным до 15 символов: kwin_wayland_wrapper → kwin_wayland_wr
COMM_LEN = 15
DESKTOP_COMM = {n[:COMM_LEN] for n in DESKTOP}
# Экраны входа работают от системных пользователей (sddm, gdm, plasmalogin…): UID ниже 1000
SYSTEM_UID_MAX = 999


def is_desktop(comm: str) -> bool:
    return comm[:COMM_LEN] in DESKTOP_COMM


def is_protected(pid: int, comm: str) -> bool:
    """Процесс, который нельзя закрыть: системный (root, системный пользователь, PID 1) или часть рабочего стола."""
    if pid == 1 or is_desktop(comm):
        return True
    try:
        return os.stat(f"/proc/{pid}").st_uid <= SYSTEM_UID_MAX
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


def driver(gpu: str | None = None) -> str | None:
    """Драйвер видеокарты: nvidia, nouveau… или None (не загружен)."""
    gpu = gpu or find_gpu()
    link = sysfs.path(f"{PCI}/{gpu}/driver") if gpu else None
    return os.path.basename(os.path.realpath(link)) if link and os.path.exists(link) else None


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


def program_name(pid: int, comm: str) -> str:
    """Имя программы для человека: по исполняемому файлу. У многих программ имя главного потока своё
    («GUI Thread», «MainThread»), а по файлу видно, что это steam, brave или davinci."""
    try:
        exe = os.path.basename(os.readlink(f"/proc/{pid}/exe")).removesuffix(" (deleted)")
    except OSError:
        return comm
    return exe or comm


def vram_by_pid() -> dict[int, int]:
    """Сколько видеопамяти NVIDIA занимает каждый процесс, МиБ (nvidia-smi; карта и так работает)."""
    import xml.etree.ElementTree as ET
    if sysfs.ROOT:
        return {}             # тесты: настоящую карту не трогаем
    try:
        out = subprocess.run(["nvidia-smi", "-q", "-x"], capture_output=True, text=True, timeout=5).stdout
        root = ET.fromstring(out)
    except (OSError, subprocess.TimeoutExpired, ET.ParseError):
        return {}
    usage = {}
    for p in root.iter("process_info"):
        try:
            pid = int(p.findtext("pid", ""))
            mib = int((p.findtext("used_memory") or "0").split()[0])
        except ValueError:
            continue
        usage[pid] = usage.get(pid, 0) + mib
    return usage


def user_programs(gpu: str | None = None) -> list[str]:
    """Программы пользователя на NVIDIA (без рабочего стола и системы) — первой та, что занимает больше
    всего видеопамяти. Их нужно закрыть, чтобы выключить карту."""
    busy = [(p, c) for p, c in holders(gpu) if not is_protected(p, c)]
    if not busy:
        return []
    vram = vram_by_pid()
    out: list[str] = []
    for pid, comm in sorted(busy, key=lambda h: -vram.get(h[0], 0)):
        if (name := program_name(pid, comm)) not in out:
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


# ---------- шаги, которые трогают ядро: каждый в своём процессе и с ограничением времени ----------
# Драйвер NVIDIA или BIOS могут зависнуть внутри ядра (процесс в состоянии D). Убить такой процесс нельзя
# ничем, поэтому поток демона сам в ядро не ходит: шаг выполняет дочерний процесс, демон ждёт его не дольше
# срока. Завис — до перезагрузки видеокарту не переключаем и говорим об этом прямо.
stuck: subprocess.Popen | None = None


def is_stuck() -> bool:
    return stuck is not None and stuck.poll() is None


def stuck_message() -> str:
    return _("драйвер NVIDIA завис в ядре (ошибка драйвера). Нужна перезагрузка; до неё видеокарту "
             "не переключаю")


def _kernel(cmd: list[str], timeout: float) -> bool:
    """Выполнить cmd не дольше timeout. Завис — запомнить и GpuError; True — успешно."""
    global stuck
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    try:
        p.wait(timeout)
    except subprocess.TimeoutExpired:
        stuck = p
        log.error(_("%s завис в ядре (%s с)"), " ".join(cmd), timeout)
        raise GpuError(stuck_message())
    if p.returncode != 0:
        log.warning("%s: %s", " ".join(cmd), p.stderr.read().strip())
    return p.returncode == 0


def _write(path: str, value, timeout: float = 20) -> bool:
    """Запись в sysfs (remove, rescan, dgpu_disable) — тоже может зависнуть в ядре."""
    if sysfs.ROOT:                       # тесты: поддельный sysfs
        return sysfs.write(path, value)
    return _kernel(["sh", "-c", 'echo "$1" > "$2"', "sh", str(value), path], timeout)


# BIOS отвечает на dgpu_disable за 6–8 с; выгрузка и загрузка драйвера — несколько секунд
BIOS_TIMEOUT = 30
UNLOAD_TIMEOUT = 15
LOAD_TIMEOUT = 60
# Между двумя переключениями — короткая пауза: BIOS ещё обрабатывает прошлое событие (подключает карту
# к шине или снимает питание), и новое переключение в этот момент может застрять в ядре.
SETTLE_S = 5
_changed_at: float | None = None      # только настоящие переключения; при старте демона паузы нет


def _now() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME)   # вместе со временем сна, в отличие от monotonic


def _settle() -> None:
    if _changed_at is not None and (wait := _changed_at + SETTLE_S - _now()) > 0:
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


def _stop_services() -> None:
    subprocess.run(["systemctl", "stop", *SERVICES], capture_output=True)


def _load_driver() -> bool:
    return _kernel(["modprobe", "-a", *MODULES_LOAD], LOAD_TIMEOUT)


def _remove_from_bus(gpu: str) -> None:
    """Сначала звук/USB-C (.1, .2 …), потом саму видеокарту (.0). Драйвер при этом отпускает карту, даже
    если его модуль «занят» — выгружать модуль для этого не нужно."""
    base = gpu.rsplit(".", 1)[0]
    for f in sorted(sysfs.find(f"{PCI}/{base}.*"), reverse=True):
        if sysfs.exists(f + "/remove"):
            _write(f + "/remove", 1)


def _rescan() -> str | None:
    """Пересканировать шину, пока карта не появится (до 10 с). PCI-адрес или None."""
    for _attempt in range(10):
        if gpu := find_gpu():
            return gpu
        _write("/sys/bus/pci/rescan", 1)
        time.sleep(1)
    return find_gpu()


def fixup() -> bool:
    """Убрать с шины обесточенную в BIOS карту. True — что-то убрали."""
    gpu = find_gpu()
    if not bios_off() or gpu is None:
        return False
    log.info(_("убираю выключенную NVIDIA с шины PCI (иначе выход из сна ждёт её 65 с)"))
    _remove_from_bus(gpu)
    return True


# ---------- уборка до и после переключения ----------
# Служебные программы NVIDIA, которые остаются висеть от прошлых попыток или опрашивают карту
LEFTOVERS = ("nvidia-smi", "nvidia-settings")


def _leftovers() -> list[int]:
    """Хвосты: nvidia-smi и nvidia-settings, ожидающие modprobe NVIDIA (не зависшие в ядре — тех не убить)."""
    out = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/comm") as f:
                comm = f.read().strip()
            if comm == "modprobe":
                with open(f"/proc/{pid}/cmdline", "rb") as f:
                    cmd = f.read()
                if b"nvidia" not in cmd and b"char-major-195" not in cmd:
                    continue
            elif comm not in LEFTOVERS:
                continue
        except OSError:
            continue
        if stuck is None or int(pid) != stuck.pid:
            out.append(int(pid))
    return out


def _kill(pids: list[int], sig) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def _close(gpu: str | None) -> None:
    """Закрыть всё, что держит NVIDIA, кроме рабочего стола и системы: TERM, 2 с, оставшимся — KILL."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        busy = [(p, c) for p, c in holders(gpu) if not is_protected(p, c)] if gpu else []
        pids = [p for p, _c in busy] + ([] if sysfs.ROOT else _leftovers())
        if not pids:
            return
        if sig == signal.SIGTERM and busy:
            log.info(_("закрываю программы на NVIDIA: %s"), ", ".join(names(busy)))
        _kill(pids, sig)
        end = time.monotonic() + 2.0
        while time.monotonic() < end and any(os.path.exists(f"/proc/{p}") for p in pids):
            time.sleep(0.2)


def _cleanup(gpu: str | None) -> None:
    """Перед переключением и после ошибки: никаких хвостов от прошлых попыток."""
    _close(gpu)
    _stop_services()


# Устройства NVIDIA на время выключения закрыты для всех, кроме root: иначе закрытая программа (или
# перезапущенный процесс браузера) сразу открыла бы карту снова.
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
            os.chmod(n, mode)        # после снятия карты с шины части узлов уже нет — это нормально
        except OSError:
            pass


# ---------- переключение ----------
def turn_off(force: bool = False, ignore_displays: bool = False) -> None:
    """Eco, жёстко (как G-Helper): закрыть программы на NVIDIA, снять карту с шины, выключить в BIOS.
    Драйвер выгружается, если получится; не получится — не мешает. При ошибке всё возвращается как было.
    force оставлен для совместимости вызовов."""
    gpu = find_gpu()
    if bios_off() and gpu is None:
        return
    if not mux_hybrid():
        raise GpuError(_("MUX в режиме «только NVIDIA» — сначала переключите MUX в гибрид и перезагрузитесь"))
    if gpu and not ignore_displays and (ext := external_displays(gpu)):
        raise GpuError(_("К NVIDIA подключён монитор ({0}) — после выключения он погаснет").format(', '.join(ext)))
    if gpu and (drv := driver(gpu)) not in (None, "nvidia"):
        # с чужим драйвером снимать карту с шины опасно — может зависнуть ядро
        raise GpuError(_("видеокарта работает на драйвере {0}, а Eco умеет выключать её только с драйвером NVIDIA "
                         "(пакет nvidia-open или nvidia)").format(drv))
    _settle()
    if gpu:
        _cleanup(gpu)
        blocked = _block_nodes(gpu)
        try:
            log.info(_("убираю NVIDIA с шины PCI"))
            _remove_from_bus(gpu)
        finally:
            _unblock_nodes(blocked)
    log.info(_("отключаю NVIDIA в BIOS"))
    _mark()
    if not _write(_attr("dgpu_disable"), 1, BIOS_TIMEOUT) or find_gpu():
        _restore()
        raise GpuError(_("BIOS отказал в отключении — всё возвращено как было"))
    log.info(_("NVIDIA выключена (Eco)"))
    # драйвер без карты не нужен; занят (буферы рабочего стола) — останется загруженным, это безвредно.
    # Завис — карта всё равно выключена; зависание запомнено, включать её до перезагрузки не будем.
    try:
        if not _kernel(["modprobe", "-r", *MODULES_UNLOAD], UNLOAD_TIMEOUT):
            log.info(_("драйвер NVIDIA остался загруженным (его модуль занят) — карта всё равно выключена"))
    except GpuError:
        pass


def _restore() -> None:
    """Откат неудачного Eco: карта снова на шине и с драйвером."""
    log.info(_("возвращаю NVIDIA"))
    _write(_attr("dgpu_disable"), 0, BIOS_TIMEOUT)
    if _rescan() and driver() is None:
        _load_driver()
    _start_services()


def turn_on() -> None:
    if not bios_off() and find_gpu() and driver():
        return
    _settle()
    _cleanup(None)
    fixup()   # «призрак» помешал бы найти карту заново
    log.info(_("включаю NVIDIA в BIOS"))
    _mark()
    if not _write(_attr("dgpu_disable"), 0, BIOS_TIMEOUT):
        raise GpuError(_("BIOS отказал во включении"))
    if not _rescan():
        raise GpuError(_("карта не появилась. Перезагрузите ноутбук — BIOS уже включил её"))
    # модуль, оставшийся загруженным, сам подхватит карту; если его нет — загрузить
    if driver() is None:
        log.info(_("загружаю драйвер NVIDIA"))
        if not _load_driver():
            raise GpuError(_("драйвер не загрузился (журнал: journalctl -b -k | grep -i nvidia)"))
    _start_services()
    log.info(_("NVIDIA включена (Стандарт)"))


class Switcher:
    """Переключение в отдельном потоке: главный цикл демона не ждёт шину PCI и BIOS."""

    def __init__(self, on_done):
        self.on_done = on_done      # on_done(error: str | None) — вызывается в главном потоке
        self.busy = False
        self.target: str | None = None
        self._error: str | None = None
        self._error_at = 0.0

    # ошибка показывается минуту: потом она уже не про текущее состояние
    ERROR_TTL = 60

    @property
    def last_error(self) -> str | None:
        return self._error if time.monotonic() - self._error_at < self.ERROR_TTL else None

    @last_error.setter
    def last_error(self, v):
        self._error = v
        self._error_at = time.monotonic()

    def start(self, want_off: bool, force: bool = False, ignore_displays: bool = False) -> bool:
        if self.busy or is_stuck():
            return False
        self.busy = True
        self.target = "eco" if want_off else "standard"
        self.last_error = None
        threading.Thread(target=self._work, args=(want_off, ignore_displays), daemon=True).start()
        return True

    def _work(self, want_off: bool, ignore_displays: bool) -> None:
        from gi.repository import GLib
        err = None
        try:
            with open(sysfs.path(LOCK) if sysfs.ROOT else LOCK, "w") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise GpuError(_("видеокарту уже переключает другая программа (gpu-eco?)"))
                guard = None if sysfs.ROOT else HotkeyGuard.acquire()
                try:
                    (turn_off(ignore_displays=ignore_displays) if want_off else turn_on())
                finally:
                    if guard:
                        guard.release_later()
        except GpuError as e:
            err = str(e)
            log.warning(_("видеокарта: %s"), err)
        except Exception as e:
            err = _("внутренняя ошибка: {0}").format(e)
            log.exception(_("видеокарта"))

        def done():
            self.busy = False
            self.last_error = err
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
