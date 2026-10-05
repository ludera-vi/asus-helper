"""Оформление окна.

system   — как в системе: стиль и цвета KDE (qqc2-desktop-style, org.kde.desktop). Работает там, где есть
           Plasma и этот стиль — на любом дистрибутиве с KDE Plasma 6.
original — своя тёмная тема в духе G-Helper: фирменные цвета режимов, карточки разделов. Рисуется стилем
           Fusion, который есть в любой установке Qt, — поэтому выглядит одинаково везде.

Если выбрана системная, но стиля KDE нет или сеанс не KDE (GNOME и др. — там цвета KDE не подхватятся),
включается оригинальная: окно не должно остаться без оформления.

noctalia — «как в системе» в niri с панелью noctalia: рисуется так же, как оригинальная (Fusion, карточки), но
цвета — из темы noctalia. Их пишет шаблон noctalia (data/noctalia/asus-helper-colors.json, его подключает
установщик) в NOCTALIA_COLORS при каждой смене темы, обоев или светлого/тёмного режима; окно следит за файлом и
перекрашивается сразу, без перезапуска. Нет файла — оригинальная.
"""
import json
import os
from pathlib import Path

from PySide6.QtCore import QLibraryInfo
from PySide6.QtGui import QColor, QPalette

SYSTEM, ORIGINAL, NOCTALIA = "system", "original", "noctalia"
THEMES = (SYSTEM, ORIGINAL)        # что можно выбрать; NOCTALIA — это SYSTEM в niri с noctalia
NOCTALIA_COLORS = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "asus-helper/noctalia-colors.json"

# Оригинальная тема: графит вместо чистого чёрного, цвета режимов как в G-Helper (Eco/Silent — бирюзово-
# зелёный, Standard/Balanced — голубой, Turbo — красный), чуть мягче, чтобы не резали глаз на тёмном.
ORIGINAL_COLORS = {
    "window": "#15171b",
    "card": "#1e2126",
    "button": "#2a2e35",
    "text": "#e8eaed",
    "dim": "#9aa0a8",
    "disabled": "#5d636c",
    "accent": "#3aaeef",
    "positive": "#13b98f",
    "negative": "#ff4b4b",
    "neutral": "#ff9f1a",
    "border": "#2f333b",
}


def kde_style_available() -> bool:
    if "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
        return False
    qml = QLibraryInfo.path(QLibraryInfo.LibraryPath.QmlImportsPath)
    return os.path.exists(os.path.join(qml, "org", "kde", "desktop", "qmldir"))


def noctalia_available() -> bool:
    """«Как в системе» вне KDE и GNOME: шаблон noctalia уже написал цвета."""
    desk = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    return "KDE" not in desk and "GNOME" not in desk and bool(noctalia_colors())


def noctalia_colors() -> dict:
    """Цвета из файла шаблона noctalia в ключах ORIGINAL_COLORS (+ mode: dark/light); {} — файла нет или он битый."""
    try:
        data = json.loads(NOCTALIA_COLORS.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not all(QColor.isValidColorName(str(data.get(k, ""))) for k in ORIGINAL_COLORS):
        return {}
    return {**{k: data[k] for k in ORIGINAL_COLORS}, "mode": "light" if data.get("mode") == "light" else "dark",
            "on_accent": data.get("on_accent") if QColor.isValidColorName(str(data.get("on_accent", ""))) else "#ffffff"}


def can_choose() -> bool:
    """Есть выбор «Система / Оригинал»: в KDE со стилем KDE и в niri с noctalia."""
    return kde_style_available() or noctalia_available()


def choose(settings: dict) -> str:
    """Тема, которая будет на самом деле: выбранная или запасная оригинальная."""
    want = os.environ.get("ASUSHELPER_THEME") or settings.get("theme")   # переменная — для отладки
    want = want if want in THEMES else SYSTEM
    if want == SYSTEM and not kde_style_available():
        return NOCTALIA if noctalia_available() else ORIGINAL
    return want


def style_for(theme: str) -> str:
    # стиль можно переопределить снаружи (QT_QUICK_CONTROLS_STYLE) — для отладки
    return os.environ.get("QT_QUICK_CONTROLS_STYLE") or ("org.kde.desktop" if theme == SYSTEM else "Fusion")


def colors_for(theme: str) -> dict:
    """Цвета окна для оригинальной темы и темы noctalia (для системной — оригинальные, их окно не берёт)."""
    if theme == NOCTALIA:
        return noctalia_colors() or ORIGINAL_COLORS
    return ORIGINAL_COLORS


def original_palette(colors: dict | None = None) -> QPalette:
    """Палитра для стиля Fusion: кнопки, ползунки, списки, меню значка в трее."""
    c = {k: QColor(v) for k, v in (colors or ORIGINAL_COLORS).items() if k in ORIGINAL_COLORS}
    on_accent = QColor((colors or {}).get("on_accent", "#ffffff"))
    p = QPalette()
    for role, color in ((QPalette.Window, c["window"]), (QPalette.WindowText, c["text"]),
                        (QPalette.Base, c["card"]), (QPalette.AlternateBase, c["button"]),
                        (QPalette.Text, c["text"]), (QPalette.Button, c["button"]),
                        (QPalette.ButtonText, c["text"]), (QPalette.BrightText, c["negative"]),
                        (QPalette.Highlight, c["accent"]), (QPalette.HighlightedText, on_accent),
                        (QPalette.ToolTipBase, c["card"]), (QPalette.ToolTipText, c["text"]),
                        (QPalette.PlaceholderText, c["dim"]), (QPalette.Link, c["accent"]),
                        (QPalette.Mid, c["border"]), (QPalette.Dark, c["window"]),
                        (QPalette.Light, c["button"]), (QPalette.Midlight, c["button"]),
                        (QPalette.Shadow, QColor("#000000"))):
        p.setColor(role, color)
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c["disabled"])
    return p
