#!/bin/bash
# Удаление gpu-switch: возвращает систему к состоянию до установки.
# Запуск: ./uninstall.sh   (от обычного пользователя, sudo спросит сам)

set -uo pipefail

ENVD="$HOME/.config/environment.d"
WIDGET_ID=org.vi.gpueco

B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'; GREEN=$'\e[32m'; RED=$'\e[31m'; BLUE=$'\e[34m'
OK="${GREEN}✔${R}"; FAIL="${RED}✖${R}"; INFO="${BLUE}•${R}"

ask() {
    local ans; read -rp "  ${B}?${R} $1 [Д/н] " ans
    [[ "${ans:-Y}" =~ ^([YyДд]|yes|да|Да)$ ]]
}
rm_file() {   # rm_file "описание" путь [sudo]
    if [ -e "$2" ] || [ -L "$2" ]; then
        if ${3:-} rm -f "$2"; then echo "  $OK $1"; else echo "  $FAIL $1"; fi
    else
        echo "  ${D}– $1 (не было)${R}"
    fi
}

if [ $EUID -eq 0 ]; then echo "Запустите от обычного пользователя: ./uninstall.sh"; exit 1; fi

echo
echo "${B}${BLUE}━━ Удаление gpu-switch ━━${R}"
echo "  Будут удалены: команда gpu-eco, сервис gpu-eco-fixup, разрешение sudo, значок, ярлык,"
echo "  настройки рабочего стола и prime-run из ~/.local/bin."
echo
ask "Удалить gpu-switch?" || { echo "  Отменено."; exit 0; }

sudo -v || { echo "  $FAIL sudo не получен — ничего не изменено"; exit 1; }
echo

# Не оставляем пользователя с выключенной видеокартой
if command -v gpu-eco >/dev/null && [ "$(gpu-eco state 2>/dev/null)" = off ]; then
    echo "  $INFO NVIDIA сейчас выключена (Eco)."
    if ask "Включить её перед удалением (иначе она останется выключенной в BIOS)?"; then
        sudo /usr/local/bin/gpu-eco on && echo "  $OK NVIDIA включена" || echo "  $FAIL не удалось — после удаления включите вручную, см. README («NVIDIA пропала совсем»)"
    fi
fi

if [ -e /etc/systemd/system/gpu-eco-fixup.service ]; then
    sudo systemctl disable gpu-eco-fixup.service >/dev/null 2>&1
    rm_file "Сервис gpu-eco-fixup"             /etc/systemd/system/gpu-eco-fixup.service sudo
    sudo systemctl daemon-reload
fi
rm_file "Команда gpu-eco"                      /usr/local/bin/gpu-eco sudo
rm_file "Разрешение sudo"                      /etc/sudoers.d/gpu-eco sudo
if [ -e /etc/udev/rules.d/61-igpu-symlink.rules ]; then
    rm_file "Правило udev /dev/dri/igpu"       /etc/udev/rules.d/61-igpu-symlink.rules sudo
    sudo udevadm control --reload
fi
rm_file "Рабочий стол только на iGPU"          "$ENVD/90-kwin-igpu.conf"
rm_file "Программы по умолчанию на iGPU"       "$ENVD/91-igpu-apps.conf"
if grep -q gpu-switch "$HOME/.local/bin/prime-run" 2>/dev/null; then
    rm_file "prime-run (из gpu-switch)"        "$HOME/.local/bin/prime-run"
fi
rm_file "Ярлык в меню"                          "$HOME/.local/share/applications/gpu-eco.desktop"
if command -v kpackagetool6 >/dev/null && kpackagetool6 -t Plasma/Applet -s "$WIDGET_ID" >/dev/null 2>&1; then
    kpackagetool6 -t Plasma/Applet -r "$WIDGET_ID" >/dev/null 2>&1 \
        && echo "  $OK Значок на панели" || echo "  $FAIL Значок на панели"
fi

echo
echo "  ${GREEN}${B}Готово.${R} Выйдите из сеанса и войдите снова, чтобы вернуть настройки рабочего стола."
echo "  Если значок остался на панели серым — удалите его правым кликом."
echo
