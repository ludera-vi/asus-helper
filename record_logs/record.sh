#!/bin/bash
# Asus-helper: запись логов для проверки на другом дистрибутиве или рабочем столе.
# Asus-helper: log recording for testing on another distribution or desktop.
#
#   ./record_logs/record.sh start            до установки Asus-helper: начать запись
#                                            (продолжается после перезагрузки и сна)
#   ./record_logs/record.sh mark "текст"     своя отметка в логе: «подключил зарядку», «открыл игру»
#   ./record_logs/record.sh status           идёт ли запись
#   ./record_logs/record.sh stop             остановить и собрать всё в один файл рядом со скриптом:
#                                            asus-helper_<дистрибутив>_<рабочий стол>_<wayland|x11>_<дата>.txt
#
# Пишется: состояние ноутбука раз в 2 с (только изменения), журнал ядра, демона, входа/выхода, сна,
# питания и экрана входа с начала каждой загрузки, все предупреждения и ошибки системы.
# Запись идёт системной службой asus-helper-record; stop убирает её и все временные файлы.
set -uo pipefail

NAME=asus-helper-record
LIB=/usr/local/lib/$NAME
DATA=${ASUS_RECORD_DATA:-/var/log/$NAME}     # переменная — только для проверки самого скрипта
UNIT=/etc/systemd/system/$NAME.service
SELF=$(readlink -f "$0")
HERE=$(dirname "$SELF")

L() { case "${LANG:-}" in ru*) printf '%s\n' "$1" ;; *) printf '%s\n' "$2" ;; esac; }

# ---------- снимок системы ----------
desktop() {
    # рабочий стол активного графического сеанса — и когда скрипт запущен из терминала без него
    local de=${XDG_CURRENT_DESKTOP:-} s
    if [ -z "$de" ]; then
        for s in $(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $1}'); do
            [ "$(loginctl show-session "$s" -p Type --value 2>/dev/null)" = tty ] && continue
            de=$(loginctl show-session "$s" -p Desktop --value 2>/dev/null)
            [ -n "$de" ] && break
        done
    fi
    echo "${de:-unknown}"
}

session_type() {
    local t=${XDG_SESSION_TYPE:-} s
    if [ -z "$t" ] || [ "$t" = tty ]; then
        for s in $(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $1}'); do
            t=$(loginctl show-session "$s" -p Type --value 2>/dev/null)
            [ "$t" = wayland ] || [ "$t" = x11 ] && break
        done
    fi
    echo "${t:-unknown}"
}

snapshot() {
    echo "Время           : $(date '+%F %T %z')"
    echo "Дистрибутив     : $(. /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-?} (${ID:-?})")"
    echo "Ядро            : $(uname -r)   параметры: $(cat /proc/cmdline)"
    echo "Ноутбук         : $(cat /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name /sys/class/dmi/id/bios_version 2>/dev/null | tr '\n' ' ')"
    echo "Процессор       : $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2-)"
    echo "Рабочий стол    : $(desktop) ($(session_type))   экран входа: $(systemctl show display-manager -p Id --value 2>/dev/null)"
    echo "Журнал systemd  : $([ -d /var/log/journal ] && echo 'на диске' || echo 'только в памяти')"
    echo
    echo "--- видеокарты ---"
    lspci -nnk 2>/dev/null | grep -A3 -E 'VGA|3D|Display' || echo "lspci нет"
    echo
    echo "--- модули NVIDIA ---"
    lsmod | grep -E '^(nvidia|nouveau)' || echo "не загружены"
    echo
    echo "--- пакеты ---"
    if command -v pacman >/dev/null; then
        pacman -Q 2>/dev/null | grep -Ei '^(linux[^ ]*|nvidia[^ ]*|mesa|lib32-nvidia[^ ]*|asus[^ ]*|rog-[^ ]*|supergfxctl|power-profiles-daemon|tuned[^ ]*|envycontrol|optimus-manager|plasma-desktop|kwin|gnome-shell|mutter|sddm|gdm|plasma-login-manager|lightdm|pyside6|python-gobject|python|kirigami|libkscreen) ' | grep -vE '^linux-(firmware|api-headers)'
    else
        echo "не pacman"
    fi
    echo
    echo "--- Asus-helper ---"
    if command -v asus-helper-cli >/dev/null; then
        echo "версия: $(grep -h __version__ /usr/lib/asus-helper/asushelper/__init__.py /usr/local/lib/asus-helper/asushelper/__init__.py 2>/dev/null | cut -d'"' -f2)"
        echo "служба: $(systemctl is-active asus-helperd 2>/dev/null) / $(systemctl is-enabled asus-helperd 2>/dev/null)"
        asus-helper-cli diag 2>&1
        echo
        asus-helper-cli 2>&1
    else
        echo "не установлен"
    fi
    echo
    echo "--- мешающие службы ---"
    for s in asusd supergfxd power-profiles-daemon tuned tuned-ppd nvidia-powerd nvidia-persistenced; do
        printf '%-22s %s / %s\n' "$s" "$(systemctl is-active $s 2>/dev/null)" "$(systemctl is-enabled $s 2>/dev/null)"
    done
}

