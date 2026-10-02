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

    spacing: Kirigami.Units.largeSpacing * 1.5

    // ---------- режим ----------
    Section {
        title: "Режим"
        value: Theme.profileName(page.st.profile)
        iconName: "speedometer-symbolic"
        info: (page.st.cpu_temp != null ? "CPU " + Math.round(page.st.cpu_temp) + " °C" : "")
              + (page.fans.cpu == null ? "" : page.fans.cpu === 0 ? "  ·  вентилятор стоит" : "  ·  " + page.fans.cpu + " об/мин")

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
                text: "Вентиляторы"
                subtitle: "и мощность"
                iconName: Qt.resolvedUrl("icons/fan-symbolic.svg")
                onClicked: page.openFans()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            QQC2.Switch {
                id: autoProfile
                text: "Сам по питанию"
                checked: !!page.st.auto_profile
                onToggled: backend.setAutoProfile(checked)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: "Подключили зарядку или отключили — включается режим, который ты выбирал для этого питания"
            }
            Item { Layout.fillWidth: true }
            QQC2.Label {
                visible: autoProfile.checked
                text: "от сети: " + Theme.profileName(page.st.profile_on_ac) + "  ·  от батареи: " + Theme.profileName(page.st.profile_on_battery)
                font: Kirigami.Theme.smallFont
                opacity: 0.7
            }
        }
    }

    // ---------- видеокарта ----------
    Section {
        visible: !!page.gpu.supported
        title: "Видеокарта"
        value: page.gpu.auto_eco ? "Авто"
             : page.gpu.switching ? (page.gpu.target === "eco" ? "Eco" : "Стандарт")
             : page.gpu.state === "off" ? "Eco" : "Стандарт"
        iconName: Qt.resolvedUrl("icons/gpu-symbolic.svg")
        info: (page.gpu.auto_eco && !page.gpu.switching
               ? (page.gpu.state === "off" ? "видеокарта отключена (батарея)" : "видеокарта включена (зарядка)")
               : Theme.gpuInfo(page.gpu, page.nv))
              + (page.fans.gpu == null ? "" : page.fans.gpu === 0 ? "  ·  вентилятор стоит" : "  ·  " + page.fans.gpu + " об/мин")
        infoColor: page.gpu.state === "active" ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Tile {
                text: "Eco"
                subtitle: "NVIDIA выключена"
                iconName: "battery-profile-powersave-symbolic"
                accent: Theme.positive
                selected: !page.gpu.auto_eco && (page.gpu.switching ? page.gpu.target === "eco" : page.gpu.state === "off")
                busy: !!page.gpu.switching && page.gpu.target === "eco"
                enabled: !page.gpu.switching && !!page.gpu.mux_hybrid
                onClicked: (page.gpu.external || []).length ? displayWarning.open() : backend.setGpuMode("eco", false)
            }
            Tile {
                text: "Стандарт"
                subtitle: "iGPU + NVIDIA"
                iconName: "monitor-symbolic"
                accent: Theme.highlight
                selected: !page.gpu.auto_eco && (page.gpu.switching ? page.gpu.target === "standard" : page.gpu.state !== "off")
                busy: !!page.gpu.switching && page.gpu.target === "standard"
                enabled: !page.gpu.switching
                onClicked: backend.setGpuMode("standard", false)
            }
            Tile {
                text: "Авто"
                subtitle: "от сети вкл. · без сети выкл."
                iconName: "automated-tasks-symbolic"
                accent: Theme.neutral
                selected: !!page.gpu.auto_eco
                enabled: !page.gpu.switching && !!page.gpu.mux_hybrid
                onClicked: backend.setGpuAutoEco(true)
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: "Отключил зарядку — NVIDIA выключается (Eco), батарея живёт дольше.\nПодключил — NVIDIA включается для игр и тяжёлых программ."
            }
        }

        Kirigami.InlineMessage {
            Layout.fillWidth: true
            visible: !!page.gpu.error && !page.gpu.switching
            type: Kirigami.MessageType.Warning
            text: page.gpu.error || ""
            actions: [
                Kirigami.Action {
                    // только обычные программы пользователя — рабочий стол и систему закрывать нельзя
                    visible: !!page.gpu.can_force
                    text: "Закрыть их и выключить"
                    icon.name: "process-stop-symbolic"
                    onTriggered: backend.setGpuMode("eco", true)
                }
            ]
        }
        QQC2.Label {
            Layout.fillWidth: true
            visible: !page.gpu.error && (page.gpu.holders || []).length > 0
            text: "Держат NVIDIA: " + (page.gpu.holders || []).join(", ")
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            elide: Text.ElideRight
        }
    }

    // ---------- экран ----------
    Section {
        visible: (page.disp.rates || []).length > 1
        title: "Экран"
        value: page.disp.hz ? page.disp.hz + " Гц" + (page.toggles.panel_overdrive ? " + OD" : "") : ""
        iconName: "monitor-symbolic"
        info: backend.screenAuto && page.disp.rates ? "авто: " + page.disp.rates[0] + " на батарее, " + page.disp.rates[1] + " от сети" : ""

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Tile {
                compact: true
                text: "Авто"
                selected: backend.screenAuto
                onClicked: backend.setScreenAuto(true)
            }
            Repeater {
                model: page.disp.rates || []
                Tile {
                    required property int modelData
                    compact: true
                    text: modelData + " Гц"
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
                QQC2.ToolTip.text: "Разгон матрицы: быстрее отклик, меньше шлейфов в играх"
            }
        }
    }

    // ---------- клавиатура ----------
    Section {
        visible: !!page.st.keyboard
        title: "Клавиатура"
        value: page.kbd.rgb ? (Theme.auraModes.find(m => m.id === page.kbd.mode) || {}).name || "" : ""
        iconName: "input-keyboard-symbolic"
        info: page.kbd.brightness === 0 ? "подсветка выключена" : ""

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                // уровни яркости — сколько их у этой клавиатуры (обычно 0–3)
                model: page.kbd.max === 3 || page.kbd.max === undefined ? ["Выкл", "Низкая", "Средняя", "Высокая"]
                     : Array.from({ length: page.kbd.max + 1 }, (_, i) => i === 0 ? "Выкл" : String(i))
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
                    QQC2.Label { text: "Цвет" }
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
                text: "Ещё"
                icon.name: "settings-configure-symbolic"
                onClicked: extraPopup.open()
            }
        }
    }

    // ---------- Slash на крышке ----------
    Section {
        visible: !!page.sl.supported
        title: "Подсветка крышки"
        value: page.sl.brightness > 0 ? ((page.sl.modes || []).find(m => m.id === page.sl.mode) || {}).name || "" : "выключена"
        iconName: "computer-laptop-symbolic"

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: ["Выкл", "Тускло", "Средне", "Ярко"]
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
                text: "Ещё"
                icon.name: "settings-configure-symbolic"
                onClicked: slashPopup.open()
            }
        }
    }

    // ---------- батарея ----------
    Section {
        visible: page.bat.capacity !== undefined
        title: "Батарея"
        value: page.bat.capacity + "%"
        iconName: page.st.ac ? "battery-full-charging-symbolic" : "battery-good-symbolic"
        info: (page.bat.status === "Discharging" ? page.bat.power_w + " Вт" : page.st.ac ? "от сети" : "")
              + (page.bat.health ? "  ·  здоровье " + page.bat.health + "%" : "")

        RowLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.largeSpacing
            QQC2.Label { text: "Заряжать до" }
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
                QQC2.ToolTip.text: "Если ноутбук почти всегда от сети, 80% заметно продлят жизнь батареи"
            }
            QQC2.Label {
                text: Math.round(chargeSlider.value) + "%"
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                font.weight: Font.DemiBold
            }
        }

        QQC2.Button {
            Layout.fillWidth: true
            icon.name: "office-chart-line-forecast-symbolic"
            text: "Графики: температура, вентиляторы, расход и заряд батареи"
            onClicked: page.openMonitor()
        }
    }

    // ---------- низ ----------
    RowLayout {
        Layout.fillWidth: true
        QQC2.Switch {
            visible: page.toggles.boot_sound !== undefined
            text: "Звук при включении"
            checked: !!page.toggles.boot_sound
            onToggled: backend.setToggle("boot_sound", checked)
        }
        Item { Layout.fillWidth: true }
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
                Kirigami.Heading { level: 4; text: "Подключён внешний монитор"; Layout.fillWidth: true; wrapMode: Text.Wrap }
            }
            QQC2.Label {
                Layout.fillWidth: true
                wrapMode: Text.Wrap
                text: "Монитор (" + (page.gpu.external || []).join(", ") + ") подключён к видеокарте NVIDIA. "
                      + "Если её выключить, он погаснет — изображение останется только на экране ноутбука."
            }
            RowLayout {
                Layout.alignment: Qt.AlignRight
                QQC2.Button { text: "Отмена"; onClicked: displayWarning.close() }
                QQC2.Button {
                    text: "Всё равно выключить"
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
            Kirigami.Heading { level: 4; text: "Цвет подсветки" }
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
                text: "Свой цвет…"
                icon.name: "color-picker-symbolic"
                onClicked: { colorPopup.close(); colorDialog.selectedColor = page.kbd.color; colorDialog.open() }
            }
        }
    }

    ColorDialog {
        id: colorDialog
        title: "Цвет подсветки"
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
            Kirigami.Heading { level: 4; text: "Подсветка крышки" }
            RowLayout {
                QQC2.Label { text: "Пауза между повторами"; Layout.fillWidth: true }
                QQC2.Label { text: intervalSlider.value + " с"; font.weight: Font.DemiBold }
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
                text: "Светиться на батарее"
                checked: !!page.sl.on_battery
                onToggled: backend.setSlashOptions(checked, !!page.sl.lid_closed)
            }
            QQC2.Switch {
                text: "Светиться с закрытой крышкой"
                checked: !!page.sl.lid_closed
                onToggled: backend.setSlashOptions(!!page.sl.on_battery, checked)
            }
            QQC2.Button {
                Layout.alignment: Qt.AlignRight
                text: "Готово"
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
            Kirigami.Heading { level: 4; text: "Подсветка клавиатуры" }

            QQC2.Label { text: "Скорость эффекта"; opacity: 0.8; visible: page.kbd.mode !== "static" }
            RowLayout {
                visible: page.kbd.mode !== "static"
                spacing: Kirigami.Units.smallSpacing
                Repeater {
                    model: [{ id: "slow", name: "Медленно" }, { id: "normal", name: "Обычно" }, { id: "fast", name: "Быстро" }]
                    Tile {
                        required property var modelData
                        compact: true
                        text: modelData.name
                        selected: page.kbd.speed === modelData.id
                        onClicked: backend.setAura(page.kbd.mode, page.kbd.color, page.kbd.color2, modelData.id)
                    }
                }
            }

            QQC2.Label { text: "Когда светиться"; opacity: 0.8 }
            GridLayout {
                columns: 2
                Layout.fillWidth: true
                Repeater {
                    model: [{ id: "awake", name: "При работе" }, { id: "boot", name: "При загрузке" },
                            { id: "sleep", name: "Во сне" }, { id: "shutdown", name: "При выключении" }]
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
                text: "Готово"
                onClicked: extraPopup.close()
            }
        }
    }
}
