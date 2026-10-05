"""Asus-helper — значок в трее и окно. Запуск: python -m asushelper.app

Левый клик по значку — открыть или закрыть окно, правый — быстрое меню.
Приложение также показывает карточки KDE (режим, подсветка) и уведомления о видеокарте —
поэтому отдельный asus-helper-agent вместе с ним не нужен.
"""
import argparse
import configparser
import logging
import os
import sys
from pathlib import Path

import gi  # noqa: E402
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402
from PySide6.QtCore import QMetaObject, QRectF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtQuickControls2 import QQuickStyle  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QStyleFactory, QSystemTrayIcon  # noqa: E402

from .. import __version__  # noqa: E402
from ..agent import Agent  # noqa: E402
from .backend import Backend, load_settings  # noqa: E402
from . import theme as themes  # noqa: E402
from ..i18n import _

log = logging.getLogger("asus-helper")

APP_BUS_NAME = "org.asushelper.App"
APP_PATH = "/org/asushelper/App"
APP_XML = """<node><interface name="org.asushelper.App"><method name="Toggle"/></interface></node>"""

PROFILE_ICONS = {"quiet": "battery-profile-powersave-symbolic", "balanced": "battery-profile-balanced-symbolic",
                 "performance": "battery-profile-performance-symbolic"}
PROFILE_NAMES = {"quiet": _("Тихий"), "balanced": _("Баланс"), "performance": _("Турбо")}
GPU_NAMES = {"off": _("выключена (Eco)"), "suspended": _("спит"), "active": _("работает"), "missing": _("без драйвера")}


# Значок: цвет — режим (Тихий зелёный, Баланс синий, Турбо красный), фиолетовая точка в правом нижнем
# углу — NVIDIA включена (нет точки — выключена). «Авто» — настройка, а не состояние: видно в подсказке и окне.
PROFILE_FILL = {"quiet": "#27ae60", "balanced": "#3daee9", "performance": "#da4453"}
DEFAULT_FILL = "#7f8c8d"
GPU_ON = "#a35bd8"


def make_icon(fill: str, gpu_on: bool, dim: bool = False) -> QIcon:
    """Скруглённый квадрат цвета режима с буквами AH; gpu_on — фиолетовая точка в правом нижнем углу;
    dim — идёт переключение видеокарты (бледнее)."""
    icon = QIcon()
    for size in (16, 22, 24, 32, 48, 64, 128):
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setOpacity(0.45 if dim else 1.0)
        m = size * 0.04
        rect = QRectF(m, m, size - 2 * m, size - 2 * m)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(fill))
        p.drawRoundedRect(rect, size * 0.22, size * 0.22)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(7, round(size * 0.48)))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "AH")
        if gpu_on:
            d = max(9.0, size * 0.38)          # в трее (22 px) — не меньше 9 px
            dot = QRectF(size - d, size - d, d, d)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#232629"))      # тёмная обводка — точку видно на любом цвете
            p.drawEllipse(dot)
            o = max(1.0, d * 0.16)
            p.setBrush(QColor(GPU_ON))
            p.drawEllipse(dot.adjusted(o, o, -o, -o))
        p.end()
        icon.addPixmap(pm)
    return icon


def panel_on_top() -> bool:
    """Где панель Plasma: сверху (location=3) или снизу (4). Окно открывается с её стороны."""
    rc = Path.home() / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    cp = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        cp.read(rc)
    except configparser.Error:
        return False
    for section in cp.sections():
        if cp.get(section, "plugin", fallback="") == "org.kde.panel":
            return cp.get(section, "location", fallback="4") == "3"
    return False


def noctalia_bar_on_top() -> bool:
    """niri с панелью noctalia: где её панель — position в разделе [bar…] настроек (по умолчанию сверху)."""
    import tomllib
    for path in (Path.home() / ".local/state/noctalia/settings.toml", Path.home() / ".config/noctalia/config.toml"):
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, ValueError):
            continue
        # [bar], [bar.main] или [[bar]] — смотря какая версия noctalia
        bars = data.get("bar") or {}
        found = [*bars, *(v for b in bars for v in b.values())] if isinstance(bars, list) else [bars, *bars.values()]
        for bar in (b for b in found if isinstance(b, dict)):
            if isinstance(bar.get("position"), str):
                return bar["position"] != "bottom"
    return True


