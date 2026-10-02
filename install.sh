#!/bin/bash
# Установщик Asus-helper: замена asusd / rog-control-center / gpu-eco / asus-osd (Arch и производные).
# Запуск: ./install.sh   (от обычного пользователя, sudo спросит сам)
#
# Ничего не удаляет. asusd и старые помощники только выключаются (systemctl mask/disable);
# ./uninstall.sh возвращает всё как было.

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

dev_daemon=$(pgrep -f '^python3 -m asushelper.daemon' || true)

# ---------- 2. план ----------
title "Что будет сделано"
info "Демон ${B}asus-helperd${R} — системная служба, стартует при загрузке"
explain "/usr/local/lib/asus-helper, /usr/local/bin/asus-helper{d,-cli,}, права D-Bus и polkit"
info "Значок ${B}Asus-helper${R} в трее при входе в систему, клавиша ROG открывает окно"
info "Настройки: /etc/asus-helper (если их нет — переносятся из /etc/asusd)"
echo
info "Выключаются (${B}не удаляются${R}), ./uninstall.sh вернёт:"
unit_exists asusd.service         && explain "asusd, asus-shutdown — systemctl mask"
unit_exists gpu-eco-fixup.service && explain "gpu-eco-fixup — его работу (уборка NVIDIA перед сном) делает демон"
user_unit_exists asus-osd.service && explain "asus-osd — карточки KDE теперь показывает Asus-helper"
[ -n "$dev_daemon" ] && explain "пробный демон из dev-run.sh (сейчас запущен) — будет остановлен"
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
    # dev-run.sh при выходе снимает временную маску asusd и запускает его — дальше мы его выключим насовсем
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

# ---------- 5. старое выключаем ----------
title "Замена asusd и старых помощников"
if unit_exists asusd.service; then
    sudo systemctl unmask --runtime asusd.service >/dev/null 2>&1   # временная маска от dev-run.sh
    step "asusd выключен (mask)" sudo systemctl mask --now asusd.service asus-shutdown.service
fi
if unit_exists gpu-eco-fixup.service && systemctl is-enabled -q gpu-eco-fixup.service 2>/dev/null; then
    step "gpu-eco-fixup выключен" sudo systemctl disable --now gpu-eco-fixup.service
fi
if user_unit_exists asus-osd.service && systemctl --user is-enabled -q asus-osd.service 2>/dev/null; then
    step "asus-osd выключен" systemctl --user disable --now asus-osd.service
fi

step "Демон asus-helperd запущен и включён" sudo systemctl enable --now asus-helperd.service

# ---------- 6. рабочий стол ----------
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

# ---------- 7. проверка ----------
title "Проверка"
sleep 2
if systemctl is-active -q asus-helperd; then ok "asus-helperd работает"; else fail "asus-helperd не запустился: journalctl -u asus-helperd"; FAILED=1; fi
if "$BIN/asus-helper-cli" >>"$LOG" 2>&1; then ok "Демон отвечает"; else fail "Демон не отвечает (журнал: $LOG)"; FAILED=1; fi
if systemctl is-active -q asusd 2>/dev/null; then warn "asusd всё ещё работает"; else ok "asusd выключен"; fi

title "Итог"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo
if [ $FAILED -eq 0 ]; then
    echo "  ${GREEN}${B}Готово.${R} Значок Asus-helper — в трее; клавиша ROG открывает окно."
else
    echo "  ${YELLOW}${B}Установлено с ошибками.${R} Журнал: $LOG"
fi
cat <<EOF

  ${D}Терминал:  asus-helper-cli          (состояние и команды)
  Журнал:    journalctl -u asus-helperd -f
  Удаление:  ./uninstall.sh            (вернёт asusd и старые помощники)${R}

EOF
