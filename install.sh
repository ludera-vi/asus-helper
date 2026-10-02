#!/bin/bash
# Установщик Asus-helper (Arch и производные, KDE Plasma 6). Ставится на систему без asusctl,
# power-profiles-daemon, supergfxctl и envycontrol — если они есть, установщик скажет, что удалить.
# Запуск: ./install.sh   (от обычного пользователя, sudo спросит сам). Удаление: ./uninstall.sh

set -uo pipefail

SRC=$(dirname "$(readlink -f "$0")")
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/asus-helper-install.log"
LIB=/usr/local/lib/asus-helper
BIN=/usr/local/bin
APPS="$HOME/.local/share/applications"
AUTOSTART="$HOME/.config/autostart"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"

# ---------- оформление ----------
B=$'\e[1m'; D=$'\e[2m'; R=$'\e[0m'
GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'; BLUE=$'\e[34m'
OK="${GREEN}✔${R}"; WARN="${YELLOW}!${R}"; FAIL="${RED}✖${R}"; INFO="${BLUE}•${R}"

RESULTS=()
FAILED=0

title()   { echo; echo "${B}${BLUE}━━ $* ━━${R}"; }
ok()      { echo "  $OK $*"; }
warn()    { echo "  $WARN $*"; }
fail()    { echo "  $FAIL $*"; }
info()    { echo "  $INFO $*"; }
explain() { echo "    ${D}$*${R}"; }

ask() {
    local def=${2:-Y} hint ans
    [ "$def" = Y ] && hint="[Д/н]" || hint="[д/Н]"
    read -rp "  ${B}?${R} $1 $hint " ans
    ans=${ans:-$def}
    [[ "$ans" =~ ^([YyДд]|yes|да|Да)$ ]]
}

step() {
    local desc=$1; shift
    echo "### $desc: $*" >> "$LOG"
    if "$@" >> "$LOG" 2>&1; then
        ok "$desc"; RESULTS+=("$OK $desc")
    else
        fail "$desc ${D}(подробности: $LOG)${R}"; RESULTS+=("$FAIL $desc"); FAILED=1
        return 1
    fi
}

unit_exists() { systemctl cat "$1" >/dev/null 2>&1; }
user_unit_exists() { systemctl --user cat "$1" >/dev/null 2>&1; }

mkdir -p "$(dirname "$LOG")"
echo "=== asus-helper install $(date) ===" > "$LOG"

clear 2>/dev/null
cat <<EOF
${B}
   ┌──────────────────────────────────────────────┐
   │   Asus-helper · ноутбук ASUS ROG в Linux      │
   │   режимы, вентиляторы, видеокарта,            │
   │   подсветка, Slash, батарея — как G-Helper    │
   └──────────────────────────────────────────────┘${R}
EOF

[ $EUID -ne 0 ] || { fail "Запускай от обычного пользователя: ./install.sh (sudo спросится сам)"; exit 1; }

# ---------- 1. проверка ----------
title "Проверка системы"
problems=0
vendor=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null)
model=$(cat /sys/class/dmi/id/product_name 2>/dev/null)
if [[ "$vendor" == ASUS* ]]; then ok "Ноутбук: $model"; else fail "Это не ASUS ($vendor)"; problems=1; fi
if [ -e /sys/firmware/acpi/platform_profile ]; then ok "Режимы производительности (platform_profile)"; else fail "Нет /sys/firmware/acpi/platform_profile"; problems=1; fi
if [ -d /sys/class/firmware-attributes/asus-armoury ]; then ok "Ядро с asus-armoury"; else warn "Нет asus-armoury — лимиты мощности будут недоступны"; fi

