#!/bin/bash
# Пробный запуск asusherod из исходников вместо asusd.
#
#   sudo ./dev-run.sh            снимок snapper → asusd на паузу → демон в этом терминале
#   Ctrl+C                       остановить демон и вернуть asusd как было
#
# Ничего не удаляется. asusd маскируется только до перезагрузки (systemctl mask --runtime),
# чтобы udev не запустил его снова. Ставятся два файла прав (D-Bus и polkit) — их убирает
# ./dev-run.sh --cleanup. Настройки демона: /etc/asushero/config.json.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ $EUID -eq 0 ] || exec sudo "$0" "$@"

DBUS_CONF=/etc/dbus-1/system.d/org.asushero.Daemon.conf
POLKIT=/usr/share/polkit-1/actions/org.asushero.policy

reload_dbus() {
    busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig >/dev/null
}

if [ "${1:-}" = --cleanup ]; then
    rm -fv "$DBUS_CONF" "$POLKIT"
    reload_dbus
    echo "Файлы прав убраны. Настройки остались в /etc/asushero (удалить вручную, если не нужны)."
    exit 0
fi

# ---------- 1. снимок ----------
if command -v snapper >/dev/null && [ "${1:-}" != --no-snapshot ]; then
    read -rp "Сделать снимок snapper перед пробой? [Д/н] " a
    if [[ ! "$a" =~ ^[НнNn] ]]; then
        n=$(snapper -c root create --print-number --cleanup-algorithm number \
                --description "перед пробным запуском asushero")
        echo "Снимок #$n создан. Откат: загрузиться в него из меню загрузчика или snapper rollback $n"
    fi
fi

# ---------- 2. права D-Bus и polkit ----------
install -Dm644 data/org.asushero.Daemon.conf "$DBUS_CONF"
install -Dm644 data/org.asushero.policy "$POLKIT"
reload_dbus

# ---------- 3. настройки: при первом запуске переносим из asusd ----------
if [ ! -e /etc/asushero/config.json ]; then
    echo "Переношу настройки из /etc/asusd:"
    python3 -m asushero.cli import-asusd
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
echo "asusherod запущен. Проверка в другом терминале: python3 -m asushero.cli   (Ctrl+C — стоп)"
python3 -m asushero.daemon --debug || true
