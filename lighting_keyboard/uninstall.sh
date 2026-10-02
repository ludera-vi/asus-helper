#!/bin/bash
# Удаление asus-osd. Запуск: ./uninstall.sh

set -uo pipefail

BIN="$HOME/.local/bin/asus-osd"
UNIT="$HOME/.config/systemd/user/asus-osd.service"

B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'; GREEN=$'\e[32m'; BLUE=$'\e[34m'
OK="${GREEN}✔${R}"

echo
echo "${B}${BLUE}━━ Удаление asus-osd ━━${R}"
read -rp "  ${B}?${R} Удалить asus-osd (карточки для Fn+F5 и подсветки)? [Д/н] " ans
[[ "${ans:-Y}" =~ ^([YyДд]|yes|да|Да)$ ]] || { echo "  Отменено."; exit 0; }
echo

if systemctl --user is-enabled -q asus-osd 2>/dev/null || systemctl --user is-active -q asus-osd 2>/dev/null; then
    systemctl --user disable --now asus-osd >/dev/null 2>&1
    echo "  $OK Служба остановлена и отключена"
fi
for f in "$UNIT" "$BIN"; do
    if [ -e "$f" ]; then rm -f "$f" && echo "  $OK Удалён ${f/#$HOME/\~}"
    else echo "  ${D}– ${f/#$HOME/\~} (не было)${R}"; fi
done
systemctl --user daemon-reload

echo
echo "  ${GREEN}${B}Готово.${R} Карточки для Fn+F5 и подсветки больше показываться не будут."
echo