missing=()
python3 -c 'import gi' 2>/dev/null || missing+=(python-gobject)
python3 -c 'import PySide6' 2>/dev/null || missing+=(pyside6)
command -v kscreen-doctor >/dev/null || missing+=(libkscreen)
if [ ${#missing[@]} -eq 0 ]; then ok "Пакеты: python-gobject, pyside6, kscreen-doctor"
else warn "Не хватает пакетов: ${missing[*]} — поставлю"; fi
[ $problems -eq 0 ] || { fail "Установка невозможна"; exit 1; }

# Ставим только на чистую систему: эти программы делают то же самое и будут спорить с демоном
conflicts=()
for p in asusctl rog-control-center power-profiles-daemon supergfxctl envycontrol optimus-manager; do
    pacman -Q "$p" >/dev/null 2>&1 && conflicts+=("$p")
done
old=()
[ -e /usr/local/bin/gpu-eco ] && old+=("gpu-switch (gpu-eco)")
[ -e "$HOME/.local/bin/asus-osd" ] && old+=("lighting_keyboard (asus-osd)")
if [ ${#conflicts[@]} -gt 0 ] || [ ${#old[@]} -gt 0 ]; then
    fail "Мешают другие программы управления ноутбуком:"
    [ ${#conflicts[@]} -gt 0 ] && explain "пакеты: ${conflicts[*]}  →  sudo pacman -Rns ${conflicts[*]}"
    [ ${#old[@]} -gt 0 ] && explain "старые помощники: ${old[*]}  →  их ./uninstall.sh"
    explain "Удалите их и запустите установку снова."
    exit 1
fi
ok "Конфликтующих программ нет"

# Встроенная видеокарта — на ней будет рабочий стол, чтобы NVIDIA выключалась без выхода из сеанса
IGPU_PCI=""; IGPU_VENDOR=""
for c in /sys/class/drm/card[0-9]*; do
    [ -e "$c/device/vendor" ] || continue
    v=$(cat "$c/device/vendor")
    [ "$v" = 0x10de ] && continue
    pci=$(basename "$(readlink -f "$c/device")")
    if [ -z "$IGPU_PCI" ] || [ "$(cat "$c/device/boot_vga" 2>/dev/null)" = 1 ]; then
        IGPU_PCI=$pci; IGPU_VENDOR=$v
    fi
done
case "$IGPU_VENDOR" in
    0x8086) IGPU_NAME="Intel"; ICD_GLOB="intel*_icd*.json" ;;
    0x1002) IGPU_NAME="AMD";   ICD_GLOB="radeon_icd*.json" ;;
    *)      IGPU_NAME="" ;;
esac
[ -n "$IGPU_PCI" ] && ok "Встроенная видеокарта: $IGPU_NAME ($IGPU_PCI)" || warn "Встроенная видеокарта не найдена"

dev_daemon=$(pgrep -f '^python3 -m asushelper.daemon' || true)

# ---------- 2. план ----------
title "Что будет сделано"
info "Демон ${B}asus-helperd${R} — системная служба, стартует при загрузке"
explain "/usr/local/lib/asus-helper, /usr/local/bin/asus-helper{d,-cli,}, права D-Bus и polkit"
info "Значок ${B}Asus-helper${R} в трее при входе в систему, клавиша ROG открывает окно"
info "Настройки: /etc/asus-helper (если их нет — переносятся из /etc/asusd)"
[ -n "$dev_daemon" ] && info "Пробный демон из dev-run.sh (сейчас запущен) будет остановлен"

DO_KWIN=0; DO_APPS=0
if [ -n "$IGPU_PCI" ]; then
    echo
    info "${B}Рабочий стол KDE всегда на $IGPU_NAME${R}"
    explain "Тогда NVIDIA выключается (Eco) одной кнопкой, без выхода из сеанса."
    explain "Минус: HDMI (обычно подключён к NVIDIA) не работает, пока настройка включена."
    ask "Рабочий стол на $IGPU_NAME? (рекомендуется)" && DO_KWIN=1
    echo
    info "${B}Запрещать программам будить NVIDIA${R} (обычно не нужно)"
    explain "Нет (по умолчанию): в Стандарте программы и игры сами берут NVIDIA; в Eco всё на $IGPU_NAME."
    explain "Да: всё всегда на $IGPU_NAME, NVIDIA — только через prime-run. Экономнее в Стандарте,"
    explain "но игры придётся запускать через prime-run (в Steam: prime-run %command%)."
    ask "Запрещать программам будить NVIDIA?" N && DO_APPS=1
fi
echo
ask "Продолжить?" || { info "Ничего не изменено"; exit 0; }

# ---------- 3. снимок ----------
if command -v snapper >/dev/null && snapper list-configs 2>/dev/null | grep -q '^root'; then
    title "Снимок системы"
    if ask "Сделать снимок snapper перед установкой?"; then
        sudo -v || exit 1
        n=$(sudo snapper -c root create --print-number --cleanup-algorithm number --description "перед установкой Asus-helper" 2>>"$LOG")
        if [ -n "$n" ]; then ok "Снимок #$n — откат: загрузиться в него из меню загрузчика"; RESULTS+=("$OK Снимок #$n")
        else warn "Снимок не создан (журнал: $LOG)"; fi
    fi
fi

# ---------- 4. установка ----------
title "Установка"
sudo -v || exit 1
[ ${#missing[@]} -eq 0 ] || step "Пакеты ${missing[*]}" sudo pacman -S --needed --noconfirm "${missing[@]}"

if [ -n "$dev_daemon" ]; then
    # пробный демон из dev-run.sh — заменяется службой
    step "Остановка пробного демона" sudo kill $dev_daemon
    sleep 3
fi
systemctl --user stop asus-helper-dev.service 2>/dev/null

install_lib() {
    sudo rm -rf "$LIB" &&
    sudo install -d "$LIB" &&
    sudo cp -r "$SRC/asushelper" "$LIB/" &&
    sudo find "$LIB" -name '__pycache__' -prune -exec rm -rf {} + &&
    sudo chmod -R a+rX "$LIB"
}
step "Программа → $LIB" install_lib

wrapper() {   # wrapper имя модуль
    printf '#!/bin/sh\n# Asus-helper: %s\nPYTHONPATH=%s exec /usr/bin/python3 -m %s "$@"\n' "$1" "$LIB" "$2" |
        sudo tee "$BIN/$1" >/dev/null && sudo chmod 755 "$BIN/$1"
}
install_bins() {
    wrapper asus-helperd asushelper.daemon &&
    wrapper asus-helper-cli asushelper.cli &&
    wrapper asus-helper asushelper.app &&
    wrapper asus-helper-agent asushelper.agent
}
step "Команды asus-helperd, asus-helper-cli, asus-helper" install_bins

install_system() {
    sudo install -Dm644 "$SRC/data/org.asushelper.Daemon.conf" /etc/dbus-1/system.d/org.asushelper.Daemon.conf &&
    sudo install -Dm644 "$SRC/data/org.asushelper.policy" /usr/share/polkit-1/actions/org.asushelper.policy &&
    sudo install -Dm644 "$SRC/data/asus-helperd.service" /etc/systemd/system/asus-helperd.service &&
    sudo install -d -m 755 /etc/asus-helper /var/lib/asus-helper &&
    sudo busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig &&
    sudo systemctl daemon-reload
}
step "Служба, права D-Bus и polkit" install_system

# старые файлы прав от пробных запусков под прежними именами
sudo rm -f /etc/dbus-1/system.d/org.{asushero,asusludera}.Daemon.conf \
           /usr/share/polkit-1/actions/org.{asushero,asusludera}.policy

if [ ! -e /etc/asus-helper/config.json ]; then
    if [ -d /etc/asusd ]; then
        step "Перенос настроек из /etc/asusd" sudo env PYTHONPATH="$LIB" python3 -m asushelper.cli import-asusd
    fi
else
    ok "Настройки /etc/asus-helper сохранены"
fi

# ---------- 5. служба ----------
step "Демон asus-helperd запущен и включён" sudo systemctl enable --now asus-helperd.service

# ---------- 6. встроенная видеокарта ----------
ENVD="$HOME/.config/environment.d"
if [ $DO_KWIN = 1 ]; then
    install_kwin() {
        echo "SUBSYSTEM==\"drm\", KERNEL==\"card*\", KERNELS==\"$IGPU_PCI\", SYMLINK+=\"dri/igpu\"" \
            | sudo tee /etc/udev/rules.d/61-igpu-symlink.rules >/dev/null &&
        sudo udevadm control --reload &&
        sudo udevadm trigger --subsystem-match=drm --action=add &&
        sudo udevadm settle &&
        [ -e /dev/dri/igpu ] &&
        mkdir -p "$ENVD" &&
        echo "KWIN_DRM_DEVICES=/dev/dri/igpu" > "$ENVD/90-kwin-igpu.conf"
    }
    step "Рабочий стол на $IGPU_NAME (/dev/dri/igpu)" install_kwin
fi
if [ $DO_APPS = 1 ]; then
    install_apps() {
        local icds
        icds=$(ls /usr/share/vulkan/icd.d/$ICD_GLOB 2>/dev/null | paste -sd:)
        mkdir -p "$ENVD" && {
            echo "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json"
            echo "__GLX_VENDOR_LIBRARY_NAME=mesa"
            [ -n "$icds" ] && echo "VK_DRIVER_FILES=$icds"
        } > "$ENVD/91-igpu-apps.conf"
    }
    step "Программы по умолчанию на $IGPU_NAME" install_apps
fi
step "prime-run — запуск на NVIDIA" sudo install -m 755 "$SRC/data/prime-run" "$BIN/prime-run"

# ---------- 7. рабочий стол ----------
title "Значок и окно"
install_desktop() {
    install -Dm644 "$SRC/data/icons/asus-helper.svg" "$ICONS/asus-helper.svg" &&
    install -Dm644 "$SRC/data/asus-helper.desktop" "$APPS/asus-helper.desktop" &&
    install -Dm644 "$SRC/data/asus-helper-autostart.desktop" "$AUTOSTART/asus-helper.desktop" &&
    { command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true; }
}
step "Ярлык, автозапуск, клавиша ROG" install_desktop
pkill -f '^/usr/bin/python3 -m asushelper.app' 2>/dev/null
pkill -f '^python3 -m asushelper.app' 2>/dev/null
pkill -f '^python3 -m asushelper.agent' 2>/dev/null
sleep 1
( setsid "$BIN/asus-helper" >/dev/null 2>&1 & )
ok "Asus-helper запущен — значок в трее"

# ---------- 8. проверка ----------
title "Проверка"
sleep 2
if systemctl is-active -q asus-helperd; then ok "asus-helperd работает"; else fail "asus-helperd не запустился: journalctl -u asus-helperd"; FAILED=1; fi
if "$BIN/asus-helper-cli" >>"$LOG" 2>&1; then ok "Демон отвечает"; else fail "Демон не отвечает (журнал: $LOG)"; FAILED=1; fi

title "Итог"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo
if [ $FAILED -eq 0 ]; then
    echo "  ${GREEN}${B}Готово.${R} Значок Asus-helper — в трее; клавиша ROG открывает окно."
    [ $DO_KWIN = 1 ] || [ $DO_APPS = 1 ] && echo "  ${YELLOW}Выйди из сеанса и войди снова${R} — чтобы рабочий стол перешёл на $IGPU_NAME."
else
    echo "  ${YELLOW}${B}Установлено с ошибками.${R} Журнал: $LOG"
fi
cat <<EOF

  ${D}Терминал:  asus-helper-cli          (состояние и команды)
  Журнал:    journalctl -u asus-helperd -f
  Удаление:  ./uninstall.sh${R}

EOF
