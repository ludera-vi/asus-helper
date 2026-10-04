#!/bin/bash
# Asus-helper installer (Arch and derivatives; KDE Plasma 6, GNOME and others) / установщик.
# First finds out the desktop and the laptop, then talks only about them. Missing packages — offers to install,
# asusctl, power-profiles-daemon, supergfxctl, envycontrol — offers to remove.
# Run as a regular user: ./install.sh (sudo asks itself). Remove: ./uninstall.sh
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
installed_now=""
# Что установщик поставил и удалил в системе — uninstall.sh предложит вернуть как было
CHANGES="${XDG_STATE_HOME:-$HOME/.local/state}/asus-helper-install-changes"
remember() {   # remember installed|removed пакеты…
    local key=$1; shift
    mkdir -p "$(dirname "$CHANGES")"
    local old; old=$(grep "^$key=" "$CHANGES" 2>/dev/null | cut -d= -f2-)
    local all; all=$(printf '%s\n' $old "$@" | sort -u | tr '\n' ' ')
    { grep -v "^$key=" "$CHANGES" 2>/dev/null; echo "$key=${all% }"; } > "$CHANGES.new" && mv "$CHANGES.new" "$CHANGES"
}

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
# сообщения sudo, pacman, systemctl — на выбранном языке
if [ "$UILANG" = ru ] && locale -a 2>/dev/null | grep -qi '^ru_RU.utf-\?8$'; then
    export LC_MESSAGES=ru_RU.UTF-8 LANGUAGE=ru
elif [ "$UILANG" = en ]; then
    export LC_MESSAGES=C.UTF-8; unset LANGUAGE
fi

# ---------- рабочий стол ----------
# Всё дальше — только про него: KDE, GNOME или другой (niri, Hyprland, Sway, COSMIC…)
desk_raw="${XDG_CURRENT_DESKTOP:-${XDG_SESSION_DESKTOP:-${DESKTOP_SESSION:-}}}"
case "${desk_raw^^}" in
    *KDE*|*PLASMA*) DESK=kde;   DESK_NAME="KDE Plasma" ;;
    *GNOME*)        DESK=gnome; DESK_NAME="GNOME $(gnome-shell --version 2>/dev/null | grep -o '[0-9][0-9.]*' | head -1)" ;;
    "")             DESK=none;  DESK_NAME="" ;;
    *HYPRLAND*)     DESK=other; DESK_NAME=Hyprland ;;
    *NIRI*)         DESK=other; DESK_NAME=niri ;;
    *SWAY*)         DESK=other; DESK_NAME=Sway ;;
    *COSMIC*)       DESK=other; DESK_NAME=COSMIC ;;
    *)              DESK=other; DESK_NAME="${desk_raw%%:*}" ;;
esac
DESK_NAME="${DESK_NAME% }"
APPINDICATOR=appindicatorsupport@rgcjonas.gmail.com
GNOMEEXT=asus-helper@ludera-vi.github.com     # своё расширение: карточки GNOME и окно под треем

# ---------- оформление окна ----------
# Выбор есть только в KDE: «как в системе» — это цвета и стиль KDE. В других средах окно всегда в своей теме.
APPCFG="${XDG_CONFIG_HOME:-$HOME/.config}/asus-helper/app.json"
UITHEME=$(grep -o '"theme": *"[a-z]*"' "$APPCFG" 2>/dev/null | grep -o '[a-z]*"$' | tr -d '"')
if [ "$DESK" = kde ] && { [ -z "$UITHEME" ] || [ $UPDATE = 0 ]; }; then
    echo
    echo "  ${B}$(L "Оформление окна" "Window appearance")${R}"
    echo "    1) $(L "Как в системе — цвета и стиль KDE" "System — KDE colours and style")"
    echo "    2) $(L "Оригинальное — тёмное, в духе G-Helper" "Original — dark, in the spirit of G-Helper")"
    explain "$(L "Сменить можно и потом: кнопка оформления внизу окна." "You can change it later: the appearance button at the bottom of the window.")"
    read -rp "  > [1] " choice
    case "${choice:-1}" in 2) UITHEME=original ;; *) UITHEME=system ;; esac
