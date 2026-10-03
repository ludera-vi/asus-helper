"""Частота встроенного экрана через KDE (kscreen-doctor): без root и без демона.

Как в виджете «GPU» из gpu-switch: берём встроенный экран (eDP), режимы с текущим разрешением,
минимальную и максимальную частоту. Настройка KDE — сохраняется и после перезагрузки.
"""
import json

from PySide6.QtCore import QProcess
from ..i18n import _


def _run(args: list[str], done) -> None:
    p = QProcess()

    def finished(code, _status):
        out, err = bytes(p.readAllStandardOutput()).decode(), bytes(p.readAllStandardError()).decode()
        _run.alive.discard(p)
        done(code, out, err)

    def failed(_error):
        # kscreen-doctor не запустился: finished не придёт
        if p.state() == QProcess.NotRunning and p in _run.alive:
            _run.alive.discard(p)
            done(-1, "", p.errorString())
    p.finished.connect(finished)
    p.errorOccurred.connect(failed)
    _run.alive.add(p)           # QProcess без родителя — держим ссылку, пока работает
    p.start("kscreen-doctor", args)


_run.alive = set()


def parse(text: str) -> dict:
    """{output, hz, rates: [низкая, высокая], modes: {hz: id}} или {} если экрана нет."""
    try:
        outputs = [o for o in json.loads(text)["outputs"] if o.get("enabled")]
    except (ValueError, KeyError):
        return {}
    out = next((o for o in outputs if o.get("type") == 7 or o["name"].startswith("eDP")), outputs[0] if outputs else None)
    if not out:
        return {}
    cur = next((m for m in out["modes"] if m["id"] == out["currentModeId"]), None)
    if not cur:
        return {}
    same = [m for m in out["modes"] if m["size"] == cur["size"]]
    modes = {}
    for m in same:
        hz = round(m["refreshRate"])
        if hz not in modes:
            modes[hz] = m["id"]
    rates = sorted(modes)
    return {"output": out["name"], "hz": round(cur["refreshRate"]),
            "rates": [rates[0], rates[-1]] if len(rates) > 1 else rates,
            "modes": {str(k): v for k, v in modes.items()}}


def query(done) -> None:
    _run(["-j"], lambda code, out, _err: done(parse(out) if code == 0 else {}))


def set_rate(info: dict, hz: int, done) -> None:
    mode = (info.get("modes") or {}).get(str(hz))
    if not mode:
        done(_("нет режима {0} Гц").format(hz))
        return
    _run([f"output.{info['output']}.mode.{mode}"],
         lambda code, _out, err: done(None if code == 0 else f"kscreen-doctor: {err.strip()}"))
