#!/bin/bash
# Установщик Asus-helper (Arch и производные, KDE Plasma 6). Ставится на систему без asusctl,
# power-profiles-daemon, supergfxctl и envycontrol — если они есть, установщик скажет, что удалить.
# Запуск: ./install.sh   (от обычного пользователя, sudo спросит сам). Удаление: ./uninstall.sh
#         ./install.sh --update   обновить уже установленное: без вопросов и снимка, с перезапуском

set -uo pipefail

SRC=$(dirname "$(readlink -f "$0")")
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/asus-helper-install.log"
LIB=/usr/local/lib/asus-helper
BIN=/usr/local/bin
# Пакет (AUR) ставит в /usr; руками — в /usr/local, а права D-Bus и правило udev — в /etc
# (в /usr/local они их не ищут). Те же пути у uninstall.sh.
MAKE_ARGS=(PREFIX=/usr/local UDEVDIR=/etc/udev/rules.d DBUSDIR=/etc/dbus-1/system.d
           POLKITDIR=/usr/share/polkit-1/actions)

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

UPDATE=0
[ "${1:-}" = --update ] && UPDATE=1
if [ $UPDATE = 1 ] && [ ! -e /usr/local/lib/systemd/system/asus-helperd.service ] && [ ! -e /etc/systemd/system/asus-helperd.service ]; then
    echo "Asus-helper ещё не установлен — запустите ./install.sh без --update"; exit 1
fi

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
command -v make >/dev/null || missing+=(make)
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

dev_daemon=$(pgrep -f '^python3 -m asushelper.daemon' || true)

if [ $UPDATE = 0 ]; then
# ---------- 2. план ----------
title "Что будет сделано"
info "Демон ${B}asus-helperd${R} — системная служба, стартует при загрузке"
explain "/usr/local/lib/asus-helper, /usr/local/bin/asus-helper{d,-cli,}, prime-run, права D-Bus и polkit"
info "Значок ${B}Asus-helper${R} в трее при входе в систему, клавиша ROG открывает окно"
info "Настройки: /etc/asus-helper (если их нет — переносятся из /etc/asusd)"
[ -n "$dev_daemon" ] && info "Пробный демон из dev-run.sh (сейчас запущен) будет остановлен"

info "Рабочий стол KDE — на встроенной видеокарте (если есть NVIDIA): так Eco включается без выхода из сеанса"
explain "Это решает демон при загрузке; без NVIDIA или в режиме MUX «только NVIDIA» ничего не меняется"
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

fi   # конец: только при обычной установке

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

# Остатки прежних версий установщика (ставили в другие места) — убираем, чтобы не было двойников
cleanup_old() {
    sudo rm -f /etc/systemd/system/asus-helperd.service /etc/udev/rules.d/61-igpu-symlink.rules \
               /etc/dbus-1/system.d/org.{asushero,asusludera}.Daemon.conf \
               /usr/share/polkit-1/actions/org.{asushero,asusludera}.policy
    rm -f "$HOME/.config/systemd/user/plasma-kwin_wayland.service.d/asus-helper-igpu.conf" \
          "$HOME/.config/environment.d/90-kwin-igpu.conf" "$HOME/.config/environment.d/91-igpu-apps.conf" \
          "$HOME/.local/share/applications/asus-helper.desktop" "$HOME/.config/autostart/asus-helper.desktop" \
          "$HOME/.local/share/icons/hicolor/scalable/apps/asus-helper.svg"
    rmdir "$HOME/.config/systemd/user/plasma-kwin_wayland.service.d" 2>/dev/null
    true
}
step "Остатки прежних версий убраны" cleanup_old

install_files() {
    sudo rm -rf "$LIB" &&
    sudo make -C "$SRC" install "${MAKE_ARGS[@]}" &&
    sudo install -d -m 755 /etc/asus-helper /var/lib/asus-helper
}
step "Программа, служба, права, ярлык, автозапуск" install_files

reload_system() {
    sudo busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig &&
    sudo udevadm control --reload &&
    sudo udevadm trigger --subsystem-match=drm --action=add && sudo udevadm settle &&
    sudo systemctl daemon-reload &&
    systemctl --user daemon-reload &&
    { command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true; }
}
step "Перечитаны systemd, D-Bus, udev, меню KDE" reload_system

if [ ! -e /etc/asus-helper/config.json ] && [ -d /etc/asusd ]; then
    step "Перенос настроек из /etc/asusd" sudo env PYTHONPATH="$LIB" python3 -m asushelper.cli import-asusd
fi

step "Демон asus-helperd включён" sudo systemctl enable asus-helperd.service
step "Демон запущен с новой версией" sudo systemctl restart asus-helperd.service

# KWin читает /run/asus-helper/kwin.env только при входе в сеанс. Если сейчас он держит NVIDIA,
# Eco заработает после одного выхода из сеанса
sleep 2
need_relogin=0
if grep -q KWIN_DRM_DEVICES /run/asus-helper/kwin.env 2>/dev/null &&
   "$BIN/asus-helper-cli" gpu 2>/dev/null | grep -q kwin_wayland; then
    need_relogin=1
fi

title "Значок и окно"
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
    [ $need_relogin = 1 ] && echo "  ${YELLOW}Один раз выйди из сеанса и войди снова${R} — тогда Eco будет включаться без выхода."
else
    echo "  ${YELLOW}${B}Установлено с ошибками.${R} Журнал: $LOG"
fi
cat <<EOF

  ${D}Терминал:  asus-helper-cli          (состояние и команды)
  Журнал:    journalctl -u asus-helperd -f
  Удаление:  ./uninstall.sh${R}

EOF