fi

if [ $UPDATE = 1 ] && [ ! -e /usr/local/lib/systemd/system/asus-helperd.service ] && [ ! -e /etc/systemd/system/asus-helperd.service ]; then
    L "Asus-helper ещё не установлен — запустите ./install.sh без --update" "Asus-helper is not installed yet — run ./install.sh without --update"; echo
    exit 1
fi

mkdir -p "$(dirname "$LOG")"
echo "=== asus-helper install $(date) lang=$UILANG ===" > "$LOG"

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
case $DESK in
    kde)   ok "KDE Plasma${XDG_SESSION_TYPE:+ ($XDG_SESSION_TYPE)}" ;;
    gnome) ok "$DESK_NAME${XDG_SESSION_TYPE:+ ($XDG_SESSION_TYPE)}" ;;
    other) ok "$(L "Рабочий стол" "Desktop"): $DESK_NAME${XDG_SESSION_TYPE:+ ($XDG_SESSION_TYPE)}"
           explain "$(L "Значок появится, если в панели есть трей (StatusNotifierItem — например, waybar с модулем tray)" "The icon appears if your bar has a tray (StatusNotifierItem — e.g. waybar with the tray module)")" ;;
    none)  warn "$(L "Рабочий стол не определён (установка не из графического сеанса?) — демон и asus-helper-cli работают везде" "Desktop not detected (not installing from a graphical session?) — the daemon and asus-helper-cli work anywhere")" ;;
esac
if [ -d /sys/class/firmware-attributes/asus-armoury ]; then ok "$(L "Ядро с asus-armoury" "Kernel with asus-armoury")"
else warn "$(L "Нет asus-armoury — лимиты мощности будут недоступны" "No asus-armoury — power limits will be unavailable")"; fi

[ $problems -eq 0 ] || { fail "$(L "Установка невозможна" "Installation is not possible")"; exit 1; }

# Пакеты: общие для окна (Kirigami, layer-shell — их подключает окно в любой среде; названия видеокарт —
# база pci.ids) и свои для рабочего стола
need=(python-gobject pyside6 make kirigami layer-shell-qt hwdata)
case $DESK in
    kde)   need+=(libkscreen qqc2-desktop-style) ;;         # частота экрана, стиль KDE для окна
    gnome) need+=(breeze-icons gnome-shell-extension-appindicator) ;;   # значки окна, трей в панели
    *)     need+=(breeze-icons) ;;
