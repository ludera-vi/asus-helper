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
asus-helper-agent (сеанс пользователя)  — карточки KDE без окна (если окно не нужно)
asus-helper-cli                       — управление из терминала
asus-helper (Qt/QML, в трее)          — окно, карточки KDE, экран
```

| Каталог | Что |
|---|---|
| `asushelper/daemon/` | демон: `hardware.py` (железо), `modes.py` (что и когда применять), `service.py` (D-Bus), `ppd.py` (для KDE) |
| `asushelper/cli.py` | `asus-helper-cli` |
| `asushelper/asusd_import.py` | перенос настроек из `/etc/asusd` |
| `data/` | systemd, D-Bus, polkit |
| `gpu-switch/`, `lighting_keyboard/` | прежние программы — всё перенесено в Asus-helper, оставлены для истории |

## Что умеет

| Раздел | Что |
|---|---|
| Режим | Тихий / Баланс / Турбо, сам по питанию; Fn+F5 и виджет батареи KDE; карточка KDE при смене |
| Вентиляторы и мощность | кривые CPU/GPU для каждого режима, PL1/PL2, NVIDIA temp/boost, EPP, Turbo Boost |
| Видеокарта | Eco / Стандарт / Оптимальный (Eco на батарее), кто держит NVIDIA |
| Экран | Авто (60 Гц на батарее, 240 от сети) / 60 / 240, Overdrive |
| Клавиатура | яркость (и с клавиш — карточка KDE), эффект Aura, цвет, скорость, когда светиться |
| Крышка (Slash) | яркость, 15 анимаций, ровный свет и «заряд батареи», пауза, на батарее, с закрытой крышкой |
| Батарея | лимит заряда, графики датчиков за час, заряд за сутки (UPower), здоровье по дням |
| Прочее | звук при включении, клавиша ROG открывает окно |

## Установка

```bash
./install.sh      # на систему без asusctl / power-profiles-daemon / supergfxctl / envycontrol: снимок → служба, значок, iGPU
./uninstall.sh    # удалить (настройки /etc/asus-helper остаются; --purge — и их)
```

Для разработки без установки: `sudo ./dev-run.sh` (демон в терминале) и `python3 -m asushelper.app --show`.
Проверка всех функций на живом ноутбуке: `python3 -m tests.hw_check --gpu`.

## Тесты

```bash
python3 -m unittest discover -s tests -t .
```
Работают на поддельном sysfs (`ASUSHELPER_SYSROOT`), железо не трогают.
