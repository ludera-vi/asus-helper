#!/bin/bash
# Remove Asus-helper / удаление: daemon, tray icon, launchers, desktop GPU setting, prime-run, settings.
# Before removing, the laptop gets its factory behaviour back (discrete GPU on, factory power limits and fan
# curves); at the end a reboot is offered. / Перед удалением ноутбук возвращается к заводскому поведению.
#   ./uninstall.sh                remove everything / удалить всё
#   ./uninstall.sh --keep-config  keep settings in /etc/asus-helper / оставить настройки

set -uo pipefail
B=$'\e[1m'; R=$'\e[0m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'
ok()   { echo "  ${GREEN}✔${R} $*"; }
warn() { echo "  ${YELLOW}!${R} $*"; }

KEEP_CONFIG=0
[ "${1:-}" = --keep-config ] && KEEP_CONFIG=1

# язык — выбранный при установке (или позже в окне): из настроек, иначе из журнала установки
LOG="${XDG_CACHE_HOME:-$HOME/.cache}/asus-helper-install.log"
UILANG=$(grep -o '"language": *"[a-z]*"' /etc/asus-helper/config.json 2>/dev/null | grep -o '[a-z]*"$' | tr -d '"')
[ -n "$UILANG" ] || UILANG=$(head -1 "$LOG" 2>/dev/null | grep -o 'lang=[a-z]*' | cut -d= -f2)
[ -n "$UILANG" ] || case "${LANG:-}" in ru*) UILANG=ru ;; *) UILANG=en ;; esac
L() { if [ "$UILANG" = ru ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }
# и сообщения sudo, systemctl и прочих — на том же языке
if [ "$UILANG" = ru ] && locale -a 2>/dev/null | grep -qi '^ru_RU.utf-\?8$'; then
    export LC_MESSAGES=ru_RU.UTF-8 LANGUAGE=ru
elif [ "$UILANG" = en ]; then
    export LC_MESSAGES=C.UTF-8; unset LANGUAGE
fi
yes_default() { [[ ! "$1" =~ ^[НнNn] ]]; }

[ $EUID -ne 0 ] || { L "Запускай от обычного пользователя: ./uninstall.sh" "Run as a regular user: ./uninstall.sh"; echo; exit 1; }
read -rp "$(L "Удалить Asus-helper? [д/Н] " "Remove Asus-helper? [y/N] ")" a
[[ "$a" =~ ^([YyДд]|yes|да)$ ]] || exit 0
sudo -v || exit 1

CLI=/usr/local/bin/asus-helper-cli
DGPU=$(ls /sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value \
          /sys/devices/platform/asus-nb-wmi/dgpu_disable 2>/dev/null | head -1)

# ---------- 1. вернуть заводское поведение, пока демон ещё работает ----------
if systemctl is-active -q asus-helperd.service && [ -x "$CLI" ]; then
    # дискретная видеокарта не должна остаться выключенной в BIOS без программы, которая умеет её включить
    if [ -n "$DGPU" ] && [ "$(cat "$DGPU" 2>/dev/null)" = 1 ]; then
        read -rp "$(L "Дискретная видеокарта выключена (Eco). Включить перед удалением? [Д/н] " "The discrete GPU is off (Eco). Turn it on before removing? [Y/n] ")" a
        if yes_default "$a"; then
            echo "  $(L "Включаю (до минуты)…" "Turning it on (up to a minute)…")"
            if "$CLI" gpu standard >/dev/null 2>&1; then
                ok "$(L "Дискретная видеокарта включена" "Discrete GPU turned on")"
            else
                warn "$(L "Не включилась — BIOS включит её после перезагрузки" "It did not turn on — the BIOS will enable it after reboot")"
                echo 0 | sudo tee "$DGPU" >/dev/null
            fi
        fi
    fi
    "$CLI" restore >/dev/null 2>&1 &&
        ok "$(L "Заводские лимиты мощности, кривые вентиляторов и Turbo Boost возвращены" "Factory power limits, fan curves and Turbo Boost restored")"
elif [ -n "$DGPU" ] && [ "$(cat "$DGPU" 2>/dev/null)" = 1 ]; then
    # демона нет — только сказать BIOS включить карту; драйвер загрузится после перезагрузки
    echo 0 | sudo tee "$DGPU" >/dev/null &&
        ok "$(L "Дискретная видеокарта включена в BIOS (заработает после перезагрузки)" "Discrete GPU enabled in BIOS (works after reboot)")"
fi

# ---------- 2. значок, ярлыки, клавиша ----------
pkill -f '^/usr/bin/python3 -m asushelper.app' 2>/dev/null
rm -f ~/.config/autostart/asus-helper.desktop ~/.local/share/applications/asus-helper.desktop \
      ~/.local/share/icons/hicolor/scalable/apps/asus-helper.svg
command -v kbuildsycoca6 >/dev/null && kbuildsycoca6 >/dev/null 2>&1
# клавиша окна в «Комбинациях клавиш» KDE
command -v qdbus6 >/dev/null && qdbus6 org.kde.kglobalaccel /kglobalaccel org.kde.KGlobalAccel.unregister \
    asus-helper toggle >/dev/null 2>&1
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/asus-helper"
ok "$(L "Значок, ярлыки и клавиша окна убраны" "Tray icon, launchers and window key removed")"

# ---------- 3. демон и системные файлы ----------
sudo systemctl disable --now asus-helperd.service 2>/dev/null
cd "$(dirname "$(readlink -f "$0")")"
sudo make uninstall PREFIX=/usr/local UDEVDIR=/etc/udev/rules.d DBUSDIR=/etc/dbus-1/system.d \
    POLKITDIR=/usr/share/polkit-1/actions >/dev/null
# и файлы прежних версий установщика
sudo rm -f /etc/systemd/system/asus-helperd.service
sudo rm -rf /var/lib/asus-helper /run/asus-helper
sudo busctl call org.freedesktop.DBus /org/freedesktop/DBus org.freedesktop.DBus ReloadConfig >/dev/null
sudo systemctl daemon-reload
ok "$(L "Демон удалён" "Daemon removed")"

rm -f ~/.config/environment.d/90-kwin-igpu.conf ~/.config/environment.d/91-igpu-apps.conf \
      ~/.config/systemd/user/plasma-kwin_wayland.service.d/asus-helper-igpu.conf
systemctl --user daemon-reload
sudo rm -f /etc/udev/rules.d/61-igpu-symlink.rules
sudo udevadm control --reload
# ссылка /dev/dri/igpu от правила udev: рабочий стол сейчас может на неё опираться — уйдёт с перезагрузкой
kwin=$(pgrep -x kwin_wayland | head -1)
if [ -L /dev/dri/igpu ] && ! { [ -n "$kwin" ] && sudo cat /proc/$kwin/environ 2>/dev/null | tr '\0' '\n' | grep -q '^KWIN_DRM_DEVICES=.*/dev/dri/igpu'; }; then
    sudo rm -f /dev/dri/igpu
fi
ok "$(L "Настройка рабочего стола и prime-run убраны" "Desktop GPU setting and prime-run removed")"

# ---------- 4. настройки ----------
if [ $KEEP_CONFIG = 1 ]; then
    echo "  $(L "Настройки остались в /etc/asus-helper" "Settings kept in /etc/asus-helper")"
else
    sudo rm -rf /etc/asus-helper
    rm -rf ~/.config/asus-helper
    ok "$(L "Настройки удалены" "Settings removed")"
fi
rm -f "$LOG"

# ---------- 5. перезагрузка ----------
echo
echo "${B}$(L "Asus-helper удалён." "Asus-helper removed.")${R}"
echo "  $(L "Перезагрузка вернёт всё остальное как было до установки: рабочий стол, драйвер NVIDIA, режимы." \
             "A reboot returns everything else to how it was before installing: desktop, NVIDIA driver, modes.")"

# Процесс, намертво застрявший в ядре (например, выгрузка драйвера видеокарты), не даст системе выключиться:
# обычная перезагрузка повиснет навсегда. Застрявший — в состоянии D при каждой проверке за 10 секунд
# (на мгновение в D попадает кто угодно, а возраст потоков ядра ничего не говорит).
in_d() { ps -eo pid=,stat= | awk '$2 ~ /^D/ {print $1}' | sort; }
stuck_pids=$(in_d)
for _ in 1 2; do
    [ -z "$stuck_pids" ] && break
    sleep 5
    stuck_pids=$(comm -12 <(echo "$stuck_pids") <(in_d))
done
stuck=""
[ -n "$stuck_pids" ] && stuck=$(ps -o comm= -p $(echo $stuck_pids | tr ' ' ,) | sort | uniq -c | sort -rn | head -3)
read -rp "$(L "Перезагрузить сейчас? Сохраните открытые документы. [Д/н] " "Reboot now? Save your open documents first. [Y/n] ")" a
yes_default "$a" || { echo "  $(L "Перезагрузитесь позже сами." "Reboot later yourself.")"; exit 0; }
if [ -z "$stuck" ]; then
    sudo systemctl reboot
else
    warn "$(L "В ядре зависли процессы — обычная перезагрузка повиснет:" "Processes are stuck in the kernel — a normal reboot would hang:")"
    echo "$stuck" | sed 's/^/      /'
    echo "  $(L "Перезагружаю безопасно: программы закрываются, данные записываются на диск, затем перезапуск." \
                 "Rebooting safely: programs are closed, data is written to disk, then restart.")"
    # то же, что Alt+SysRq R-E-I-S-U-B: закрыть программы, записать диски, перемонтировать только для чтения,
    # перезапуск. Отдельной системной службой — закрытие программ закроет и этот терминал.
    sudo systemd-run --no-block --quiet --unit=asus-helper-safe-reboot sh -c \
        'systemctl kill --signal=TERM user.slice; sleep 5; sync;
         echo s > /proc/sysrq-trigger; sleep 3; echo u > /proc/sysrq-trigger; sleep 3;
         echo b > /proc/sysrq-trigger'
fi
