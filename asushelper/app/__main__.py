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

os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

import gi  # noqa: E402
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402
from PySide6.QtCore import QMetaObject, QRectF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon  # noqa: E402

from .. import __version__  # noqa: E402
from ..agent import Agent  # noqa: E402
from .backend import Backend  # noqa: E402

log = logging.getLogger("asus-helper")

APP_BUS_NAME = "org.asushelper.App"
APP_PATH = "/org/asushelper/App"
APP_XML = """<node><interface name="org.asushelper.App"><method name="Toggle"/></interface></node>"""

PROFILE_ICONS = {"quiet": "battery-profile-powersave-symbolic", "balanced": "battery-profile-balanced-symbolic",
                 "performance": "battery-profile-performance-symbolic"}
PROFILE_NAMES = {"quiet": "Тихий", "balanced": "Баланс", "performance": "Турбо"}
GPU_NAMES = {"off": "выключена (Eco)", "suspended": "спит", "active": "работает", "missing": "без драйвера"}


# Значок: рамка — режим видеокарты, заливка — режим производительности (цвета Breeze)
GPU_BORDER = {"eco": "#95a5a6", "standard": "#3daee9", "auto": "#f67400"}
PROFILE_FILL = {"quiet": "#2e7d4f", "balanced": "#2a6f97", "performance": "#a93226"}
DEFAULT_FILL = "#4d5358"


def make_icon(fill: str, border: str, dim: bool = False) -> QIcon:
    """Скруглённый квадрат с буквами AH: рамка border, внутри fill. dim — идёт переключение видеокарты."""
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
        p.setBrush(QColor(border))
        p.drawRoundedRect(rect, size * 0.22, size * 0.22)
        w = max(2.0, size * 0.1)
        p.setBrush(QColor(fill))
        p.drawRoundedRect(rect.adjusted(w, w, -w, -w), size * 0.14, size * 0.14)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(7, round(size * 0.47)))
        font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 92)
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "AH")
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
            a.triggered.connect(lambda _=False, p=p: backend.setProfile(p))
            menu.addAction(a)
            self.mode_actions[p] = a
        menu.addSeparator()
        self.eco = QAction("NVIDIA выключена (Eco)", menu, checkable=True)
        self.eco.triggered.connect(lambda on: backend.setGpuMode("eco" if on else "standard", False))
        menu.addAction(self.eco)
        menu.addSeparator()
        menu.addAction(QIcon.fromTheme("configure"), "Открыть", self.toggle)
        menu.addAction(QIcon.fromTheme("application-exit"), "Выйти", app.quit)
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
        gpu_mode = "auto" if g.get("auto_eco") else ("eco" if off else "standard")
        key = (gpu_mode, profile, switching)
        if key != getattr(self, "_icon_key", None):
            self._icon_key = key
            self.icon.setIcon(make_icon(PROFILE_FILL.get(profile, DEFAULT_FILL), GPU_BORDER[gpu_mode], switching))
        for p, a in self.mode_actions.items():
            a.setChecked(p == profile)
        g = s.get("gpu") or {}
        self.eco.setVisible(bool(g.get("supported")))
        self.eco.setChecked(g.get("state") == "off")
        self.eco.setEnabled(not g.get("switching"))
        if not self.backend.connected:
            self.icon.setToolTip("Asus-helper: демон не запущен")
            return
        lines = [f"Режим: {PROFILE_NAMES.get(profile, profile)}"]
        if g.get("supported"):
            lines.append(f"NVIDIA: {GPU_NAMES.get(g.get('state'), g.get('state'))}"
                         + (" — Авто: от сети вкл., без сети выкл." if g.get("auto_eco") else ""))
        if s.get("cpu_temp") is not None:
            lines.append(f"CPU {round(s['cpu_temp'])} °C · вентиляторы {s['fans']['cpu']}/{s['fans']['gpu']} об/мин")
        self.icon.setToolTip("Asus-helper\n" + "\n".join(lines))


def main() -> int:
    ap = argparse.ArgumentParser(prog="asus-helper")
    ap.add_argument("--show", action="store_true", help="сразу открыть окно")
    ap.add_argument("--page", choices=["main", "fans", "monitor"], default="main", help="с какой страницы открыть (с --show)")
    ap.add_argument("--no-osd", action="store_true", help="не показывать карточки KDE (их показывает asus-helper-agent)")
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
    app.setWindowIcon(QIcon.fromTheme("asus-helper", make_icon(PROFILE_FILL["balanced"], GPU_BORDER["standard"])))
    app.setQuitOnLastWindowClosed(False)

    system = Gio.bus_get_sync(Gio.BusType.SYSTEM)
    backend = Backend(system)
    if not args.no_osd:
        app.agent = Agent(system, session)   # держим ссылку

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.setInitialProperties({"anchorTop": panel_on_top()})
    engine.load(QUrl.fromLocalFile(str(Path(__file__).with_name("qml") / "Main.qml")))
    if not engine.rootObjects():
        log.error("окно не загрузилось (ошибки QML выше)")
        return 1
    window = engine.rootObjects()[0]

    tray = Tray(app, backend, window)

    # второй запуск программы (например, из меню приложений) открывает окно этого экземпляра
    node = Gio.DBusNodeInfo.new_for_xml(APP_XML)
    session.register_object(APP_PATH, node.interfaces[0],
                            lambda *a: (tray.toggle(), a[-1].return_value(None)), None, None)
    Gio.bus_own_name_on_connection(session, APP_BUS_NAME, Gio.BusNameOwnerFlags.NONE, None, None)

    if args.show:
        tray.toggle()
        if args.page != "main":
            QMetaObject.invokeMethod(window, "openFans" if args.page == "fans" else "openMonitor")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