esac
missing=()
for p in "${need[@]}"; do pacman -Q "$p" >/dev/null 2>&1 || missing+=("$p"); done
if [ ${#missing[@]} -eq 0 ]; then
    ok "$(L "Пакеты" "Packages"): ${need[*]}"
else
    warn "$(L "Не хватает пакетов" "Missing packages"): ${B}${missing[*]}${R}"
    [ $DESK = gnome ] && [[ " ${missing[*]} " == *" gnome-shell-extension-appindicator "* ]] &&
        explain "$(L "gnome-shell-extension-appindicator — трей в верхней панели GNOME, без него значка не будет" "gnome-shell-extension-appindicator — the tray in the GNOME top bar, without it there is no icon")"
    if ask "$(L "Установить их сейчас?" "Install them now?")"; then
        sudo -v || exit 1
        echo "### pacman -S ${missing[*]}" >> "$LOG"
        if sudo pacman -S --needed --noconfirm "${missing[@]}" >> "$LOG" 2>&1; then
            ok "$(L "Пакеты установлены" "Packages installed"): ${missing[*]}"
            RESULTS+=("$OK $(L "Пакеты" "Packages") ${missing[*]}")
            installed_now=" ${missing[*]} "
            remember installed "${missing[@]}"
        else
            fail "$(L "Пакеты не установились" "Packages failed to install") ${D}($LOG)${R}"; exit 1
        fi
    else
        fail "$(L "Без них Asus-helper не установить" "Asus-helper cannot be installed without them")"; exit 1
    fi
fi

# Ставим только на чистую систему: эти программы делают то же самое и будут спорить с демоном
conflicts=()
for p in asusctl rog-control-center power-profiles-daemon tuned-ppd supergfxctl envycontrol optimus-manager; do
    pacman -Q "$p" >/dev/null 2>&1 && conflicts+=("$p")
done
old=()
[ -e /usr/local/bin/gpu-eco ] && old+=("gpu-switch (gpu-eco)")
[ -e "$HOME/.local/bin/asus-osd" ] && old+=("lighting_keyboard (asus-osd)")
if [ ${#old[@]} -gt 0 ]; then
    fail "$(L "Мешают старые помощники" "Old helpers are in the way"): ${old[*]}"
    explain "$(L "Удалите их (их ./uninstall.sh) и запустите установку снова." "Remove them (their ./uninstall.sh) and run the installer again.")"
    exit 1
fi
if [ ${#conflicts[@]} -gt 0 ]; then
    warn "$(L "Мешают другие программы управления ноутбуком" "Other laptop control programs are in the way"): ${B}${conflicts[*]}${R}"
    explain "$(L "Они делают то же самое и будут спорить с Asus-helper за вентиляторы, режимы и видеокарту." "They do the same job and would fight Asus-helper over fans, profiles and the GPU.")"
    [[ " ${conflicts[*]} " == *" power-profiles-daemon "* || " ${conflicts[*]} " == *" tuned-ppd "* ]] &&
        explain "$(L "Режимы питания в $( [ $DESK = none ] && echo "рабочем столе" || echo "$DESK_NAME") останутся: Asus-helper отвечает за них сам." "Power profiles in $( [ $DESK = none ] && echo "the desktop" || echo "$DESK_NAME") keep working: Asus-helper serves them itself.")"
    if ask "$(L "Удалить их?" "Remove them?")"; then
        sudo -v || exit 1
        echo "### pacman -Rns ${conflicts[*]}" >> "$LOG"
        # по одной: несуществующая служба (например, supergfxd без supergfxctl) не мешает остановить остальные
        for u in asusd supergfxd power-profiles-daemon tuned-ppd; do
            systemctl cat "$u.service" >/dev/null 2>&1 && sudo systemctl disable --now "$u.service" >> "$LOG" 2>&1
        done
        if sudo pacman -Rns --noconfirm "${conflicts[@]}" >> "$LOG" 2>&1; then
            ok "$(L "Удалено" "Removed"): ${conflicts[*]}"
            remember removed "${conflicts[@]}"
            RESULTS+=("$OK $(L "Удалено" "Removed") ${conflicts[*]}")
        else
            fail "$(L "Не удалось удалить" "Could not remove") ${D}($LOG)${R}"
            explain "$(L "Вручную" "By hand"): sudo pacman -Rns ${conflicts[*]}"
            exit 1
        fi
    else
        fail "$(L "Пока они установлены, Asus-helper не поставить" "Asus-helper cannot be installed while they are present")"; exit 1
    fi
else
    ok "$(L "Конфликтующих программ нет" "No conflicting programs")"
fi

dev_daemon=$(pgrep -f '^python3 -m asushelper.daemon' || true)

if [ $UPDATE = 0 ]; then
# ---------- 2. план ----------
title "$(L "Что будет сделано" "What will be done")"
info "$(L "Демон ${B}asus-helperd${R} — системная служба, стартует при загрузке" "Daemon ${B}asus-helperd${R} — a system service started at boot")"
explain "/usr/local/lib/asus-helper, /usr/local/bin/asus-helper{d,-cli,}, prime-run, D-Bus, polkit"
case $DESK in
    gnome) info "$(L "Значок ${B}Asus-helper${R} в верхней панели GNOME при входе (расширение AppIndicator будет включено)" "${B}Asus-helper${R} icon in the GNOME top bar at login (the AppIndicator extension gets enabled)")"
           info "$(L "Расширение GNOME ${B}Asus-helper${R}: карточки при смене режима и подсветки, окно — в правом верхнем углу под треем" "GNOME extension ${B}Asus-helper${R}: pop-ups on profile and lighting changes, the window opens top-right under the tray")"
           explain "$(L "Клавиша ROG открывает окно: «Настройки → Клавиатура → Свои комбинации клавиш»" "The ROG key opens the window: Settings → Keyboard → Custom Shortcuts")" ;;
    none)  info "$(L "Значок ${B}Asus-helper${R} в трее при входе в систему" "${B}Asus-helper${R} tray icon at login")" ;;
    *)     info "$(L "Значок ${B}Asus-helper${R} в трее при входе в систему, клавиша ROG открывает окно" "${B}Asus-helper${R} tray icon at login, the ROG key opens the window")" ;;
esac
info "$(L "Настройки: /etc/asus-helper (если их нет — переносятся из /etc/asusd)" "Settings: /etc/asus-helper (imported from /etc/asusd if present)")"
[ -n "$dev_daemon" ] && info "$(L "Пробный демон из dev-run.sh (сейчас запущен) будет остановлен" "The dev-run.sh daemon (running now) will be stopped")"
case $DESK in
    kde)   info "$(L "Рабочий стол KDE — на встроенной видеокарте (если есть NVIDIA): так Eco включается без выхода из сеанса" "KDE desktop runs on the integrated GPU (if NVIDIA is present): then Eco works without logging out")" ;;
    gnome) info "$(L "GNOME и экран входа GDM — на встроенной видеокарте (если есть NVIDIA): так Eco включается без выхода из сеанса" "GNOME and the GDM login screen run on the integrated GPU (if NVIDIA is present): then Eco works without logging out")" ;;
esac
if [ $DESK = kde ] || [ $DESK = gnome ]; then
    explain "$(L "Это решает демон при загрузке; без NVIDIA или в режиме MUX «только NVIDIA» ничего не меняется" "The daemon decides this at boot; without NVIDIA or with MUX in \"NVIDIA only\" nothing changes")"
    [ $DESK = gnome ] && explain "$(L "Мониторы, подключённые к выходам NVIDIA, в этом случае не работают" "Monitors connected to NVIDIA outputs do not work in this case")"
