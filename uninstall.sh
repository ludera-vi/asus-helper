#!/bin/bash
# Удаление Asus-helper: демон, значок, ярлыки, рабочий стол на встроенной видеокарте и prime-run.
#   ./uninstall.sh           настройки /etc/asus-helper остаются
#   ./uninstall.sh --purge   и настройки тоже

set -uo pipefail
B=$'\e[1m'; R=$'\e[0m'; GREEN=$'\e[32m'
ok() { echo "  ${GREEN}✔${R} $*"; }

[ $EUID -ne 0 ] || { echo "Запускай от обычного пользователя: ./uninstall.sh"; exit 1; }
read -rp "Удалить Asus-helper? [д/Н] " a
[[ "$a" =~ ^([YyДд]|да)$ ]] || exit 0
sudo -v || exit 1

pkill -f '^/usr/bin/python3 -m asushelper.app' 2>/dev/null
rm -f ~/.config/autostart/asus-helper.desktop ~/.local/share/applications/asus-helper.desktop \
      ~/.local/share/icons/hicolor/scalable/apps/asus-helper.svg
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1
ok "Значок и ярлыки убраны"

sudo systemctl disable --now asus-helperd.service 2>/dev/null
sudo rm -f /etc/systemd/system/asus-helperd.service /etc/dbus-1/system.d/org.asushelper.Daemon.conf \
           /usr/share/polkit-1/actions/org.asushelper.policy \
           /usr/local/bin/asus-helperd /usr/local/bin/asus-helper-cli /usr/local/bin/asus-helper /usr/local/bin/asus-helper-agent
sudo rm -rf /usr/local/lib/asus-helper /var/lib/asus-helper
sudo busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig >/dev/null
sudo systemctl daemon-reload
ok "Демон удалён"

# NVIDIA не должна остаться выключенной в BIOS без программы, которая умеет её включить
dgpu=/sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value
if [ "$(cat $dgpu 2>/dev/null)" = 1 ]; then
    read -rp "NVIDIA выключена (Eco). Включить перед удалением? [Д/н] " a
    if [[ ! "$a" =~ ^[НнNn] ]]; then
        echo 0 | sudo tee $dgpu >/dev/null && sudo sh -c 'sleep 2; echo 1 > /sys/bus/pci/rescan' && ok "NVIDIA включена (драйвер загрузится после перезагрузки)"
    fi
fi

rm -f ~/.config/environment.d/90-kwin-igpu.conf ~/.config/environment.d/91-igpu-apps.conf \
      ~/.config/systemd/user/plasma-kwin_wayland.service.d/asus-helper-igpu.conf
systemctl --user daemon-reload
sudo rm -f /etc/udev/rules.d/61-igpu-symlink.rules /usr/local/bin/prime-run
sudo udevadm control --reload
ok "Рабочий стол на встроенной видеокарте и prime-run убраны (выйди из сеанса и войди снова)"

if [ "${1:-}" = --purge ]; then
    sudo rm -rf /etc/asus-helper && rm -rf ~/.config/asus-helper && ok "Настройки удалены"
else
    echo "  Настройки остались в /etc/asus-helper (удалить: ./uninstall.sh --purge)"
fi
echo "${B}Готово.${R}"
