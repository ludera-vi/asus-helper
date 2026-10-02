#!/bin/bash
# Установщик asus-osd: карточки KDE для Fn+F5 (режим) и подсветки клавиатуры на ноутбуках ASUS.
# Запуск: ./install.sh   (от обычного пользователя)

set -uo pipefail

SRC=$(dirname "$(readlink -f "$0")")
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/asus-osd-install.log"
BIN="$HOME/.local/bin/asus-osd"
UNIT="$HOME/.config/systemd/user/asus-osd.service"

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

osd() {   # osd метод сигнатура значение
    busctl --user call org.kde.plasmashell /org/kde/osdService org.kde.osdService "$@" >/dev/null 2>&1
}

mkdir -p "$(dirname "$LOG")"
echo "=== asus-osd install $(date) ===" > "$LOG"

clear 2>/dev/null
cat <<EOF
${B}
   ┌──────────────────────────────────────────────┐
   │   asus-osd · карточки KDE для клавиш ASUS     │
   │   Fn+F5 (режим) и подсветка клавиатуры        │
   └──────────────────────────────────────────────┘${R}

  На ноутбуках ASUS режимом производительности управляет asusd, а подсветкой
  клавиатуры — ядро. Ни один из них не сообщает KDE об изменениях, поэтому
  KDE не показывает свои красивые карточки. asus-osd это исправляет.
EOF

if [ $EUID -eq 0 ]; then
    echo; fail "Запустите от обычного пользователя, не через sudo: ./install.sh"; exit 1
fi

# ---------- 1. проверка ----------
title "1. Проверка системы"

if busctl --user introspect org.kde.plasmashell /org/kde/osdService >/dev/null 2>&1; then
    ok "KDE Plasma — карточки (OSD) доступны"
else
    fail "Не найден сервис карточек KDE (org.kde.osdService)"
    explain "Нужен KDE Plasma 6, и установщик надо запускать внутри сеанса KDE (не по SSH/TTY)."
    exit 1
fi

NEED_PKG=""
if python3 -c 'import gi; gi.require_version("Gio", "2.0")' 2>/dev/null; then
    ok "Python и python-gobject установлены"
else
    warn "Не хватает python-gobject — установщик предложит поставить"
    NEED_PKG=python-gobject
    command -v pacman >/dev/null || { explain "Установите вручную (python3-gi / python-gobject) и запустите снова"; exit 1; }
fi

if systemctl is-active -q asusd 2>/dev/null; then
    ok "asusd работает — будет карточка режима при Fn+F5"
    HAS_ASUSD=1
else
    warn "asusd не запущен — карточки режима не будет (только подсветка)"
    explain "Установите asusctl и включите: sudo systemctl enable --now asusd"
    HAS_ASUSD=0
fi

KBD=$(ls -d /sys/class/leds/*::kbd_backlight 2>/dev/null | head -1)
if [ -n "$KBD" ]; then
    ok "Подсветка клавиатуры: $(basename "$KBD") (уровни 0–$(cat "$KBD/max_brightness"))"
else
    warn "Подсветка клавиатуры не найдена — будет только карточка режима"
fi

if [ $HAS_ASUSD = 0 ] && [ -z "$KBD" ]; then
    fail "Нет ни asusd, ни подсветки клавиатуры — asus-osd здесь нечего показывать"; exit 1
fi

if systemctl is-active -q power-profiles-daemon 2>/dev/null; then
    warn "Работает power-profiles-daemon — KDE может сам показывать карточку режима"
    explain "Если после установки карточка будет появляться дважды — напишите, это настраивается."
fi

if systemctl --user is-enabled -q asus-osd 2>/dev/null; then
    info "asus-osd уже установлен — будет обновлён"
fi

# ---------- 2. план ----------
title "2. Что будет сделано"
[ -n "$NEED_PKG" ] && info "пакет $NEED_PKG (понадобится пароль sudo)"
info "помощник ${B}asus-osd${R} → ~/.local/bin/"
info "служба, которая запускает его при входе в систему → ~/.config/systemd/user/"
explain "Работает от вашего пользователя, пароль не нужен. Нагрузка — практически нулевая."
echo
if ! ask "Устанавливаем?"; then
    echo; info "Установка отменена, ничего не изменено."; exit 0
fi

# ---------- 3. установка ----------
title "3. Установка"
if [ -n "$NEED_PKG" ]; then
    echo "  Нужен пароль sudo для установки $NEED_PKG."
    step "Пакет $NEED_PKG" sudo pacman -S --needed --noconfirm "$NEED_PKG" || exit 1
fi
step "Помощник asus-osd"          install -Dm 755 "$SRC/bin/asus-osd" "$BIN"
step "Служба автозапуска"         install -Dm 644 "$SRC/systemd/asus-osd.service" "$UNIT"
step "Обновление списка служб"    systemctl --user daemon-reload
step "Включение и запуск службы"  systemctl --user enable --now asus-osd
systemctl --user restart asus-osd >> "$LOG" 2>&1   # при обновлении — подхватить новую версию

# ---------- 4. проверка ----------
title "4. Проверка"
sleep 1
if systemctl --user is-active -q asus-osd; then
    ok "Служба asus-osd работает"
else
    fail "Служба asus-osd не запустилась"
    explain "Причина: journalctl --user -u asus-osd -n 20"
    FAILED=1
fi

if [ $FAILED = 0 ]; then
    echo
    echo "  Сейчас на экране появится тестовая карточка…"
    sleep 1
    osd showText s s "input-keyboard" "asus-osd установлен"
fi

# ---------- итог ----------
title "Итог"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo
if [ $FAILED = 0 ]; then
    echo "  ${GREEN}${B}Готово!${R} Перезаходить в систему не нужно — всё уже работает."
    echo
    echo "  ${B}Попробуйте:${R}"
    [ $HAS_ASUSD = 1 ] && explain "Fn+F5 — карточка режима (Тихий / Сбалансированный / Производительность)"
    [ -n "$KBD" ]      && explain "клавиши подсветки клавиатуры — карточка с уровнем подсветки"
else
    echo "  ${RED}${B}Установка завершена с ошибками.${R} Журнал: $LOG"
    echo "  Раздел «Если что-то не работает» в README.md поможет разобраться."
fi
echo
echo "  Удаление: ${B}./uninstall.sh${R}    Журнал установки: $LOG"
echo
exit $FAILED
