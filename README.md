# Asus-helper

Своя замена asusd / asusctl / rog-control-center для ASUS ROG Zephyrus G16 GU605MZ, по мотивам
G-Helper. Режимы, вентиляторы, лимиты мощности, видеокарта, подсветка — одним приложением.

## Устройство

```
asus-helperd (root, systemd)          — единственный, кто пишет в sysfs и HID
  ├─ режимы + кривые вентиляторов + лимиты мощности + EPP, автоматика сеть/батарея
  ├─ D-Bus org.asushelper.Daemon (права — polkit org.asushelper.manage)
  ├─ видеокарта: Eco / Стандарт / Оптимальный (бывший gpu-eco)
  ├─ подсветка клавиатуры: яркость и Aura по HID (вместо asusd)
  └─ эмуляция power-profiles-daemon → KDE видит режимы (виджет батареи)
asus-helper-agent (сеанс пользователя)  — карточки KDE: режим, подсветка; уведомления о видеокарте (бывший asus-osd)
asus-helper-cli                       — управление из терминала
asushelper (Qt/QML, в трее)          — интерфейс (этап 5)
```

| Каталог | Что |
|---|---|
| `asushelper/daemon/` | демон: `hardware.py` (железо), `modes.py` (что и когда применять), `service.py` (D-Bus), `ppd.py` (для KDE) |
| `asushelper/cli.py` | `asus-helper-cli` |
| `asushelper/asusd_import.py` | перенос настроек из `/etc/asusd` |
| `data/` | systemd, D-Bus, polkit |
| `gpu-switch/`, `lighting_keyboard/` | прежние программы (переносятся в asushelper на этапах 3–5) |

## Что умеет

| Раздел | Что |
|---|---|
| Режим | Тихий / Баланс / Турбо, сам по питанию; Fn+F5 и виджет батареи KDE; карточка KDE при смене |
| Вентиляторы и мощность | кривые CPU/GPU для каждого режима, PL1/PL2, NVIDIA temp/boost, EPP, Turbo Boost |
| Видеокарта | Eco / Стандарт / Оптимальный (Eco на батарее), кто держит NVIDIA |
| Экран | Авто (60 Гц на батарее, 240 от сети) / 60 / 240, Overdrive |
| Клавиатура | яркость (и с клавиш — карточка KDE), эффект Aura, цвет, скорость, когда светиться |
| Крышка (Slash) | яркость, 16 анимаций и «заряд батареи», пауза, на батарее, с закрытой крышкой |
| Батарея | лимит заряда, графики датчиков за час, заряд за сутки (UPower), здоровье по дням |
| Прочее | звук при включении, клавиша ROG открывает окно |

## Установка

```bash
./install.sh      # снимок snapper → служба asus-helperd, значок в трее; asusd выключается (не удаляется)
./uninstall.sh    # вернуть как было
```

Для разработки без установки: `sudo ./dev-run.sh` (демон в терминале) и `python3 -m asushelper.app --show`.
Проверка всех функций на живом ноутбуке: `python3 -m tests.hw_check --gpu`.

## Тесты

```bash
python3 -m unittest discover -s tests -t .
```
Работают на поддельном sysfs (`ASUSHELPER_SYSROOT`), железо не трогают.