fi
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
          "$HOME/.local/share/applications/asus-helper.desktop" "$HOME/.config/autostart/asus-helper.desktop" \
          "$HOME/.local/share/icons/hicolor/scalable/apps/asus-helper.svg"
    rmdir "$HOME/.config/systemd/user/plasma-kwin_wayland.service.d" 2>/dev/null
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
if [ $DESK = kde ]; then step "$(L "Перечитаны systemd, D-Bus, udev, меню KDE" "Reloaded systemd, D-Bus, udev, KDE menu")" reload_system
else step "$(L "Перечитаны systemd, D-Bus, udev" "Reloaded systemd, D-Bus, udev")" reload_system; fi

if [ ! -e /etc/asus-helper/config.json ] && [ -d /etc/asusd ]; then
    step "$(L "Перенос настроек из /etc/asusd" "Imported settings from /etc/asusd")" sudo env PYTHONPATH="$LIB" python3 -m asushelper.cli import-asusd
fi
step "$(L "Язык: русский" "Language: English")" sudo env PYTHONPATH="$LIB" python3 -m asushelper.cli language "$UILANG" --local
save_theme() {
    python3 - "$APPCFG" "$UITHEME" <<'PY'
import json, os, sys
path, theme = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
data["theme"] = theme
os.makedirs(os.path.dirname(path), exist_ok=True)
json.dump(data, open(path, "w"), indent=2)
PY
}
[ $DESK = kde ] && step "$(L "Оформление: " "Appearance: ")$( [ "$UITHEME" = original ] && L "оригинальное" "original" || L "как в системе" "system")" save_theme

step "$(L "Демон asus-helperd включён" "asus-helperd daemon enabled")" sudo systemctl enable asus-helperd.service
step "$(L "Демон запущен с новой версией" "Daemon started with the new version")" sudo systemctl restart asus-helperd.service

# KWin читает /run/asus-helper/kwin.env только при входе в сеанс. Если сейчас он держит NVIDIA,
# Eco заработает после одного выхода из сеанса
sleep 2
need_relogin=0
if [ $DESK = kde ] && grep -q KWIN_DRM_DEVICES /run/asus-helper/kwin.env 2>/dev/null &&
   "$BIN/asus-helper-cli" gpu 2>/dev/null | grep -q kwin_wayland; then
    need_relogin=1
