#!/bin/bash
# Установщик gpu-switch: Eco-режим NVIDIA для ноутбуков ASUS (Arch и производные).
# Запуск: ./install.sh   (от обычного пользователя, sudo спросит сам)

set -uo pipefail

SRC=$(dirname "$(readlink -f "$0")")
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/gpu-switch-install.log"
ENVD="$HOME/.config/environment.d"
WIDGET_ID=org.vi.gpueco

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

# ask "вопрос" [Y|N] → 0 = да
ask() {
    local def=${2:-Y} hint ans
    [ "$def" = Y ] && hint="[Д/н]" || hint="[д/Н]"
    read -rp "  ${B}?${R} $1 $hint " ans
    ans=${ans:-$def}
    [[ "$ans" =~ ^([YyДд]|yes|да|Да)$ ]]
}

# step "описание" команда… — выполняет, пишет вывод в журнал, запоминает результат
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

skip() { info "$1 — пропущено"; RESULTS+=("${D}– $1 (пропущено)${R}"); }

# ---------- начало ----------
mkdir -p "$(dirname "$LOG")"
echo "=== gpu-switch install $(date) ===" > "$LOG"

clear 2>/dev/null
cat <<EOF
${B}
   ┌──────────────────────────────────────────────┐
   │   gpu-switch · Eco-режим NVIDIA для ASUS      │
   │   выключение видеокарты через BIOS            │
   │   без перезагрузки — как в G-Helper           │
   └──────────────────────────────────────────────┘${R}

  Установщик проверит систему, расскажет, что собирается сделать,
  и только после вашего согласия что-то изменит.
EOF

if [ $EUID -eq 0 ]; then
    echo; fail "Запустите установщик от обычного пользователя, не через sudo:"
    explain "./install.sh"
    exit 1
fi

# ---------- 1. проверка системы ----------
title "1. Проверка системы"

if command -v pacman >/dev/null; then
    ok "Arch-подобная система ($(. /etc/os-release; echo "${PRETTY_NAME:-Linux}"))"
    HAS_PACMAN=1
else
    warn "Не Arch-подобная система — недостающие пакеты придётся поставить вручную"
    HAS_PACMAN=0
fi

DGPU_ATTR=""
for a in /sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value \
         /sys/devices/platform/asus-nb-wmi/dgpu_disable; do
    [ -e "$a" ] && { DGPU_ATTR=$a; break; }
done
if [ -n "$DGPU_ATTR" ]; then
    ok "Ноутбук ASUS с отключением dGPU через BIOS"
else
    fail "Не найдено управление dGPU через BIOS (dgpu_disable)"
    explain "Нужен ноутбук ASUS (ROG/TUF/Zenbook с NVIDIA) и ядро с модулем asus-wmi/asus-armoury."
    explain "Проверьте: ls /sys/class/firmware-attributes/  и  lsmod | grep asus"
    exit 1
fi

MUX_ATTR=""
for a in /sys/class/firmware-attributes/asus-armoury/attributes/gpu_mux_mode/current_value \
         /sys/devices/platform/asus-nb-wmi/gpu_mux_mode; do
    [ -e "$a" ] && { MUX_ATTR=$a; break; }
done
if [ -n "$MUX_ATTR" ] && [ "$(cat "$MUX_ATTR")" = 0 ]; then
    fail "MUX в режиме «только NVIDIA» (Ultimate) — в нём выключить NVIDIA нельзя"
    explain "Переключите MUX в гибрид (Optimus) в Armoury Crate / G-Helper / rog-control-center"
    explain "и перезагрузитесь, затем запустите установщик снова."
    exit 1
elif [ -n "$MUX_ATTR" ]; then
    ok "MUX в гибридном режиме"
else
    ok "MUX нет (обычный Optimus)"
fi

