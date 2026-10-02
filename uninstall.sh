#!/bin/bash
# Удаление Asus-helper и возврат как было: asusd, asus-shutdown, gpu-eco-fixup, asus-osd снова включаются.
#   ./uninstall.sh           настройки /etc/asus-helper остаются
#   ./uninstall.sh --purge   и настройки тоже

set -uo pipefail
B=$'\e[1m'; R=$'\e[0m'; GREEN=$'\e[32m'
ok() { echo "  ${GREEN}✔${R} $*"; }

[ $EUID -ne 0 ] || { echo "Запускай от обычного пользователя: ./uninstall.sh"; exit 1; }
read -rp "Удалить Asus-helper и вернуть asusd? [д/Н] " a
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

if systemctl cat asusd.service >/dev/null 2>&1; then
    sudo systemctl unmask asusd.service asus-shutdown.service
    sudo systemctl start asusd.service && ok "asusd снова работает"
fi
systemctl cat gpu-eco-fixup.service >/dev/null 2>&1 && sudo systemctl enable --now gpu-eco-fixup.service && ok "gpu-eco-fixup включён"
systemctl --user cat asus-osd.service >/dev/null 2>&1 && systemctl --user enable --now asus-osd.service && ok "asus-osd включён"

if [ "${1:-}" = --purge ]; then
    sudo rm -rf /etc/asus-helper && rm -rf ~/.config/asus-helper && ok "Настройки удалены"
else
    echo "  Настройки остались в /etc/asus-helper (удалить: ./uninstall.sh --purge)"
fi
echo "${B}Готово.${R}"