def desktop() -> str:
    """Рабочий стол сеанса: kde, gnome или другое (niri, hyprland…) — в нижнем регистре."""
    d = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    return "kde" if "KDE" in d else "gnome" if "GNOME" in d else d.split(":")[0].lower()


def use_breeze_icons(dark: bool) -> None:
    """Вне KDE (GNOME — Adwaita) нужных значков нет: берём Breeze, если он установлен. На тёмном фоне
    (оригинальная тема, тёмная тема noctalia) — Breeze Dark, светлые значки."""
    name = "breeze-dark" if dark else "breeze"
    if any(os.path.exists(f"{d}/icons/{name}/index.theme")
           for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")):
        QIcon.setThemeName(name)


def already_running(session: Gio.DBusConnection) -> bool:
    """Если приложение уже запущено — попросить его открыть окно и выйти."""
    try:
        session.call_sync(APP_BUS_NAME, APP_PATH, "org.asushelper.App", "Toggle", None, None,
                          Gio.DBusCallFlags.NO_AUTO_START, 2000, None)
        return True
    except GLib.Error:
        return False


class Tray:
    def __init__(self, app: QApplication, backend: Backend, window):
        self.backend = backend
        self.window = window
        self.icon = QSystemTrayIcon(app)
        self.icon.activated.connect(self.on_activated)
        menu = QMenu()
        self.mode_actions = {}
        for p in ("quiet", "balanced", "performance"):
            a = QAction(QIcon.fromTheme(PROFILE_ICONS[p]), PROFILE_NAMES[p], menu, checkable=True)
            a.triggered.connect(lambda _checked=False, p=p: backend.setProfile(p))
            menu.addAction(a)
            self.mode_actions[p] = a
        menu.addSeparator()
        self.eco = QAction(_("NVIDIA выключена (Eco)"), menu, checkable=True)
        self.eco.triggered.connect(lambda on: backend.setGpuMode("eco" if on else "standard", False))
        menu.addAction(self.eco)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("configure"), _("Открыть"), self.toggle)
        menu.addAction(QIcon.fromTheme("application-exit"), _("Выйти"), app.quit)
        self.menu = menu
        self.icon.setContextMenu(menu)
        backend.stateChanged.connect(self.update)
        backend.connectedChanged.connect(self.update)
        self.update()
        self.icon.show()

    def toggle(self):
        QMetaObject.invokeMethod(self.window, "toggle")

    def on_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.MiddleClick):
            self.toggle()

    def update(self):
        s = self.backend.state or {}
        profile = s.get("profile")
        g = s.get("gpu") or {}
        switching = bool(g.get("switching"))
        off = (g.get("target") == "eco") if switching else g.get("state") == "off"
        key = (profile, off, switching)
        if key != getattr(self, "_icon_key", None):
            self._icon_key = key
            self.icon.setIcon(make_icon(PROFILE_FILL.get(profile, DEFAULT_FILL), gpu_on=not off, dim=switching))
        for p, a in self.mode_actions.items():
            a.setChecked(p == profile)
        g = s.get("gpu") or {}
        self.eco.setVisible(bool(g.get("supported")))
        self.eco.setChecked(g.get("state") == "off")
        self.eco.setEnabled(not g.get("switching"))
        if not self.backend.connected:
            self.icon.setToolTip(_("Asus-helper: демон не запущен"))
            return
        lines = [_("Режим: {0}").format(PROFILE_NAMES.get(profile, profile))]
        if g.get("supported"):
            lines.append(f"NVIDIA: {GPU_NAMES.get(g.get('state'), g.get('state'))}"
                         + (_(" — Авто: от сети вкл., без сети выкл.") if g.get("auto_eco") else ""))
            if g.get("auto_waiting"):
                lines.append(_("Ожидание закрытия: ") + ", ".join(g["auto_waiting"]))
        # вентиляторов у ноутбука может быть один, три или ни одного (ядро не показывает обороты)
        rpm = "/".join(str(v) for v in (s.get("fans") or {}).values() if v is not None)
        if s.get("cpu_temp") is not None:
            lines.append(_("CPU {0} °C").format(round(s["cpu_temp"]))
                         + (_(" · вентиляторы {0} об/мин").format(rpm) if rpm else ""))
        self.icon.setToolTip("Asus-helper\n" + "\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(prog="asus-helper")
    ap.add_argument("--show", action="store_true", help=_("сразу открыть окно"))
    ap.add_argument("--page", choices=["main", "fans", "monitor"], default="main", help=_("с какой страницы открыть (с --show)"))
    ap.add_argument("--no-osd", action="store_true", help=_("не показывать карточки KDE (их показывает asus-helper-agent)"))
    args, qt_args = ap.parse_known_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    session = Gio.bus_get_sync(Gio.BusType.SESSION)
    if already_running(session):
        return 0

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("asus-helper")
    app.setApplicationDisplayName("Asus-helper")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName("asus-helper")
    app.setWindowIcon(QIcon.fromTheme("asus-helper", make_icon(PROFILE_FILL["balanced"], gpu_on=False)))
    app.setQuitOnLastWindowClosed(False)

    # оформление выбирается до загрузки окна: стиль QtQuick потом не сменить — только перезапуском
    theme = themes.choose(load_settings())
    QQuickStyle.setStyle(themes.style_for(theme))
    colors = themes.colors_for(theme)
    if theme != themes.SYSTEM:
        app.setStyle("Fusion")                       # и меню значка в трее — в той же теме
        app.setPalette(themes.original_palette(colors))
    elif app.style().name().lower() != "breeze" and "breeze" in (k.lower() for k in QStyleFactory.keys()):
        # «Как в системе» — цвета KDE, но кнопки и списки всегда стилем Breeze: стиль KDE для QML рисует их стилем
        # виджетов системы, а сторонние (Kvantum — его, например, включают глобальные темы из магазина KDE)
        # ломают окно: градиенты, заливки, обрезанные подписи
        log.info(_("стиль виджетов системы %s — окно рисую стилем Breeze"), app.style().name())
        app.setStyle("Breeze")
    log.info(_("оформление: %s (%s)"), theme, QQuickStyle.name())
    session_desktop = desktop()
    if session_desktop != "kde":
        use_breeze_icons(theme != themes.SYSTEM and colors.get("mode") != "light")

    system = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    backend = Backend(system, theme)
    if theme == themes.NOCTALIA:
        # сменилась тема noctalia — меню значка в трее берёт новую палитру (окно — из backend.colors само).
        # Набор значков на ходу не меняем: уже показанные значки тогда пропадают, а символьные значки окна
        # и так красятся цветом текста
        backend.colorsChanged.connect(lambda: app.setPalette(themes.original_palette(backend.colors)))
    if not args.no_osd:
        app.agent = Agent(system, session)   # держим ссылку

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.setInitialProperties({"anchorTop": panel_on_top() if session_desktop == "kde" else noctalia_bar_on_top(),
                                 "movable": session_desktop == "gnome",
                                 # niri и другие с layer-shell (не KDE и не GNOME): окно встаёт под панель (её
                                 # зону), а не поверх неё, и закрывается кликом мимо, а не потерей фокуса
                                 "underPanels": session_desktop not in ("kde", "gnome")})
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("qml") / "Main.qml")))
    if not engine.rootObjects():
        log.error(_("окно не загрузилось (ошибки QML выше)"))
        return 1
    window = engine.rootObjects()[0]

    tray = Tray(app, backend, window)

    # второй запуск программы (например, из меню приложений) открывает окно этого экземпляра
    node = Gio.DBusNodeInfo.new_for_xml(APP_XML)
    session.register_object(APP_PATH, node.interfaces[0],
                            lambda *a: (tray.toggle(), a[-1].return_value(None)), None, None)
    Gio.bus_own_name_on_connection(session, APP_BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)

    # клавиша ROG (или назначенная в настройках KDE / GNOME) открывает окно; в niri это строка в его
    # конфиге (~/.config/niri/asus-helper.kdl от установщика) — второй запуск программы открывает окно
    if session_desktop == "gnome":
        from .hotkey import gnome_shortcut
        gnome_shortcut()
        if not QSystemTrayIcon.isSystemTrayAvailable():
            log.warning(_("в GNOME нет трея: нужно расширение AppIndicator (gnome-shell-extension-appindicator); "
                          "окно открывается из меню приложений и клавишей ROG"))
    elif session_desktop != "niri":
        from .hotkey import GlobalShortcut
        app.shortcut = GlobalShortcut(session, tray.toggle)

    if args.show:
        tray.toggle()
        if args.page != "main":
            QMetaObject.invokeMethod(window, "openFans" if args.page == "fans" else "openMonitor")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
