#!/bin/bash
# Remove Asus-helper / удаление: daemon, tray icon, launchers, desktop GPU setting, prime-run.
#   ./uninstall.sh           settings in /etc/asus-helper are kept / настройки остаются
#   ./uninstall.sh --purge   settings are removed too / и настройки тоже

set -uo pipefail
B=$'\e[1m'; R=$'\e[0m'; GREEN=$'\e[32m'
ok() { echo "  ${GREEN}✔${R} $*"; }

# язык — выбранный при установке (или позже в окне): из настроек, иначе из журнала установки
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/asus-helper-install.log"
UILANG=$(grep -o '"language": *"[a-z]*"' /etc/asus-helper/config.json 2>/dev/null | grep -o '[a-z]*"$' | tr -d '"')
[ -n "$UILANG" ] || UILANG=$(head -1 "$LOG" 2>/dev/null | grep -o 'lang=[a-z]*' | cut -d= -f2)
[ -n "$UILANG" ] || case "${LANG:-}" in ru*) UILANG=ru ;; *) UILANG=en ;; esac
L() { if [ "$UILANG" = ru ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }
# и сообщения sudo, systemctl и прочих — на том же языке
if [ "$UILANG" = ru ] && locale -a 2>/dev/null | grep -qi '^ru_RU.utf-\?8$'; then
    export LC_MESSAGES=ru_RU.UTF-8 LANGUAGE=ru
elif [ "$UILANG" = en ]; then
    export LC_MESSAGES=C.UTF-8; unset LANGUAGE
fi

[ $EUID -ne 0 ] || { L "Запускай от обычного пользователя: ./uninstall.sh" "Run as a regular user: ./uninstall.sh"; echo; exit 1; }
read -rp "$(L "Удалить Asus-helper? [д/Н] " "Remove Asus-helper? [y/N] ")" a
[[ "$a" =~ ^([YyДд]|yes|да)$ ]] || exit 0
sudo -v || exit 1

pkill -f '^/usr/bin/python3 -m asushelper.app' 2>/dev/null
rm -f ~/.config/autostart/asus-helper.desktop ~/.local/share/applications/asus-helper.desktop \
      ~/.local/share/icons/hicolor/scalable/apps/asus-helper.svg
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1
# клавиша окна в «Комбинациях клавиш» KDE
command -v qdbus6 >/dev/null && qdbus6 org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.unregister \
    asus-helper toggle >/dev/null 2>&1
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/asus-helper"
ok "$(L "Значок, ярлыки и клавиша окна убраны" "Tray icon, launchers and window key removed")"

sudo systemctl disable --now asus-helperd.service 2>/dev/null
cd "$(dirname "$(readlink -f "$0")")"
sudo make uninstall PREFIX=/usr/local UDEVDIR=/etc/udev/rules.d DBUSDIR=/etc/dbus-1/system.d \
    POLKITDIR=/usr/share/polkit-1/actions >/dev/null
# и файлы прежних версий установщика
sudo rm -f /etc/systemd/system/asus-helperd.service
sudo rm -rf /var/lib/asus-helper /run/asus-helper
sudo busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig >/dev/null
sudo systemctl daemon-reload
ok "$(L "Демон удалён" "Daemon removed")"

# дискретная видеокарта не должна остаться выключенной в BIOS без программы, которая умеет её включить
dgpu=$(ls /sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value \
           /sys/devices/platform/asus-nb-wmi/dgpu_disable 2>/dev/null | head -1)
if [ -n "$dgpu" ] && [ "$(cat "$dgpu" 2>/dev/null)" = 1 ]; then
    read -rp "$(L "Дискретная видеокарта выключена (Eco). Включить перед удалением? [Д/н] " "The discrete GPU is off (Eco). Turn it on before removing? [Y/n] ")" a
    if [[ ! "$a" =~ ^[НнNn] ]]; then
        echo 0 | sudo tee "$dgpu" >/dev/null && sudo sh -c 'sleep 2; echo 1 > /sys/bus/pci/rescan' &&
            ok "$(L "Дискретная видеокарта включена (драйвер загрузится после перезагрузки)" "Discrete GPU turned on (the driver loads after reboot)")"
    fi
fi

rm -f ~/.config/environment.d/90-kwin-igpu.conf ~/.config/environment.d/91-igpu-apps.conf \
      ~/.config/systemd/user/plasma-kwin_wayland.service.d/asus-helper-igpu.conf
systemctl --user daemon-reload
sudo rm -f /etc/udev/rules.d/61-igpu-symlink.rules
sudo udevadm control --reload
# ссылка /dev/dri/igpu от правила udev: убираем, если рабочий стол сейчас на неё не опирается
# (иначе исчезнет сама после перезагрузки)
kwin=$(pgrep -x kwin_wayland | head -1)
if [ -L /dev/dri/igpu ] && ! { [ -n "$kwin" ] && sudo cat /proc/$kwin/environ 2>/dev/null | tr '\0' '\n' | grep -q '^KWIN_DRM_DEVICES=.*/dev/dri/igpu'; }; then
    sudo rm -f /dev/dri/igpu
fi
ok "$(L "Настройка рабочего стола и prime-run убраны (выйди из сеанса и войди снова)" "Desktop GPU setting and prime-run removed (log out and back in)")"

if [ "${1:-}" = --purge ]; then
    sudo rm -rf /etc/asus-helper && rm -rf ~/.config/asus-helper && ok "$(L "Настройки удалены" "Settings removed")"
else
    echo "  $(L "Настройки остались в /etc/asus-helper (удалить: ./uninstall.sh --purge)" "Settings kept in /etc/asus-helper (remove: ./uninstall.sh --purge)")"
fi
rm -f "$LOG"
echo "${B}$(L "Готово." "Done.")${R}"
