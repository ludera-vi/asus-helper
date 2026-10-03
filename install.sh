#!/bin/bash
# Asus-helper installer (Arch and derivatives, KDE Plasma 6) / установщик.
# Installs on a system without asusctl, power-profiles-daemon, supergfxctl, envycontrol — otherwise tells
# what to remove. Run as a regular user: ./install.sh (sudo asks itself). Remove: ./uninstall.sh
#         ./install.sh --update   update an existing install: no questions, no snapshot, restarts everything

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

# L "по-русски" "in English" — текст на выбранном языке
L() { if [ "$UILANG" = ru ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }

title()   { echo; echo "${B}${BLUE}━━ $* ━━${R}"; }
ok()      { echo "  $OK $*"; }
warn()    { echo "  $WARN $*"; }
fail()    { echo "  $FAIL $*"; }
info()    { echo "  $INFO $*"; }
explain() { echo "    ${D}$*${R}"; }

ask() {
    local def=${2:-Y} hint ans
    if [ "$UILANG" = ru ]; then [ "$def" = Y ] && hint="[Д/н]" || hint="[д/Н]"
    else [ "$def" = Y ] && hint="[Y/n]" || hint="[y/N]"; fi
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
        fail "$desc ${D}($(L "подробности" "details"): $LOG)${R}"; RESULTS+=("$FAIL $desc"); FAILED=1
        return 1
    fi
}

UPDATE=0
[ "${1:-}" = --update ] && UPDATE=1

# ---------- язык / language ----------
UILANG=$(grep -o '"language": *"[a-z]*"' /etc/asus-helper/config.json 2>/dev/null | grep -o '[a-z]*"$' | tr -d '"')
if [ -z "$UILANG" ] || [ $UPDATE = 0 ]; then
    case "${LANG:-}" in ru*) def=2 ;; *) def=1 ;; esac
    echo
    echo "  ${B}Language / Язык${R}"
    echo "    1) English"
    echo "    2) Русский"
    read -rp "  > [$def] " choice
    case "${choice:-$def}" in 2|ru|RU|р|Р) UILANG=ru ;; *) UILANG=en ;; esac
fi

if [ $UPDATE = 1 ] && [ ! -e /usr/local/lib/systemd/system/asus-helperd.service ] && [ ! -e /etc/systemd/system/asus-helperd.service ]; then
    L "Asus-helper ещё не установлен — запустите ./install.sh без --update" "Asus-helper is not installed yet — run ./install.sh without --update"; echo
    exit 1
fi

mkdir -p "$(dirname "$LOG")"
echo "=== asus-helper install $(date) ===" > "$LOG"

clear 2>/dev/null
if [ "$UILANG" = ru ]; then cat <<EOF
${B}
   ┌──────────────────────────────────────────────┐
   │   Asus-helper · ноутбук ASUS ROG в Linux      │
   │   режимы, вентиляторы, видеокарта,            │
   │   подсветка, Slash, батарея — как G-Helper    │
   └──────────────────────────────────────────────┘${R}
EOF
else cat <<EOF
${B}
   ┌──────────────────────────────────────────────┐
   │   Asus-helper · ASUS ROG laptop on Linux      │
   │   profiles, fans, GPU, lighting, Slash,       │
   │   battery — like G-Helper                     │
   └──────────────────────────────────────────────┘${R}
EOF
fi

[ $EUID -ne 0 ] || { fail "$(L "Запускай от обычного пользователя: ./install.sh (sudo спросится сам)" "Run as a regular user: ./install.sh (sudo will ask by itself)")"; exit 1; }