fi
# GNOME так же: тег udev и окружение gnome-shell действуют с нового входа
if [ $DESK = gnome ] && [ -e /run/asus-helper/mutter-igpu-only ] &&
   "$BIN/asus-helper-cli" gpu 2>/dev/null | grep -qE 'gnome-shell|Xwayland'; then
    need_relogin=1
fi

# GNOME: трей — расширение AppIndicator, карточки и окно под треем — своё расширение Asus-helper.
# Только что установленные GNOME увидит после нового входа, поэтому включаем их в настройках (подхватятся при
# входе), а если GNOME их уже знает — сразу
tray_after_relogin=0
enable_extensions() {
    gsettings set org.gnome.shell disable-user-extensions false &&
    python3 - "$APPINDICATOR" "$GNOMEEXT" <<'PY'
import sys
from gi.repository import Gio
s = Gio.Settings.new("org.gnome.shell")
for uuid in sys.argv[1:]:
    s.set_strv("disabled-extensions", [e for e in s.get_strv("disabled-extensions") if e != uuid])
    if uuid not in s.get_strv("enabled-extensions"):
        s.set_strv("enabled-extensions", s.get_strv("enabled-extensions") + [uuid])
Gio.Settings.sync()
PY
    gnome-extensions enable "$APPINDICATOR" 2>/dev/null
    gnome-extensions enable "$GNOMEEXT" 2>/dev/null
    true
}
if [ $DESK = gnome ]; then
    step "$(L "Расширения GNOME включены: трей (AppIndicator) и Asus-helper (карточки, окно под треем)" "GNOME extensions enabled: tray (AppIndicator) and Asus-helper (pop-ups, window under the tray)")" enable_extensions
    for e in "$APPINDICATOR" "$GNOMEEXT"; do
        gnome-extensions info "$e" 2>/dev/null | grep -qiE 'state: *(enabled|active)' || tray_after_relogin=1
    done
fi

title "$(L "Значок и окно" "Tray icon and window")"
pkill -f '^/usr/bin/python3 -m asushelper.app' 2>/dev/null
pkill -f '^python3 -m asushelper.app' 2>/dev/null
pkill -f '^python3 -m asushelper.agent' 2>/dev/null
sleep 1
( setsid "$BIN/asus-helper" >/dev/null 2>&1 & )
if [ $DESK = gnome ] && [ $tray_after_relogin = 1 ]; then
    ok "$(L "Asus-helper запущен — значок появится в верхней панели после нового входа (окно — из меню приложений)" "Asus-helper started — the icon appears in the top bar after logging in again (the window opens from the app menu)")"
    need_relogin=1
elif [ $DESK = gnome ]; then ok "$(L "Asus-helper запущен — значок в верхней панели" "Asus-helper started — icon in the top bar")"
else ok "$(L "Asus-helper запущен — значок в трее" "Asus-helper started — icon in the tray")"; fi

# ---------- 8. проверка ----------
title "$(L "Проверка" "Verification")"
sleep 2
if systemctl is-active -q asus-helperd; then ok "$(L "asus-helperd работает" "asus-helperd is running")"
else fail "$(L "asus-helperd не запустился" "asus-helperd failed to start"): journalctl -u asus-helperd"; FAILED=1; fi
if "$BIN/asus-helper-cli" >>"$LOG" 2>&1; then ok "$(L "Демон отвечает" "Daemon responds")"
else fail "$(L "Демон не отвечает" "Daemon does not respond") ($LOG)"; FAILED=1; fi

# Что демон нашёл у этого ноутбука: человек сразу видит, что будет работать, а чего у модели нет
title "$(L "Что нашлось у ноутбука" "What this laptop has")"
"$BIN/asus-helper-cli" diag 2>>"$LOG" | sed 's/^/  /'

