# record_logs — логи для проверки на другом дистрибутиве или рабочем столе

Скрипт записывает всё, что нужно для разбора проблем: до установки Asus-helper, во время и после —
через перезагрузки и сон. В конце собирает один файл с понятным названием.

```bash
git clone https://github.com/ludera-vi/asus-helper && cd asus-helper
./record_logs/record.sh start          # 1. до установки — запись пошла
./install.sh                           # 2. ставим как обычно
# 3. проверяем: перезагрузка, сон, зарядка вкл/выкл, Eco/Стандарт/Авто, игры на NVIDIA…
./record_logs/record.sh mark "отключил зарядку"   # своя отметка в логе (по желанию)
./record_logs/record.sh status         # идёт ли запись
./record_logs/record.sh stop           # 4. остановить и собрать файл
```

Результат — рядом со скриптом, например `asus-helper_endeavouros_GNOME_wayland_2026-10-05_14-30.txt`.

Что внутри: система до установки и сейчас (дистрибутив, ядро, рабочий стол, видеокарты, пакеты,
`asus-helper-cli diag`), состояние ноутбука раз в 2 с (питание, видеокарта, драйвер, режим, демон,
ожидание Eco, сеансы, зависшие процессы — только изменения), журнал ядра, демона, входа/выхода, сна и
питания с начала каждой загрузки, журнал окна в трее, лог установщика, все предупреждения и ошибки системы.

Запись идёт системной службой `asus-helper-record` (нужен sudo). `stop` убирает её и временные файлы.
Если журнал systemd хранился только в памяти, `start` включает хранение на диске — иначе после
перезагрузки он бы пропал.

---

**English.** `./record_logs/record.sh start` before installing, test (reboot, sleep, charger, GPU modes),
`./record_logs/record.sh stop` — everything is collected into one file named after the distribution,
desktop and session type, next to the script.
