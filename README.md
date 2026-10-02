# AsusLudera

Своя замена asusd / asusctl / rog-control-center для ASUS ROG Zephyrus G16 GU605MZ, по мотивам
G-Helper. Режимы, вентиляторы, лимиты мощности, видеокарта, подсветка — одним приложением.

## Устройство

```
asusluderad (root, systemd)          — единственный, кто пишет в sysfs и HID
  ├─ режимы + кривые вентиляторов + лимиты мощности + EPP, автоматика сеть/батарея
  ├─ D-Bus org.asusludera.Daemon (права — polkit org.asusludera.manage)
  ├─ видеокарта: Eco / Стандарт / Оптимальный (бывший gpu-eco)
  ├─ подсветка клавиатуры: яркость и Aura по HID (вместо asusd)
  └─ эмуляция power-profiles-daemon → KDE видит режимы (виджет батареи)
asusludera-agent (сеанс пользователя)  — карточки KDE: режим, подсветка; уведомления о видеокарте (бывший asus-osd)
asusludera-cli                       — управление из терминала
asusludera (Qt/QML, в трее)          — интерфейс (этап 5)
```

| Каталог | Что |
|---|---|
| `asusludera/daemon/` | демон: `hardware.py` (железо), `modes.py` (что и когда применять), `service.py` (D-Bus), `ppd.py` (для KDE) |
| `asusludera/cli.py` | `asusludera-cli` |
| `asusludera/asusd_import.py` | перенос настроек из `/etc/asusd` |
| `data/` | systemd, D-Bus, polkit |
| `gpu-switch/`, `lighting_keyboard/` | прежние программы (переносятся в asusludera на этапах 3–5) |

## Этапы

1. ✅ Демон: режимы, EPP, кривые вентиляторов, лимиты мощности, лимит заряда, сеть/батарея, сон, D-Bus, KDE, CLI
2. Вентиляторы и мощность: телеметрия, заводские кривые, проверка на железе
3. ✅ GPU: gpu-eco внутрь демона, режим «Оптимальный» (Eco на батарее) — нужна проверка на железе
4. ✅ Подсветка: Aura (HID 0b05:19b6), яркость; агент с карточками KDE — нужна проверка на железе.
   Позже: таймауты подсветки, Slash (0b05:193b)
5. Интерфейс: окно в трее как у G-Helper, окно вентиляторов, OSD, частота экрана
6. Переезд: установщик, asusd выключается (не удаляется), проверка после сна и перезагрузки

## Пробный запуск

```bash
sudo ./dev-run.sh        # снимок snapper → asusd на паузу → демон в терминале; Ctrl+C — вернуть asusd
python3 -m asusludera.agent  # второй терминал: карточки KDE (asus-osd на это время остановить)
python3 -m asusludera.cli    # третий терминал
```

## Тесты

```bash
python3 -m unittest discover -s tests -t .
```
Работают на поддельном sysfs (`ASUSLUDERA_SYSROOT`), железо не трогают.