title "$(L "Итог" "Summary")"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo
if [ $FAILED -eq 0 ]; then
    case $DESK in
        gnome) echo "  ${GREEN}${B}$(L "Готово." "Done.")${R} $(L "Значок Asus-helper — в верхней панели GNOME; клавиша ROG открывает окно." "The Asus-helper icon is in the GNOME top bar; the ROG key opens the window.")" ;;
        *)     echo "  ${GREEN}${B}$(L "Готово." "Done.")${R} $(L "Значок Asus-helper — в трее; клавиша ROG открывает окно." "The Asus-helper icon is in the tray; the ROG key opens the window.")" ;;
    esac
else
    echo "  ${YELLOW}${B}$(L "Установлено с ошибками." "Installed with errors.")${R} $(L "Журнал" "Log"): $LOG"
fi
cat <<EOF

  ${D}$(L "Терминал" "Terminal"):  asus-helper-cli          ($(L "состояние и команды" "status and commands"))
  $(L "Журнал" "Log"):    journalctl -u asus-helperd -f
  $(L "Удаление" "Remove"):  ./uninstall.sh${R}

EOF

# Рабочий стол запущен до установки и держит NVIDIA: настройка «KDE только на встроенной видеокарте»
# подействует со следующего входа. Без этого Eco не выключит карту — говорим прямо и предлагаем выйти.
if [ $FAILED -eq 0 ] && [ $need_relogin = 1 ] && [ $DESK = gnome ]; then
    echo "  ${YELLOW}${B}$(L "Нужен один выход из сеанса." "One log out is needed.")${R}"
    if [ -e /run/asus-helper/mutter-igpu-only ] && "$BIN/asus-helper-cli" gpu 2>/dev/null | grep -qE 'gnome-shell|Xwayland'; then
        explain "$(L "GNOME запустился до установки и сейчас работает на NVIDIA — выключить её (Eco) нельзя." \
                     "GNOME started before the install and runs on NVIDIA now — it cannot be turned off (Eco).")"
        explain "$(L "После выхода и входа GNOME будет на встроенной видеокарте, и Eco заработает. Это нужно один раз." \
                     "After logging out and back in GNOME uses the integrated GPU and Eco works. Needed once.")"
    fi
    [ $tray_after_relogin = 1 ] &&
        explain "$(L "Расширения GNOME загрузит при новом входе — тогда появятся значок в панели и карточки режима и подсветки." \
                     "GNOME loads the extensions at the next login — then the top-bar icon and the profile/lighting pop-ups appear.")"
    if command -v gnome-session-quit >/dev/null && ask "$(L "Выйти из сеанса сейчас? (сначала сохрани открытые документы)" "Log out now? (save your open documents first)")" Y; then
        gnome-session-quit --logout >/dev/null 2>&1 &
    else
        explain "$(L "Выйди позже сам: меню в правом верхнем углу → Выключение → Выйти." "Log out later yourself: top-right menu → Power Off → Log Out.")"
    fi
    echo
elif [ $FAILED -eq 0 ] && [ $need_relogin = 1 ]; then
    echo "  ${YELLOW}${B}$(L "Нужен один выход из сеанса." "One log out is needed.")${R}"
    explain "$(L "Рабочий стол KDE запустился до установки и сейчас работает на NVIDIA — выключить её (Eco) нельзя." \
                 "The KDE desktop started before the install and runs on NVIDIA now — it cannot be turned off (Eco).")"
    explain "$(L "После выхода и входа рабочий стол будет на встроенной видеокарте, и Eco заработает. Это нужно один раз." \
                 "After logging out and back in the desktop uses the integrated GPU and Eco works. Needed once.")"
    if command -v qdbus6 >/dev/null && ask "$(L "Выйти из сеанса сейчас? (сначала сохрани открытые документы)" "Log out now? (save your open documents first)")" Y; then
        qdbus6 org.kde.LogoutPrompt /LogoutPrompt org.kde.LogoutPrompt.promptLogout >/dev/null 2>&1 ||
            qdbus6 org.kde.Shutdown /Shutdown org.kde.Shutdown.logout >/dev/null 2>&1
    else
        explain "$(L "Выйди позже сам: меню → Выйти." "Log out later yourself: menu → Log Out.")"
    fi
    echo
fi
