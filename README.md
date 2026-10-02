# asushero

Своя замена asusd / asusctl / rog-control-center для ASUS ROG Zephyrus G16 GU605MZ, по мотивам
G-Helper. Режимы, вентиляторы, лимиты мощности, видеокарта, подсветка — одним приложением.

## Устройство

```
asusherod (root, systemd)          — единственный, кто пишет в sysfs и HID
  ├─ режимы + кривые вентиляторов + лимиты мощности + EPP, автоматика сеть/батарея
  ├─ D-Bus org.asushero.Daemon (права — polkit org.asushero.manage)
  └─ эмуляция power-profiles-daemon → KDE видит режимы (виджет батареи, карточка Fn+F5)
asushero-cli                       — управление из терминала
asushero (Qt/QML, в трее)          — интерфейс (этап 5)
```

| Каталог | Что |
|---|---|
| `asushero/daemon/` | демон: `hardware.py` (железо), `modes.py` (что и когда применять), `service.py` (D-Bus), `ppd.py` (для KDE) |
| `asushero/cli.py` | `asushero-cli` |
| `asushero/asusd_import.py` | перенос настроек из `/etc/asusd` |
| `data/` | systemd, D-Bus, polkit |
| `gpu-switch/`, `lighting_keyboard/` | прежние программы (переносятся в asushero на этапах 3–5) |

## Этапы

1. ✅ Демон: режимы, EPP, кривые вентиляторов, лимиты мощности, лимит заряда, сеть/батарея, сон, D-Bus, KDE, CLI
2. Вентиляторы и мощность: телеметрия, заводские кривые, проверка на железе
3. GPU: gpu-eco внутрь демона, режим «Оптимальный» (Eco на батарее)
4. Подсветка: Aura (HID 0b05:19b6), яркость и таймауты, Slash (0b05:193b)
5. Интерфейс: окно в трее как у G-Helper, окно вентиляторов, OSD, частота экрана
6. Переезд: установщик, asusd выключается (не удаляется), проверка после сна и перезагрузки

## Пробный запуск

```bash
sudo ./dev-run.sh        # снимок snapper → asusd на паузу → демон в терминале; Ctrl+C — вернуть asusd
python3 -m asushero.cli  # в другом терминале
```

## Тесты

```bash
python3 -m unittest discover -s tests -t .
```
Работают на поддельном sysfs (`ASUSHERO_SYSROOT`), железо не трогают.
