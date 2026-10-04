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
# клавиша окна в «Своих комбинациях клавиш» GNOME
python3 - <<'PY' 2>/dev/null
from gi.repository import Gio
schema, path = "org.gnome.settings-daemon.plugins.media-keys", "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/asus-helper/"
src = Gio.SettingsSchemaSource.get_default()
if src and src.lookup(schema, True):
    keys = Gio.Settings.new(schema)
    if path in keys.get_strv("custom-keybindings"):
        keys.set_strv("custom-keybindings", [p for p in keys.get_strv("custom-keybindings") if p != path])
        entry = Gio.Settings.new_with_path(schema + ".custom-keybinding", path)
        for k in ("name", "command", "binding"):
            entry.reset(k)
        Gio.Settings.sync()
PY
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

# расширения GNOME, которые включил установщик (своё — всегда, трей — если его ставил установщик)
CHANGES="${XDG_STATE_HOME:-$HOME/.local/state}/asus-helper-install-changes"
inst=$(grep '^installed=' "$CHANGES" 2>/dev/null | cut -d= -f2-)
removed=$(grep '^removed=' "$CHANGES" 2>/dev/null | cut -d= -f2-)
drop="asus-helper@ludera-vi.github.com"
[[ " $inst " == *" gnome-shell-extension-appindicator "* ]] && drop="$drop appindicatorsupport@rgcjonas.gmail.com"
python3 - $drop <<'PY' 2>/dev/null
import sys
from gi.repository import Gio
src = Gio.SettingsSchemaSource.get_default()
if src and src.lookup("org.gnome.shell", True):
    s = Gio.Settings.new("org.gnome.shell")
    s.set_strv("enabled-extensions", [e for e in s.get_strv("enabled-extensions") if e not in sys.argv[1:]])
    Gio.Settings.sync()
PY

# ---------- 3a. пакеты: что поставил и что удалил установщик ----------
still=()
for p in $inst; do pacman -Q "$p" >/dev/null 2>&1 && still+=("$p"); done
if [ ${#still[@]} -gt 0 ]; then
    echo "  $(L "Установщик ставил пакеты" "The installer added packages"): ${still[*]}"
    read -rp "$(L "Удалить их (и их зависимости, если они больше никому не нужны)? [Д/н] " "Remove them (and their dependencies no longer needed)? [Y/n] ")" a
    if yes_default "$a"; then
        if sudo pacman -Rns --noconfirm "${still[@]}" >/dev/null 2>&1; then
            ok "$(L "Удалено" "Removed"): ${still[*]}"
        else
            # какой-то пакет нужен другой программе (например, рабочему столу) — удаляем остальные по одному
            kept=()
            for p in "${still[@]}"; do sudo pacman -Rns --noconfirm "$p" >/dev/null 2>&1 || kept+=("$p"); done
            ok "$(L "Удалено, кроме нужных другим программам" "Removed, except those needed by other programs")${kept[*]:+: ${kept[*]}}"
        fi
    fi
fi
back=()
for p in $removed; do pacman -Q "$p" >/dev/null 2>&1 || back+=("$p"); done
if [ ${#back[@]} -gt 0 ]; then
    echo "  $(L "Установщик удалял" "The installer removed"): ${back[*]}"
    read -rp "$(L "Вернуть их? [Д/н] " "Bring them back? [Y/n] ")" a
    if yes_default "$a"; then
        if sudo pacman -S --needed --noconfirm "${back[@]}" >/dev/null 2>&1; then
            # службы вернувшихся пакетов: пакет → служба
            for p in "${back[@]}"; do
                case $p in
                    power-profiles-daemon|tuned-ppd) svc=$p ;;
                    asusctl) svc=asusd ;;
                    supergfxctl) svc=supergfxd ;;
                    *) continue ;;
                esac
                # маска (её часто ставят на power-profiles-daemon ради asusctl) не дала бы службе запуститься;
                # asusd — служба «static», её запускает udev при загрузке: enable ничего не даст, только start
                sudo systemctl unmask "$svc.service" >/dev/null 2>&1
                sudo systemctl enable --now "$svc.service" >/dev/null 2>&1 || sudo systemctl start "$svc.service" >/dev/null 2>&1
            done
            ok "$(L "Возвращено" "Restored"): ${back[*]}"
        else
            warn "$(L "Не вернулись — вручную" "Not restored — by hand"): sudo pacman -S ${back[*]}"
        fi
    fi
fi
rm -f "$CHANGES"

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
