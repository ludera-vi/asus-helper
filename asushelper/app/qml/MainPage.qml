// Главная страница в раскладке G-Helper: в каждом разделе ряд плиток, в заголовке — что выбрано
// и что с датчиками. Редкие настройки (скорость эффекта, когда светиться) — во всплывающих окнах.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: page

    signal openFans()
    signal openMonitor()

    readonly property var st: backend.state || {}
    readonly property var gpu: st.gpu || {}
    readonly property var kbd: st.keyboard || {}
    // режимы, которые есть у этого ноутбука (до ответа демона — все)
    readonly property var profiles: Theme.profiles.filter(p => !(st.profiles || []).length || st.profiles.indexOf(p.id) !== -1)
    readonly property var bat: st.battery || {}
    readonly property var fans: st.fans || {}
    readonly property var disp: backend.display || {}
    readonly property var nv: backend.nvidia || {}
    readonly property var toggles: st.toggles || {}
    readonly property var sl: st.slash || {}
    readonly property string dgpu: gpu.dgpu_name || "NVIDIA"     // имя дискретной видеокарты из системы

    spacing: Kirigami.Units.largeSpacing * 1.5

    // ---------- режим ----------
    Section {
        title: Theme.tr("Режим")
        value: Theme.profileName(page.st.profile)
        iconName: "speedometer-symbolic"
        info: (page.st.cpu_temp != null ? "CPU " + Math.round(page.st.cpu_temp) + " °C" : "")
              + (page.fans.cpu == null ? "" : page.fans.cpu === 0 ? Theme.tr("  ·  вентилятор стоит") : "  ·  " + page.fans.cpu + Theme.tr(" об/мин"))

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: page.profiles
                Tile {
                    required property var modelData
                    text: modelData.name
                    iconName: modelData.icon
                    accent: Theme.profileColor(modelData.id)
                    selected: page.st.profile === modelData.id
                    onClicked: backend.setProfile(modelData.id)
                }
            }
            Tile {
                // есть что настраивать: свои кривые или лимиты мощности с диапазоном
                visible: !!page.st.fan_curves
                         || Object.values(page.st.power_limits || {}).some(l => l.min !== null && l.max !== null && l.max > l.min)
                text: Theme.tr("Вентиляторы")
                subtitle: Theme.tr("и мощность")
                iconName: Qt.resolvedUrl("icons/fan-symbolic.svg")
                onClicked: page.openFans()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            QQC2.Switch {
                id: autoProfile
                text: Theme.tr("Сам по питанию")
                checked: !!page.st.auto_profile
                onToggled: backend.setAutoProfile(checked)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: Theme.tr("Подключили зарядку или отключили — включается режим, который ты выбирал для этого питания")
            }
            Item { Layout.fillWidth: true }
            QQC2.Label {
                visible: autoProfile.checked
                text: Theme.tr("от сети: ") + Theme.profileName(page.st.profile_on_ac) + Theme.tr("  ·  от батареи: ") + Theme.profileName(page.st.profile_on_battery)
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }
        }
    }

    // ---------- видеокарта ----------
    Section {
        visible: !!page.gpu.supported
        title: Theme.tr("Видеокарта")
        value: page.gpu.auto_eco ? Theme.tr("Авто")
             : page.gpu.switching ? (page.gpu.target === "eco" ? "Eco" : Theme.tr("Стандарт"))
             : page.gpu.state === "off" ? "Eco" : Theme.tr("Стандарт")
        iconName: Qt.resolvedUrl("icons/gpu-symbolic.svg")
        info: (page.gpu.auto_eco && !page.gpu.switching
               ? (page.gpu.state === "off" ? Theme.tr("без сети — %1 отключена").arg(page.dgpu)
                                           : Theme.tr("от сети — %1 включена").arg(page.dgpu))
               : Theme.gpuInfo(page.gpu, page.nv))
              + (page.fans.gpu == null ? "" : page.fans.gpu === 0 ? Theme.tr("  ·  вентилятор стоит") : "  ·  " + page.fans.gpu + Theme.tr(" об/мин"))
        infoColor: page.gpu.state === "active" ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Tile {
                text: "Eco"
                subtitle: page.gpu.waiting_manual ? Theme.tr("ждёт: %1").arg(page.gpu.auto_waiting[0])
                        : Theme.tr("%1 выключена").arg(page.dgpu)
                iconName: "battery-profile-powersave-symbolic"
                accent: Theme.positive
                selected: !page.gpu.auto_eco && (page.gpu.switching ? page.gpu.target === "eco"
                                                 : page.gpu.state === "off" || !!page.gpu.waiting_manual)
                dimmed: !!page.gpu.waiting_manual
                busy: !!page.gpu.switching && page.gpu.target === "eco"
                enabled: !page.gpu.switching && !page.gpu.stuck && !!page.gpu.mux_hybrid
                onClicked: (page.gpu.external || []).length ? displayWarning.open() : backend.setGpuMode("eco", false)
            }
            Tile {
                text: Theme.tr("Стандарт")
                subtitle: (page.gpu.igpu_name || "iGPU") + " + " + page.dgpu
                iconName: "monitor-symbolic"
                accent: Theme.highlight
                selected: !page.gpu.auto_eco && (page.gpu.switching ? page.gpu.target === "standard"
                                                 : page.gpu.state !== "off" && !page.gpu.waiting_manual)
                busy: !!page.gpu.switching && page.gpu.target === "standard"
                enabled: !page.gpu.switching && !page.gpu.stuck
                onClicked: backend.setGpuMode("standard", false)
            }
            Tile {
                text: Theme.tr("Авто")
                // что работает прямо сейчас
                subtitle: page.gpu.switching ? Theme.tr("переключается…")
                        : page.gpu.auto_waiting && !page.gpu.waiting_manual ? Theme.tr("ждёт: %1").arg(page.gpu.auto_waiting[0])
                        : page.gpu.state === "off" ? Theme.tr("работает %1").arg(page.gpu.igpu_name || Theme.tr("встроенная"))
                        : Theme.tr("включена %1").arg(page.dgpu)
                iconName: "automated-tasks-symbolic"
                accent: Theme.neutral
                selected: !!page.gpu.auto_eco
                dimmed: !!page.gpu.auto_waiting && !page.gpu.waiting_manual
                enabled: !page.gpu.switching && !page.gpu.stuck && !!page.gpu.mux_hybrid
                onClicked: backend.setGpuAutoEco(true)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: Theme.tr("Отключил зарядку — %1 выключается (Eco), батарея живёт дольше.\nПодключил — %1 включается для игр и тяжёлых программ.").arg(page.dgpu)
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: text !== ""
            text: [page.gpu.igpu_model, page.gpu.dgpu_model].filter(m => !!m).join("  ·  ")
            font: Kirigami.Theme.smallFont
            opacity: 0.55
            elide: Text.ElideRight
        }
        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: !!page.gpu.error && !page.gpu.switching
            type: Kirigami.MessageType.Warning
            text: page.gpu.error || ""
        }
        Kirigami.InlineMessage {
            // Eco (вручную или «Авто» без зарядки), а на NVIDIA работают программы — ждём, пока закроют,
            // закрыть сразу или отменить
            Layout.fillWidth: true
            visible: !!page.gpu.auto_waiting && !page.gpu.switching
            type: Kirigami.MessageType.Information
            text: Theme.tr("Ожидание закрытия: %1. Потом %2 выключится сама.")
                  .arg((page.gpu.auto_waiting || []).join(", ")).arg(page.dgpu)
            actions: [
                Kirigami.Action {
                    text: Theme.tr("Закрыть и выключить")
                    icon.name: "process-stop-symbolic"
                    onTriggered: backend.answerGpuAuto("close")
                },
                Kirigami.Action {
                    // отменить можно только свой Eco; «Авто» дождётся закрытия и выключит карту само
                    visible: !!page.gpu.waiting_manual
                    text: Theme.tr("Отмена")
                    icon.name: "dialog-cancel-symbolic"
                    onTriggered: backend.answerGpuAuto("cancel")
                }
            ]
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: !page.gpu.error && (page.gpu.holders || []).length > 0
            text: Theme.tr("Держат %1: ").arg(page.dgpu) + (page.gpu.holders || []).join(", ")
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            elide: Text.ElideRight
        }
    }

    // ---------- экран ----------
    Section {
        visible: (page.disp.rates || []).length > 1
        title: Theme.tr("Экран")
        value: page.disp.hz ? page.disp.hz + Theme.tr(" Гц") + (page.toggles.panel_overdrive ? " + OD" : "") : ""
        iconName: "monitor-symbolic"
        info: backend.screenAuto && page.disp.rates ? Theme.tr("авто: ") + page.disp.rates[0] + Theme.tr(" на батарее, ") + page.disp.rates[1] + Theme.tr(" от сети") : ""

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Tile {
                compact: true
                text: Theme.tr("Авто")
                selected: backend.screenAuto
                onClicked: backend.setScreenAuto(true)
            }
            Repeater {
                model: page.disp.rates || []
                Tile {
                    required property int modelData
                    compact: true
                    text: modelData + Theme.tr(" Гц")
                    selected: !backend.screenAuto && page.disp.hz === modelData
                    onClicked: { backend.setScreenAuto(false); backend.setRefreshRate(modelData) }
                }
            }
            Tile {
                compact: true
                visible: page.toggles.panel_overdrive !== undefined
                text: "Overdrive"
                accent: Theme.neutral
                selected: !!page.toggles.panel_overdrive
                onClicked: backend.setToggle("panel_overdrive", !page.toggles.panel_overdrive)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: Theme.tr("Разгон матрицы: быстрее отклик, меньше шлейфов в играх")
            }
        }
    }

    // ---------- клавиатура ----------
    Section {
        visible: !!page.st.keyboard
        title: Theme.tr("Клавиатура")
        value: page.kbd.rgb ? (Theme.auraModes.find(m => m.id === page.kbd.mode) || {}).name || "" : ""
        iconName: "input-keyboard-symbolic"
        info: page.kbd.brightness === 0 ? Theme.tr("подсветка выключена") : ""

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                // уровни яркости — сколько их у этой клавиатуры (обычно 0–3)
                model: page.kbd.max === 3 || page.kbd.max === undefined ? [Theme.tr("Выкл"), Theme.tr("Низкая"), Theme.tr("Средняя"), Theme.tr("Высокая")]
                     : Array.from({ length: page.kbd.max + 1 }, (_, i) => i === 0 ? Theme.tr("Выкл") : String(i))
                Tile {
                    required property string modelData
                    required property int index
                    compact: true
                    text: modelData
                    accent: page.kbd.rgb ? page.kbd.color || Theme.highlight : Theme.highlight
                    selected: page.kbd.brightness === index
                    onClicked: backend.setKeyboardBrightness(index)
                }
            }
        }

        RowLayout {
            visible: !!page.kbd.rgb
            spacing: Kirigami.Units.smallSpacing
            QQC2.ComboBox {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                model: Theme.auraModes.map(m => m.name)
                currentIndex: Math.max(0, Theme.auraModes.findIndex(m => m.id === page.kbd.mode))
                onActivated: i => backend.setAura(Theme.auraModes[i].id, page.kbd.color, page.kbd.color2, page.kbd.speed)
            }
            QQC2.Button {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                enabled: page.kbd.mode !== "cycle"
                onClicked: colorPopup.open()
                contentItem: RowLayout {
                    spacing: Kirigami.Units.smallSpacing
                    Item { Layout.fillWidth: true }
                    QQC2.Label { text: Theme.tr("Цвет") }
                    Rectangle {
                        implicitWidth: Kirigami.Units.iconSizes.small
                        implicitHeight: implicitWidth
                        radius: 3
                        color: page.kbd.color || "white"
                        border.color: Qt.alpha(Kirigami.Theme.textColor, 0.3)
                    }
                    Item { Layout.fillWidth: true }
                }
            }
            QQC2.Button {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: Theme.tr("Ещё")
                icon.name: "settings-configure-symbolic"
                onClicked: extraPopup.open()
            }
        }
    }

    // ---------- Slash на крышке ----------
    Section {
        visible: !!page.sl.supported
        title: Theme.tr("Подсветка крышки")
        value: page.sl.brightness > 0 ? ((page.sl.modes || []).find(m => m.id === page.sl.mode) || {}).name || "" : Theme.tr("выключена")
        iconName: "computer-laptop-symbolic"

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: [Theme.tr("Выкл"), Theme.tr("Тускло"), Theme.tr("Средне"), Theme.tr("Ярко")]
                Tile {
                    required property string modelData
                    required property int index
                    compact: true
                    text: modelData
                    selected: page.sl.brightness === index
                    onClicked: backend.setSlash(page.sl.mode, index, page.sl.interval)
                }
            }
        }
        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            QQC2.ComboBox {
                Layout.fillWidth: true
                Layout.preferredWidth: 2
                model: (page.sl.modes || []).map(m => m.name)
                currentIndex: Math.max(0, (page.sl.modes || []).findIndex(m => m.id === page.sl.mode))
                onActivated: i => backend.setSlash(page.sl.modes[i].id, Math.max(1, page.sl.brightness), page.sl.interval)
            }
            QQC2.Button {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: Theme.tr("Ещё")
                icon.name: "settings-configure-symbolic"
                onClicked: slashPopup.open()
            }
        }
    }

    // ---------- батарея ----------
    Section {
        visible: page.bat.capacity !== undefined
        title: Theme.tr("Батарея")
        value: page.bat.capacity + "%"
        iconName: page.st.ac ? "battery-full-charging-symbolic" : "battery-good-symbolic"
        info: (page.bat.status === "Discharging" ? page.bat.power_w + Theme.tr(" Вт") : page.st.ac ? Theme.tr("от сети") : "")
              + (page.bat.health ? Theme.tr("  ·  здоровье ") + page.bat.health + "%" : "")

        RowLayout {
            Layout.fillWidth: true
            visible: page.bat.charge_limit !== null && page.bat.charge_limit !== undefined   // ядро умеет ограничивать заряд
            spacing: Kirigami.Units.largeSpacing
            QQC2.Label { text: Theme.tr("Заряжать до") }
            QQC2.Slider {
                id: chargeSlider
                Layout.fillWidth: true
                from: 60; to: 100; stepSize: 5
                snapMode: QQC2.Slider.SnapAlways
                value: page.bat.charge_limit || 100
                onPressedChanged: if (!pressed && value !== page.bat.charge_limit) backend.setChargeLimit(value)
                Keys.onReleased: if (value !== page.bat.charge_limit) backend.setChargeLimit(value)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: Theme.tr("Если ноутбук почти всегда от сети, 80% заметно продлят жизнь батареи")
            }
            QQC2.Label {
                text: Math.round(chargeSlider.value) + "%"
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                font.weight: Font.DemiBold
            }
        }
    }

    // ---------- низ ----------
    RowLayout {
        Layout.fillWidth: true
        QQC2.Switch {
            visible: page.toggles.boot_sound !== undefined
            text: Theme.tr("Звук при включении")
            checked: !!page.toggles.boot_sound
            onToggled: backend.setToggle("boot_sound", checked)
        }
        Item { Layout.fillWidth: true }
        // оформление: как в системе (KDE) или оригинальное — окно перезапустится в выбранном
        QQC2.ToolButton {
            id: themeButton
            icon.name: "color-management"
            display: QQC2.AbstractButton.IconOnly
            text: Theme.tr("Оформление")
            onClicked: themeMenu.open()
            QQC2.ToolTip.visible: hovered && !themeMenu.visible
            QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
            QQC2.ToolTip.text: Theme.tr("Оформление: %1").arg(backend.theme === "original" ? Theme.tr("оригинальное") : Theme.tr("как в системе"))
            QQC2.Menu {
                id: themeMenu
                y: -height
                QQC2.MenuItem {
                    text: Theme.tr("Как в системе (KDE)")
                    checkable: true
                    checked: backend.themeWanted === "system"
                    // стиля KDE нет (не Plasma или не установлен qqc2-desktop-style) — выбрать нельзя
                    enabled: backend.kdeStyle
                    onTriggered: backend.setTheme("system")
                }
                QQC2.MenuItem {
                    text: Theme.tr("Оригинальное (тёмное)")
                    checkable: true
                    checked: backend.themeWanted === "original"
                    onTriggered: backend.setTheme("original")
                }
            }
        }
        // язык: RU / EN — программа перезапустится на выбранном
        Repeater {
            model: ["ru", "en"]
            QQC2.ToolButton {
                required property string modelData
                text: modelData.toUpperCase()
                checkable: true
                checked: backend.language === modelData
                font: Kirigami.Theme.smallFont
                onClicked: if (backend.language !== modelData) backend.setLanguage(modelData)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: modelData === "ru" ? "Русский" : "English"
            }
        }
        QQC2.Label {
            text: page.st.version ? "v" + page.st.version : ""
            font: Kirigami.Theme.smallFont
            opacity: 0.5
        }
    }

    // ---------- предупреждение: монитор на NVIDIA ----------
    QQC2.Popup {
        id: displayWarning
        parent: QQC2.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 20)
        modal: true
        padding: Kirigami.Units.largeSpacing * 1.5
        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            RowLayout {
                Kirigami.Icon { source: "dialog-warning"; implicitWidth: Kirigami.Units.iconSizes.medium; implicitHeight: implicitWidth }
                Kirigami.Heading { level: 4; text: Theme.tr("Подключён внешний монитор"); Layout.fillWidth: true; wrapMode: Text.Wrap }
            }
            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: Theme.tr("Монитор (%1) подключён к видеокарте %2. ").arg((page.gpu.external || []).join(", ")).arg(page.dgpu)
                      + Theme.tr("Если её выключить, он погаснет — изображение останется только на экране ноутбука.")
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                QQC2.Button { text: Theme.tr("Отмена"); onClicked: displayWarning.close() }
                QQC2.Button {
                    text: Theme.tr("Всё равно выключить")
                    icon.name: "battery-profile-powersave-symbolic"
                    onClicked: { displayWarning.close(); backend.setGpuModeFlags("eco", 2) }
                }
            }
        }
    }

    // ---------- всплывающее: цвет ----------
    QQC2.Popup {
        id: colorPopup
        parent: QQC2.Overlay.overlay
        anchors.centerIn: parent
        modal: true
        padding: Kirigami.Units.largeSpacing * 1.5
        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Heading { level: 4; text: Theme.tr("Цвет подсветки") }
            GridLayout {
                columns: 5
                columnSpacing: Kirigami.Units.largeSpacing
                rowSpacing: Kirigami.Units.largeSpacing
                Repeater {
                    model: Theme.swatches
                    ColorSwatch {
                        required property string modelData
                        color: modelData
                        selected: page.kbd.color === modelData
                        onClicked: { backend.setAura(page.kbd.mode, modelData, page.kbd.color2, page.kbd.speed); colorPopup.close() }
                    }
                }
            }
            QQC2.Button {
                Layout.fillWidth: true
                text: Theme.tr("Свой цвет…")
                icon.name: "color-picker-symbolic"
                onClicked: { colorPopup.close(); colorDialog.selectedColor = page.kbd.color; colorDialog.open() }
            }
        }
    }

    ColorDialog {
        id: colorDialog
        title: Theme.tr("Цвет подсветки")
        onAccepted: backend.setAura(page.kbd.mode === "cycle" ? "static" : page.kbd.mode,
                                    selectedColor.toString().toUpperCase(), page.kbd.color2, page.kbd.speed)
    }

    // ---------- всплывающее: ещё про Slash ----------
    QQC2.Popup {
        id: slashPopup
        parent: QQC2.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 20)
        modal: true
        padding: Kirigami.Units.largeSpacing * 1.5
        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Heading { level: 4; text: Theme.tr("Подсветка крышки") }
            RowLayout {
                QQC2.Label { text: Theme.tr("Пауза между повторами"); Layout.fillWidth: true }
                QQC2.Label { text: intervalSlider.value + Theme.tr(" с"); font.weight: Font.DemiBold }
            }
            QQC2.Slider {
                id: intervalSlider
                Layout.fillWidth: true
                from: 0; to: 5; stepSize: 1
                snapMode: QQC2.Slider.SnapAlways
                value: page.sl.interval || 0
                onPressedChanged: if (!pressed) backend.setSlash(page.sl.mode, page.sl.brightness, value)
            }
            QQC2.Switch {
                text: Theme.tr("Светиться на батарее")
                checked: !!page.sl.on_battery
                onToggled: backend.setSlashOptions(checked, !!page.sl.lid_closed)
            }
            QQC2.Switch {
                text: Theme.tr("Светиться с закрытой крышкой")
                checked: !!page.sl.lid_closed
                onToggled: backend.setSlashOptions(!!page.sl.on_battery, checked)
            }
            QQC2.Button {
                Layout.alignment: Qt.AlignRight
                text: Theme.tr("Готово")
                onClicked: slashPopup.close()
            }
        }
    }

    // ---------- всплывающее: ещё про подсветку ----------
    QQC2.Popup {
        id: extraPopup
        parent: QQC2.Overlay.overlay
        anchors.centerIn: parent
        width: Math.min(parent.width - Kirigami.Units.gridUnit * 2, Kirigami.Units.gridUnit * 20)
        modal: true
        padding: Kirigami.Units.largeSpacing * 1.5
        contentItem: ColumnLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Heading { level: 4; text: Theme.tr("Подсветка клавиатуры") }

            QQC2.Label { text: Theme.tr("Скорость эффекта"); opacity: 0.8; visible: page.kbd.mode !== "static" }
            RowLayout {
                visible: page.kbd.mode !== "static"
                spacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: [{ id: "slow", name: Theme.tr("Медленно") }, { id: "normal", name: Theme.tr("Обычно") }, { id: "fast", name: Theme.tr("Быстро") }]
                    Tile {
                        required property var modelData
                        compact: true
                        text: modelData.name
                        selected: page.kbd.speed === modelData.id
                        onClicked: backend.setAura(page.kbd.mode, page.kbd.color, page.kbd.color2, modelData.id)
                    }
                }
            }

            QQC2.Label { text: Theme.tr("Гаснуть, если клавиатуру и тачпад не трогать"); opacity: 0.8 }
            GridLayout {
                id: timeouts
                columns: 2
                Layout.fillWidth: true
                readonly property var values: [0, 15, 30, 60, 120, 300, 600]
                readonly property var names: [Theme.tr("никогда"), Theme.tr("через 15 с"), Theme.tr("через 30 с"), Theme.tr("через 1 мин"), Theme.tr("через 2 мин"), Theme.tr("через 5 мин"), Theme.tr("через 10 мин")]
                function index(v) { const i = values.indexOf(v || 0); return i < 0 ? 0 : i }
                QQC2.Label { text: Theme.tr("От сети") }
                QQC2.ComboBox {
                    Layout.fillWidth: true
                    model: timeouts.names
                    currentIndex: timeouts.index(page.kbd.timeout_ac)
                    onActivated: i => backend.setKeyboardTimeout(timeouts.values[i], page.kbd.timeout_battery || 0)
                }
                QQC2.Label { text: Theme.tr("От батареи") }
                QQC2.ComboBox {
                    Layout.fillWidth: true
                    model: timeouts.names
                    currentIndex: timeouts.index(page.kbd.timeout_battery)
                    onActivated: i => backend.setKeyboardTimeout(page.kbd.timeout_ac || 0, timeouts.values[i])
                }
            }

            QQC2.Label { text: Theme.tr("Когда светиться"); opacity: 0.8 }
            GridLayout {
                columns: 2
                Layout.fillWidth: true
                Repeater {
                    model: [{ id: "awake", name: Theme.tr("При работе") }, { id: "boot", name: Theme.tr("При загрузке") },
                            { id: "sleep", name: Theme.tr("Во сне") }, { id: "shutdown", name: Theme.tr("При выключении") }]
                    QQC2.CheckBox {
                        required property var modelData
                        Layout.fillWidth: true
                        text: modelData.name
                        checked: !!page.kbd[modelData.id]
                        onToggled: {
                            const s = { awake: page.kbd.awake, boot: page.kbd.boot, sleep: page.kbd.sleep, shutdown: page.kbd.shutdown }
                            s[modelData.id] = checked
                            backend.setAuraPower(s.awake, s.boot, s.sleep, s.shutdown)
                        }
                    }
                }
            }
            QQC2.Button {
                Layout.alignment: Qt.AlignRight
                text: Theme.tr("Готово")
                onClicked: extraPopup.close()
            }
        }
    }
}