NV_PRESENT=0
for d in /sys/bus/pci/devices/*; do
    [ "$(cat "$d/vendor")" = 0x10de ] && [[ "$(cat "$d/class")" == 0x03* ]] && NV_PRESENT=1
done
if [ $NV_PRESENT = 1 ]; then
    ok "Видеокарта NVIDIA найдена"
elif [ "$(cat "$DGPU_ATTR")" = 1 ]; then
    ok "Видеокарта NVIDIA сейчас выключена в BIOS (Eco)"
else
    fail "Видеокарта NVIDIA не найдена"; exit 1
fi

if modinfo nvidia >/dev/null 2>&1; then
    ok "Драйвер NVIDIA установлен"
else
    warn "Драйвер NVIDIA не найден — включение карты будет работать, но без драйвера она бесполезна"
    explain "Установите nvidia-open (или nvidia-open-dkms), затем перезагрузитесь"
fi

# Встроенная видеокарта (Intel/AMD) — для KWin
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
    *)      IGPU_NAME="";      ICD_GLOB="" ;;
esac
if [ -n "$IGPU_PCI" ]; then
    ok "Встроенная видеокарта: $IGPU_NAME ($IGPU_PCI)"
else
    warn "Встроенная видеокарта не найдена — настройки рабочего стола будут пропущены"
fi

CONFLICT=0
IS_KDE=0; IS_WAYLAND=0
[[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]] && command -v kpackagetool6 >/dev/null && IS_KDE=1
[ "${XDG_SESSION_TYPE:-}" = wayland ] && IS_WAYLAND=1
if [ $IS_KDE = 1 ]; then
    ok "KDE Plasma 6$([ $IS_WAYLAND = 1 ] && echo ", Wayland") — будет значок на панели"
else
    warn "Не KDE Plasma 6 — значка на панели не будет (команды и ярлык в меню будут)"
fi

if systemctl is-active -q supergfxd 2>/dev/null; then
    warn "Работает supergfxd — он конфликтует с gpu-switch"
    explain "Отключите его: sudo systemctl disable --now supergfxd"
    CONFLICT=1
fi
if command -v envycontrol >/dev/null; then
    mode=$(envycontrol --query 2>/dev/null)
    if [ "$mode" != hybrid ]; then
        warn "envycontrol в режиме «$mode» — верните гибрид: sudo envycontrol -s hybrid, и перезагрузитесь"
        CONFLICT=1
    else
        info "envycontrol установлен (режим hybrid) — не мешает, но больше не нужен"
    fi
fi

if [ $CONFLICT = 1 ] && ! ask "Есть конфликты (см. выше). Всё равно продолжить?" N; then
    echo; info "Установка отменена, ничего не изменено."; exit 0
fi

MISSING_PKGS=()
command -v notify-send >/dev/null || MISSING_PKGS+=(libnotify)
command -v flock       >/dev/null || MISSING_PKGS+=(util-linux)
command -v sudo        >/dev/null || { fail "Нет sudo"; exit 1; }

# ---------- 2. что будет сделано ----------
title "2. Что будет установлено"

DO_KWIN=0; DO_APPS=0; DO_SNAP=0
echo "  Обязательно:"
info "команда ${B}gpu-eco${R} (/usr/local/bin) — выключение/включение NVIDIA"
info "разрешение запускать gpu-eco без пароля (только её)"
info "быстрый выход из сна в режиме Eco (сервис gpu-eco-fixup)"
info "ярлык «NVIDIA Eco» в меню приложений"
[ $IS_KDE = 1 ] && info "значок «GPU» на панели KDE"
[ ${#MISSING_PKGS[@]} -gt 0 ] && info "пакеты: ${MISSING_PKGS[*]}"
echo
echo "  По желанию:"

if command -v snapper >/dev/null && snapper list-configs 2>/dev/null | grep -q "^root "; then
    if ask "Сделать снимок системы (snapper) перед установкой?"; then DO_SNAP=1; fi
fi

if [ $IS_KDE = 1 ] && [ $IS_WAYLAND = 1 ] && [ -n "$IGPU_PCI" ]; then
    echo
    echo "  ${B}Вопрос 1. Выключать NVIDIA одной кнопкой, не выходя из системы${R}"
    echo "    Сейчас рабочий стол KDE всё время «держит» NVIDIA, даже если она не нужна."
    echo "    Пока он её держит, выключить карту можно только выйдя из сеанса."
    echo "    Если ответить «да», рабочий стол всегда будет работать на $IGPU_NAME,"
    echo "    и NVIDIA можно выключать и включать в любой момент."
    echo "    ${YELLOW}Минус:${R} внешний монитор через HDMI, скорее всего, работать не будет —"
    echo "    на большинстве ASUS этот разъём подключён к NVIDIA. USB-C обычно работает."
    echo "    Если монитор понадобится, настройку легко временно отключить (см. README)."
    echo "    ${D}Если ответить «нет», выключать NVIDIA придётся после выхода из сеанса.${R}"
    if ask "Рабочий стол всегда на $IGPU_NAME? (рекомендуется, если не нужен HDMI)"; then DO_KWIN=1; fi
fi

if [ -n "$IGPU_PCI" ]; then
    echo
    echo "  ${B}Вопрос 2. Чтобы программы сами не будили NVIDIA${R}"
    echo "    Браузер, видеоплеер, мессенджеры и другие программы при запуске иногда"
    echo "    «заглядывают» в NVIDIA и будят её — а это лишний расход батареи."
    echo "    Если ответить «да», все программы будут работать на $IGPU_NAME, а на NVIDIA"
    echo "    — только те, что ты сам запустишь через команду ${B}prime-run${R}"
    echo "    (например: prime-run steam). Это так же, как сделано в Windows:"
    echo "    видеокарта включается только для игр и тяжёлых программ."
    echo "    ${YELLOW}Важно:${R} игры и программы для видео/3D (Steam, DaVinci Resolve, Blender)"
    echo "    тогда нужно запускать через prime-run, иначе они пойдут на $IGPU_NAME и будут медленнее."
    echo "    ${D}Если ответить «нет», программы сами решают, какую видеокарту использовать.${R}"
    if ask "Программы по умолчанию на $IGPU_NAME, NVIDIA только через prime-run? (рекомендуется)"; then DO_APPS=1; fi
fi

echo
if ! ask "Всё верно, начинаем установку?"; then
    echo; info "Установка отменена, ничего не изменено."; exit 0
fi

# ---------- 3. установка ----------
title "3. Установка"
echo "  Сейчас понадобится пароль sudo (для системных файлов)."
if ! sudo -v; then fail "sudo не получен — установка прервана, ничего не изменено"; exit 1; fi
# держим sudo активным до конца установки
( while kill -0 $$ 2>/dev/null; do sudo -n true; sleep 50; done ) 2>/dev/null &
echo

if [ $DO_SNAP = 1 ]; then
    step "Снимок системы snapper" sudo snapper -c root create -t single -d "before gpu-switch install"
fi

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    if [ $HAS_PACMAN = 1 ]; then
        step "Пакеты: ${MISSING_PKGS[*]}" sudo pacman -S --needed --noconfirm "${MISSING_PKGS[@]}"
    else
        warn "Установите вручную: ${MISSING_PKGS[*]}"
    fi
fi

step "Команда gpu-eco" sudo install -m 755 "$SRC/bin/gpu-eco" /usr/local/bin/gpu-eco

install_sudoers() {
    local tmp; tmp=$(mktemp)
    echo "$USER ALL=(root) NOPASSWD: /usr/local/bin/gpu-eco" > "$tmp"
    sudo visudo -cf "$tmp" && sudo install -m 440 -o root -g root "$tmp" /etc/sudoers.d/gpu-eco
    local rc=$?; rm -f "$tmp"; return $rc
}
step "gpu-eco без пароля (sudoers)" install_sudoers

install_fixup() {
    sudo install -m 644 "$SRC/systemd/gpu-eco-fixup.service" /etc/systemd/system/gpu-eco-fixup.service &&
    sudo systemctl daemon-reload &&
    sudo systemctl enable --now gpu-eco-fixup.service
}
step "Быстрый выход из сна в режиме Eco (gpu-eco-fixup.service)" install_fixup

if [ $DO_KWIN = 1 ]; then
    install_kwin() {
        echo "SUBSYSTEM==\"drm\", KERNEL==\"card*\", KERNELS==\"$IGPU_PCI\", SYMLINK+=\"dri/igpu\"" \
            | sudo tee /etc/udev/rules.d/61-igpu-symlink.rules
        sudo udevadm control --reload
        sudo udevadm trigger --subsystem-match=drm --action=add
        sudo udevadm settle
        # без этой ссылки KWin не запустится — проверяем до записи настройки
        [ -e /dev/dri/igpu ] || { echo "/dev/dri/igpu не появился"; return 1; }
        mkdir -p "$ENVD"
        echo "KWIN_DRM_DEVICES=/dev/dri/igpu" > "$ENVD/90-kwin-igpu.conf"
    }
    step "Рабочий стол всегда на $IGPU_NAME (NVIDIA выключается без выхода из сеанса)" install_kwin
else
    skip "Рабочий стол всегда на встроенной видеокарте"
fi

if [ $DO_APPS = 1 ]; then
    install_apps() {
        local icds
        icds=$(ls /usr/share/vulkan/icd.d/$ICD_GLOB 2>/dev/null | paste -sd:)
        mkdir -p "$ENVD" "$HOME/.local/bin"
        {
            echo "__EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/50_mesa.json"
            echo "__GLX_VENDOR_LIBRARY_NAME=mesa"
            [ -n "$icds" ] && echo "VK_DRIVER_FILES=$icds"
        } > "$ENVD/91-igpu-apps.conf"
        install -m 755 "$SRC/bin/prime-run" "$HOME/.local/bin/prime-run"
    }
    step "Программы на $IGPU_NAME, NVIDIA через prime-run" install_apps
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) warn "~/.local/bin нет в PATH — добавьте, иначе prime-run будет системный" ;;
    esac
else
    skip "Программы по умолчанию на встроенной видеокарте"
fi

step "Ярлык «NVIDIA Eco» в меню" install -Dm 644 "$SRC/desktop/gpu-eco.desktop" \
    "$HOME/.local/share/applications/gpu-eco.desktop"

if [ $IS_KDE = 1 ]; then
    install_widget() {
        if kpackagetool6 -t Plasma/Applet -s "$WIDGET_ID" >/dev/null 2>&1; then
            kpackagetool6 -t Plasma/Applet -u "$SRC/widget"
        else
            kpackagetool6 -t Plasma/Applet -i "$SRC/widget"
        fi
    }
    step "Значок «GPU» для панели KDE" install_widget
fi

# ---------- 4. проверка ----------
title "4. Проверка"
state=$(/usr/local/bin/gpu-eco state 2>/dev/null)
case "$state" in
    off)       ok "gpu-eco работает: NVIDIA выключена (Eco)" ;;
    suspended) ok "gpu-eco работает: NVIDIA включена и спит" ;;
    active)    ok "gpu-eco работает: NVIDIA включена и сейчас работает" ;;
    *)         fail "gpu-eco state вернул «$state»"; FAILED=1 ;;
esac
if systemctl is-enabled -q gpu-eco-fixup.service; then
    ok "сервис gpu-eco-fixup включён"
else
    fail "сервис gpu-eco-fixup не включён"; FAILED=1
fi
if sudo -k; sudo -n /usr/local/bin/gpu-eco status >/dev/null 2>&1; then
    ok "gpu-eco запускается без пароля"
else
    fail "gpu-eco просит пароль — проверьте /etc/sudoers.d/gpu-eco"; FAILED=1
fi

# ---------- итог ----------
title "Итог"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo

if [ $FAILED = 0 ]; then
    echo "  ${GREEN}${B}Установка завершена успешно!${R}"
else
    echo "  ${RED}${B}Установка завершена с ошибками.${R} Журнал: $LOG"
    echo "  Раздел «Если что-то пошло не так» в README.md поможет разобраться."
fi

echo
echo "  ${B}Что дальше:${R}"
n=1
if [ $DO_KWIN = 1 ] || [ $DO_APPS = 1 ]; then
    echo "  $n. ${B}Выйдите из сеанса и войдите снова${R} — чтобы применились настройки рабочего стола."; n=$((n+1))
    explain "Если после входа чёрный экран: Ctrl+Alt+F3 → войти → ./uninstall.sh (или см. README)"
fi
if [ $IS_KDE = 1 ]; then
    echo "  $n. Добавьте значок: правый клик по панели → «Добавить или изменить виджеты» → «NVIDIA Eco»."; n=$((n+1))
    explain "Если его нет в списке: systemctl --user restart plasma-plasmashell"
fi
echo "  $n. Пользуйтесь:"
explain "gpu-eco off   — выключить NVIDIA      gpu-eco on — включить"
explain "gpu-eco status — состояние            prime-run программа — запуск на NVIDIA"
echo
echo "  Удаление: ${B}./uninstall.sh${R}    Журнал установки: $LOG"
echo
exit $FAILED
