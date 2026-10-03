"""Перевод интерфейса: русский (исходный текст в коде) и английский (en.json: русская строка → английская).

Язык берётся один раз при запуске процесса: ASUSHELPER_LANG, иначе "language" из /etc/asus-helper/config.json,
иначе язык системы ($LANG). Смена языка — демон и окно перезапускаются сами (см. SetLanguage).
Шаблоны с подстановкой пишутся с {0}, {1} и переводятся целиком: _("Режим {0}").format(name).
"""
import json
import os

LANGUAGES = ("ru", "en")
_DIR = os.path.dirname(__file__)
_CONFIG = os.path.join(os.environ.get("ASUSHELPER_CONFIG_DIR", "/etc/asus-helper"), "config.json")


def _detect() -> str:
    lang = os.environ.get("ASUSHELPER_LANG")
    if lang not in LANGUAGES:
        try:
            with open(_CONFIG) as f:
                lang = json.load(f).get("language")
        except (OSError, ValueError):
            lang = None
    if lang not in LANGUAGES:
        lang = "ru" if os.environ.get("LANG", "").startswith("ru") else "en"
    return lang


LANG = _detect()


def table(lang: str = None) -> dict:
    """Словарь «русская строка → перевод» для языка (для русского — пустой)."""
    if (lang or LANG) == "ru":
        return {}
    try:
        with open(os.path.join(_DIR, f"{lang or LANG}.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


_T = table()


def _(s: str) -> str:
    return _T.get(s, s)
