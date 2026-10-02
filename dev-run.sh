#!/bin/bash
# Пробный запуск asus-helperd из исходников вместо asusd.
#
#   sudo ./dev-run.sh            снимок snapper → asusd на паузу → демон в этом терминале
#   Ctrl+C                       остановить демон и вернуть asusd как было
#
# Ничего не удаляется. asusd маскируется только до перезагрузки (systemctl mask --runtime),
# чтобы udev не запустил его снова. Ставятся два файла прав (D-Bus и polkit) — их убирает
# ./dev-run.sh --cleanup. Настройки демона: /etc/asus-helper/config.json.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ $EUID -eq 0 ] || exec sudo "$0" "$@"

DBUS_CONF=/etc/dbus-1/system.d/org.asushelper.Daemon.conf
POLKIT=/usr/share/polkit-1/actions/org.asushelper.policy

reload_dbus() {
    busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig >/dev/null
}

if [ "${1:-}" = --cleanup ]; then
    rm -fv "$DBUS_CONF" "$POLKIT"
    reload_dbus
    echo "Файлы прав убраны. Настройки остались в /etc/asus-helper (удалить вручную, если не нужны)."
    exit 0
fi

# ---------- 1. снимок ----------
if command -v snapper >/dev/null && [ "${1:-}" != --no-snapshot ]; then
    read -rp "Сделать снимок snapper перед пробой? [Д/н] " a
    if [[ ! "$a" =~ ^[НнNn] ]]; then
        n=$(snapper -c root create --print-number --cleanup-algorithm number \
                --description "перед пробным запуском asushelper")
        echo "Снимок #$n создан. Откат: загрузиться в него из меню загрузчика или snapper rollback $n"
    fi
fi

# ---------- 2. права D-Bus и polkit ----------
# проект раньше назывался asushero, потом AsusLudera — переносим настройки и убираем старые файлы прав
for old in asusludera asushero; do
    if [ -e /etc/$old/config.json ] && [ ! -e /etc/asus-helper/config.json ]; then
        install -Dm644 /etc/$old/config.json /etc/asus-helper/config.json
        echo "Настройки перенесены из /etc/$old в /etc/asus-helper"
    fi
    rm -rf /etc/$old
    rm -f /etc/dbus-1/system.d/org.$old.Daemon.conf /usr/share/polkit-1/actions/org.$old.policy
done
install -Dm644 data/org.asushelper.Daemon.conf "$DBUS_CONF"
install -Dm644 data/org.asushelper.policy "$POLKIT"
reload_dbus

# ---------- 3. настройки: при первом запуске переносим из asusd ----------
if [ ! -e /etc/asus-helper/config.json ]; then
    echo "Переношу настройки из /etc/asusd:"
    python3 -m asushelper.cli import-asusd
elif ! grep -q '"keyboard"' /etc/asus-helper/config.json; then
    # настройки от прошлой версии — без подсветки: дозабираем её из asusd, остальное не трогаем
    python3 - <<'EOF'
import glob
from asushelper.asusd_import import parse_aura
from asushelper.daemon.config import Config
cfg = Config().load()
for path in sorted(glob.glob("/etc/asusd/aura_*.ron"))[:1]:
    cfg.data["keyboard"].update(parse_aura(open(path).read()))
    print("Подсветка перенесена из", path, cfg.data["keyboard"])
cfg.save()
EOF
fi

# ---------- 4. asusd на паузу ----------
restore() {
    echo
    echo "Возвращаю asusd…"
    systemctl unmask --runtime asusd.service >/dev/null 2>&1 || true
    systemctl start asusd.service || echo "asusd не запустился: systemctl status asusd"
    echo "asusd снова работает со своими настройками."
}
trap restore EXIT
systemctl mask --runtime asusd.service >/dev/null
systemctl stop asusd.service asus-shutdown.service

# ---------- 5. демон ----------
echo "asus-helperd запущен. Проверка в другом терминале: python3 -m asushelper.cli   (Ctrl+C — стоп)"
python3 -m asushelper.daemon --debug || true