# ---------- 1. проверка ----------
title "$(L "Проверка системы" "Checking the system")"
problems=0
vendor=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null)
model=$(cat /sys/class/dmi/id/product_name 2>/dev/null)
if [[ "$vendor" == ASUS* ]]; then ok "$(L "Ноутбук" "Laptop"): $model"; else fail "$(L "Это не ASUS" "Not an ASUS") ($vendor)"; problems=1; fi
if [ -e /sys/firmware/acpi/platform_profile ]; then ok "$(L "Режимы производительности (platform_profile)" "Performance profiles (platform_profile)")"
else fail "$(L "Нет" "Missing") /sys/firmware/acpi/platform_profile"; problems=1; fi
if [ -d /sys/class/firmware-attributes/asus-armoury ]; then ok "$(L "Ядро с asus-armoury" "Kernel with asus-armoury")"
else warn "$(L "Нет asus-armoury — лимиты мощности будут недоступны" "No asus-armoury — power limits will be unavailable")"; fi

missing=()
python3 -c 'import gi' 2>/dev/null || missing+=(python-gobject)
python3 -c 'import PySide6' 2>/dev/null || missing+=(pyside6)
command -v make >/dev/null || missing+=(make)
command -v kscreen-doctor >/dev/null || missing+=(libkscreen)
if [ ${#missing[@]} -eq 0 ]; then ok "$(L "Пакеты" "Packages"): python-gobject, pyside6, kscreen-doctor"
else warn "$(L "Не хватает пакетов" "Missing packages"): ${missing[*]} — $(L "поставлю" "will install")"; fi
[ $problems -eq 0 ] || { fail "$(L "Установка невозможна" "Installation is not possible")"; exit 1; }

# Ставим только на чистую систему: эти программы делают то же самое и будут спорить с демоном
conflicts=()
for p in asusctl rog-control-center power-profiles-daemon supergfxctl envycontrol optimus-manager; do
    pacman -Q "$p" >/dev/null 2>&1 && conflicts+=("$p")
done
old=()
[ -e /usr/local/bin/gpu-eco ] && old+=("gpu-switch (gpu-eco)")
[ -e "$HOME/.local/bin/asus-osd" ] && old+=("lighting_keyboard (asus-osd)")
if [ ${#conflicts[@]} -gt 0 ] || [ ${#old[@]} -gt 0 ]; then
    fail "$(L "Мешают другие программы управления ноутбуком:" "Other laptop control programs are in the way:")"
    [ ${#conflicts[@]} -gt 0 ] && explain "$(L "пакеты" "packages"): ${conflicts[*]}  →  sudo pacman -Rns ${conflicts[*]}"
    [ ${#old[@]} -gt 0 ] && explain "$(L "старые помощники" "old helpers"): ${old[*]}  →  $(L "их" "their") ./uninstall.sh"
    explain "$(L "Удалите их и запустите установку снова." "Remove them and run the installer again.")"
    exit 1
fi
ok "$(L "Конфликтующих программ нет" "No conflicting programs")"

dev_daemon=$(pgrep -f '^python3 -m asushelper.daemon' || true)

if [ $UPDATE = 0 ]; then
# ---------- 2. план ----------
title "$(L "Что будет сделано" "What will be done")"
info "$(L "Демон ${B}asus-helperd${R} — системная служба, стартует при загрузке" "Daemon ${B}asus-helperd${R} — a system service started at boot")"
explain "/usr/local/lib/asus-helper, /usr/local/bin/asus-helper{d,-cli,}, prime-run, D-Bus, polkit"
info "$(L "Значок ${B}Asus-helper${R} в трее при входе в систему, клавиша ROG открывает окно" "${B}Asus-helper${R} tray icon at login, the ROG key opens the window")"
info "$(L "Настройки: /etc/asus-helper (если их нет — переносятся из /etc/asusd)" "Settings: /etc/asus-helper (imported from /etc/asusd if present)")"
[ -n "$dev_daemon" ] && info "$(L "Пробный демон из dev-run.sh (сейчас запущен) будет остановлен" "The dev-run.sh daemon (running now) will be stopped")"
info "$(L "Рабочий стол KDE — на встроенной видеокарте (если есть NVIDIA): так Eco включается без выхода из сеанса" "KDE desktop runs on the integrated GPU (if NVIDIA is present): then Eco works without logging out")"
explain "$(L "Это решает демон при загрузке; без NVIDIA или в режиме MUX «только NVIDIA» ничего не меняется" "The daemon decides this at boot; without NVIDIA or with MUX in \"NVIDIA only\" nothing changes")"
echo
ask "$(L "Продолжить?" "Continue?")" || { info "$(L "Ничего не изменено" "Nothing changed")"; exit 0; }

# ---------- 3. снимок ----------
if command -v snapper >/dev/null && snapper list-configs 2>/dev/null | grep -q '^root'; then
    title "$(L "Снимок системы" "System snapshot")"
    if ask "$(L "Сделать снимок snapper перед установкой?" "Create a snapper snapshot before installing?")"; then
        sudo -v || exit 1
        n=$(sudo snapper -c root create --print-number --cleanup-algorithm number --description "before Asus-helper install" 2>>"$LOG")
        if [ -n "$n" ]; then ok "$(L "Снимок" "Snapshot") #$n — $(L "откат: загрузиться в него из меню загрузчика" "rollback: boot into it from the boot menu")"; RESULTS+=("$OK $(L "Снимок" "Snapshot") #$n")
        else warn "$(L "Снимок не создан" "Snapshot not created") ($LOG)"; fi
    fi
fi

fi   # конец: только при обычной установке

# ---------- 4. установка ----------
title "$(L "Установка" "Installing")"
sudo -v || exit 1
[ ${#missing[@]} -eq 0 ] || step "$(L "Пакеты" "Packages") ${missing[*]}" sudo pacman -S --needed --noconfirm "${missing[@]}"

if [ -n "$dev_daemon" ]; then
    # пробный демон из dev-run.sh — заменяется службой
    step "$(L "Остановка пробного демона" "Stopping the dev daemon")" sudo kill $dev_daemon
    sleep 3
fi
systemctl --user stop asus-helper-dev.service 2>/dev/null

# Остатки прежних версий установщика (ставили в другие места) — убираем, чтобы не было двойников
cleanup_old() {
    if [ -e /etc/systemd/system/asus-helperd.service ]; then
        sudo systemctl disable asus-helperd.service 2>/dev/null   # снять ссылку автозапуска на старый файл
    fi
    sudo rm -f /etc/systemd/system/asus-helperd.service /etc/udev/rules.d/61-igpu-symlink.rules \
               /etc/dbus-1/system.d/org.{asushero,asusludera}.Daemon.conf \
               /usr/share/polkit-1/actions/org.{asushero,asusludera}.policy
    rm -f "$HOME/.config/systemd/user/plasma-kwin_wayland.service.d/asus-helper-igpu.conf" \
          "$HOME/.config/environment.d/90-kwin-igpu.conf" "$HOME/.config/environment.d/91-igpu-apps.conf" \
          "$HOME/.config/autostart/asus-helper.desktop" \
          "$HOME/.local/share/icons/hicolor/scalable/apps/asus-helper.svg"
    rmdir "$HOME/.config/systemd/user/plasma-kwin_wayland.service.d" 2>/dev/null
    # Ярлык прежней версии лежал в ~/.local/share/applications, и горячие клавиши KDE (клавиша ROG)
    # помнят этот путь до следующего входа — оставляем там ссылку на новый ярлык
    local old_desktop="$HOME/.local/share/applications/asus-helper.desktop"
    if [ -e "$old_desktop" ] || [ -L "$old_desktop" ]; then
        ln -sf /usr/local/share/applications/asus-helper.desktop "$old_desktop"
    fi
    true
}
step "$(L "Остатки прежних версий убраны" "Leftovers of older versions removed")" cleanup_old

install_files() {
    sudo rm -rf "$LIB" &&
    sudo make -C "$SRC" install "${MAKE_ARGS[@]}" &&
    sudo install -d -m 755 /etc/asus-helper /var/lib/asus-helper
}
step "$(L "Программа, служба, права, ярлык, автозапуск" "Program, service, permissions, launcher, autostart")" install_files

reload_system() {
    sudo busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig &&
    sudo udevadm control --reload &&
    sudo udevadm trigger --subsystem-match=drm --action=add && sudo udevadm settle &&
    sudo systemctl daemon-reload &&
    systemctl --user daemon-reload &&
    { command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1 || true; }
}
step "$(L "Перечитаны systemd, D-Bus, udev, меню KDE" "Reloaded systemd, D-Bus, udev, KDE menu")" reload_system

if [ ! -e /etc/asus-helper/config.json ] && [ -d /etc/asusd ]; then
    step "$(L "Перенос настроек из /etc/asusd" "Imported settings from /etc/asusd")" sudo env PYTHONPATH="$LIB" python3 -m asushelper.cli import-asusd
fi
step "$(L "Язык: русский" "Language: English")" sudo env PYTHONPATH="$LIB" python3 -m asushelper.cli language "$UILANG" --local

step "$(L "Демон asus-helperd включён" "asus-helperd daemon enabled")" sudo systemctl enable asus-helperd.service
step "$(L "Демон запущен с новой версией" "Daemon started with the new version")" sudo systemctl restart asus-helperd.service

# KWin читает /run/asus-helper/kwin.env только при входе в сеанс. Если сейчас он держит NVIDIA,
# Eco заработает после одного выхода из сеанса
sleep 2
need_relogin=0
if grep -q KWIN_DRM_DEVICES /run/asus-helper/kwin.env 2>/dev/null &&
   "$BIN/asus-helper-cli" gpu 2>/dev/null | grep -q kwin_wayland; then
    need_relogin=1
fi

title "$(L "Значок и окно" "Tray icon and window")"
pkill -f '^/usr/bin/python3 -m asushelper.app' 2>/dev/null
pkill -f '^python3 -m asushelper.app' 2>/dev/null
pkill -f '^python3 -m asushelper.agent' 2>/dev/null
sleep 1
( setsid "$BIN/asus-helper" >/dev/null 2>&1 & )
ok "$(L "Asus-helper запущен — значок в трее" "Asus-helper started — icon in the tray")"

# ---------- 8. проверка ----------
title "$(L "Проверка" "Verification")"
sleep 2
if systemctl is-active -q asus-helperd; then ok "$(L "asus-helperd работает" "asus-helperd is running")"
else fail "$(L "asus-helperd не запустился" "asus-helperd failed to start"): journalctl -u asus-helperd"; FAILED=1; fi
if "$BIN/asus-helper-cli" >>"$LOG" 2>&1; then ok "$(L "Демон отвечает" "Daemon responds")"
else fail "$(L "Демон не отвечает" "Daemon does not respond") ($LOG)"; FAILED=1; fi

title "$(L "Итог" "Summary")"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo
if [ $FAILED -eq 0 ]; then
    echo "  ${GREEN}${B}$(L "Готово." "Done.")${R} $(L "Значок Asus-helper — в трее; клавиша ROG открывает окно." "The Asus-helper icon is in the tray; the ROG key opens the window.")"
    [ $need_relogin = 1 ] && echo "  ${YELLOW}$(L "Один раз выйди из сеанса и войди снова" "Log out and back in once")${R} — $(L "тогда Eco будет включаться без выхода." "then Eco will work without logging out.")"
else
    echo "  ${YELLOW}${B}$(L "Установлено с ошибками." "Installed with errors.")${R} $(L "Журнал" "Log"): $LOG"
fi
cat <<EOF

  ${D}$(L "Терминал" "Terminal"):  asus-helper-cli          ($(L "состояние и команды" "status and commands"))
  $(L "Журнал" "Log"):    journalctl -u asus-helperd -f
  $(L "Удаление" "Remove"):  ./uninstall.sh${R}

EOF