# ---------- служба (запускает systemd от root) ----------
nvidia_dev() {
    local d
    for d in /sys/bus/pci/devices/*; do
        [ "$(cat "$d/vendor" 2>/dev/null)" = 0x10de ] && [[ "$(cat "$d/class" 2>/dev/null)" == 0x03* ]] && { echo "$d"; return; }
    done
}

state_line() {
    local dgpu=/sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value
    [ -e "$dgpu" ] || dgpu=/sys/devices/platform/asus-nb-wmi/dgpu_disable
    local power="" p
    for p in /sys/class/power_supply/*; do
        [ "$(cat "$p/scope" 2>/dev/null)" = Device ] && continue
        case $(cat "$p/type" 2>/dev/null) in
            Mains|USB) power+="$(basename "$p" | sed 's/^ucsi-source-psy-//')=$(cat "$p/online" 2>/dev/null) " ;;
            Battery) power+="батарея=$(cat "$p/capacity" 2>/dev/null)%/$(cat "$p/status" 2>/dev/null) " ;;
        esac
    done
    local nv drv="нет" rt=""
    nv=$(nvidia_dev)
    if [ -n "$nv" ]; then
        [ -e "$nv/driver" ] && drv=$(basename "$(readlink "$nv/driver")")
        rt=$(cat "$nv/power/runtime_status" 2>/dev/null)
    fi
    local sess="" s
    for s in $(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $1}'); do
        sess+="$(loginctl show-session "$s" -p Name -p Type -p Desktop -p State --value 2>/dev/null | tr '\n' '/' | sed 's|/$||') "
    done
    local gpu_line
    gpu_line=$(asus-helper-cli 2>/dev/null | grep -E '^(Видеокарта|GPU)|^ +(ожидание|последняя|waiting|last)' | tr -s ' ' | tr '\n' ' ')
    echo "питание: ${power}| dgpu_disable=$(cat "$dgpu" 2>/dev/null) NVIDIA=${nv:+на шине}${nv:-нет на шине} драйвер=$drv $rt nvidia_drm=$(cat /sys/module/nvidia_drm/refcnt 2>/dev/null || echo выгружен) | режим=$(cat /sys/firmware/acpi/platform_profile 2>/dev/null) | демон=$(systemctl is-active asus-helperd 2>/dev/null) | ${gpu_line:-cli нет} | сеансы: $sess"
}

cmd_run() {
    mkdir -p "$DATA"
    echo "===== загрузка $(cat /proc/sys/kernel/random/boot_id) $(date '+%F %T') =====" >> "$DATA/state.log"
    # журнал с начала этой загрузки: ядро, демон, вход/выход, сон, питание, экран входа, отметки
    local units=(asus-helperd systemd-logind systemd-suspend systemd-hibernate systemd-suspend-then-hibernate
                 upower nvidia-powerd nvidia-persistenced sddm gdm plasmalogin lightdm display-manager
                 power-profiles-daemon)
    local match=(_TRANSPORT=kernel) u
    for u in "${units[@]}"; do match+=(+ "_SYSTEMD_UNIT=$u.service" + "UNIT=$u.service"); done
    match+=(+ SYSLOG_IDENTIFIER=asus-record + SYSLOG_IDENTIFIER=systemd-sleep)
    # без шума: блокировки файрвола и аудит
    local noise='UFW BLOCK|UFW AUDIT|audit:|audit\['
    journalctl -b -f -n all -o short-iso --no-hostname "${match[@]}" 2>&1 |
        grep --line-buffered -vE "$noise" >> "$DATA/journal-main.log" &
    journalctl -b -f -n all -o short-iso --no-hostname -p warning 2>&1 |
        grep --line-buffered -vE "$noise" >> "$DATA/journal-warnings.log" &

    local prev="" cur prev_d="" now_d stuck_d last_beat=0
    while true; do
        cur=$(state_line)
        # процессы в состоянии D: короткое — норма, пишем только тех, кто висит две проверки подряд
        now_d=$(ps -eo pid=,stat=,comm= | awk '$2 ~ /^D/ {print $1":"$3}' | sort)
        stuck_d=$(comm -12 <(echo "$prev_d") <(echo "$now_d") | cut -d: -f2 | sort -u | tr '\n' ' ')
        prev_d=$now_d
        cur+=" | висят: [${stuck_d}]"
        if [ "$cur" != "$prev" ] || [ $(( SECONDS - last_beat )) -ge 600 ]; then
            echo "$(date '+%F %T') $cur" >> "$DATA/state.log"
            prev=$cur
            last_beat=$SECONDS
        fi
        sleep 2
    done
}

# ---------- команды ----------
cmd_start() {
    if systemctl is-active -q $NAME 2>/dev/null; then
        L "Запись уже идёт: $0 status" "Recording is already running: $0 status"; exit 0
    fi
    L "Нужны права root — sudo спросит пароль." "Root is needed — sudo will ask for the password."
    sudo -v || exit 1
    sudo install -Dm755 "$SELF" "$LIB/record.sh" || exit 1
    sudo mkdir -p "$DATA"
    date '+%F %T' | sudo tee "$DATA/started" >/dev/null
    snapshot 2>&1 | sudo tee "$DATA/before.txt" >/dev/null
    # если журнал только в памяти — включить хранение на диске, иначе после перезагрузки он пропадёт
    if [ ! -d /var/log/journal ]; then
        sudo mkdir -p /var/log/journal && sudo systemd-tmpfiles --create --prefix /var/log/journal &&
            sudo systemctl restart systemd-journald && echo created | sudo tee "$DATA/journal-created" >/dev/null
    fi
    sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Asus-helper: запись логов для проверки (record_logs/record.sh)
After=systemd-journald.service

[Service]
ExecStart=$LIB/record.sh run
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    sudo systemctl daemon-reload && sudo systemctl enable --now $NAME || exit 1
    logger -t asus-record "=== запись начата ==="
    L "Запись идёт. Теперь ставьте Asus-helper и проверяйте: перезагрузка, сон, зарядка — всё запишется.
Отметка: $0 mark \"подключил зарядку\"
Закончить: $0 stop" \
      "Recording. Now install Asus-helper and test: reboot, sleep, charger — everything is recorded.
Mark: $0 mark \"plugged the charger\"
Finish: $0 stop"
}

cmd_mark() {
    logger -t asus-record "ОТМЕТКА: $*"
    L "Отмечено: $*" "Marked: $*"
}

cmd_status() {
    if systemctl is-active -q $NAME 2>/dev/null; then
        L "Запись идёт с $(cat $DATA/started 2>/dev/null), размер: $(du -sh $DATA 2>/dev/null | cut -f1)" \
          "Recording since $(cat $DATA/started 2>/dev/null), size: $(du -sh $DATA 2>/dev/null | cut -f1)"
    else
        L "Запись не идёт." "Not recording."
    fi
}

cmd_stop() {
    [ -f "$DATA/started" ] || { L "Запись не начиналась: $0 start" "Nothing recorded yet: $0 start"; exit 1; }
    L "Нужны права root — sudo спросит пароль." "Root is needed — sudo will ask for the password."
    sudo -v || exit 1
    logger -t asus-record "=== запись остановлена ==="
    sleep 1
    sudo systemctl disable --now $NAME 2>/dev/null
    local started distro out
    started=$(cat "$DATA/started")
    distro=$(. /etc/os-release 2>/dev/null; echo "${ID:-linux}")
    out="$HERE/asus-helper_${distro}_$(desktop | tr ':/ ' '---')_$(session_type)_$(date '+%F_%H-%M').txt"
    {
        echo "######## Asus-helper: логи проверки ########"
        echo "Запись: с $started по $(date '+%F %T')"
        echo "Загрузки за это время:"
        journalctl --list-boots --no-pager 2>/dev/null | tail -10
        echo
        echo "######## ДО установки ########"
        sudo cat "$DATA/before.txt"
        echo
        echo "######## СЕЙЧАС ########"
        snapshot 2>&1
        echo
        echo "######## СОСТОЯНИЕ (раз в 2 с, только изменения) ########"
        sudo cat "$DATA/state.log"
        echo
        echo "######## ЖУРНАЛ: ядро, демон, вход/выход, сон, питание ########"
        sudo cat "$DATA/journal-main.log"
        echo
        echo "######## ОКНО В ТРЕЕ И РАБОЧИЙ СТОЛ (журнал пользователя) ########"
        journalctl --user --since "$started" --no-pager -o short-iso --no-hostname 2>/dev/null |
            grep -iE 'asus|asushelper|nvidia|kwin|gnome-shell|mutter|xwayland|plasmashell|warn|error|fail' | tail -5000
        echo
        echo "######## УСТАНОВЩИК (~/.cache/asus-helper-install.log) ########"
        cat "${XDG_CACHE_HOME:-$HOME/.cache}/asus-helper-install.log" 2>/dev/null || echo "нет"
        echo
        echo "######## ВСЕ ПРЕДУПРЕЖДЕНИЯ И ОШИБКИ СИСТЕМЫ ########"
        sudo cat "$DATA/journal-warnings.log"
    } > "$out" 2>&1
    # убрать за собой: службу, копию скрипта, временные логи (журнал на диске, если включали, — оставить)
    sudo rm -f "$UNIT"
    sudo systemctl daemon-reload
    sudo rm -rf "$LIB" "$DATA"
    L "Готово: $out ($(du -h "$out" | cut -f1))" "Done: $out ($(du -h "$out" | cut -f1))"
}

case "${1:-}" in
    start)  cmd_start ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    mark)   shift; cmd_mark "$*" ;;
    run)    cmd_run ;;
    *)      sed -n '2,13p' "$SELF" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
