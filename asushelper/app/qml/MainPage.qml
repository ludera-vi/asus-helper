// Главная страница: режим, видеокарта, экран, клавиатура, батарея — всё на одном экране, как в G-Helper.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import QtQuick.Dialogs
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: page

    signal openFans()

    readonly property var st: backend.state || {}
    readonly property var gpu: st.gpu || {}
    readonly property var kbd: st.keyboard || {}
    readonly property var bat: st.battery || {}
    readonly property var disp: backend.display || {}
    readonly property var nv: backend.nvidia || {}

    spacing: Kirigami.Units.largeSpacing

    // ---------- режим ----------
    Section {
        title: "Режим"
        iconName: "speedometer"
        info: (page.st.cpu_temp !== undefined && page.st.cpu_temp !== null ? Math.round(page.st.cpu_temp) + " °C" : "")
              + (page.st.fans ? "  ·  " + page.st.fans.cpu + " / " + page.st.fans.gpu + " об/мин" : "")

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: Theme.profiles
                Tile {
                    required property var modelData
                    text: modelData.name
                    subtitle: modelData.hint
                    iconName: modelData.icon
                    accent: Theme.profileColor(modelData.id)
                    selected: page.st.profile === modelData.id
                    onClicked: backend.setProfile(modelData.id)
                }
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
                QQC2.ToolTip.text: "При подключении зарядки и от батареи включать режим, выбранный для этого питания"
            }
            QQC2.Label {
                Layout.fillWidth: true
                visible: autoProfile.checked
                text: "сеть: " + Theme.profileName(page.st.profile_on_ac) + " · батарея: " + Theme.profileName(page.st.profile_on_battery)
                font: Kirigami.Theme.smallFont
                opacity: 0.7
                elide: Text.ElideRight
            }
        }

        QQC2.Button {
            Layout.fillWidth: true
            text: "Вентиляторы и мощность"
            icon.name: "go-next"
            LayoutMirroring.enabled: true     // стрелка справа
            onClicked: page.openFans()
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    // ---------- видеокарта ----------
    Section {
        visible: !!page.gpu.supported
        title: "Видеокарта"
        iconName: "video-display"
        info: Theme.gpuInfo(page.gpu, page.nv)
        infoColor: page.gpu.state === "active" ? Kirigami.Theme.neutralTextColor : Kirigami.Theme.textColor

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Tile {
                text: "Eco"
                subtitle: "NVIDIA выключена"
                iconName: "battery-profile-powersave"
                accent: Kirigami.Theme.positiveTextColor
                selected: !page.gpu.auto_eco && page.gpu.state === "off"
                busy: page.gpu.switching && page.gpu.state !== "off"
                enabled: !page.gpu.switching && page.gpu.mux_hybrid
                onClicked: backend.setGpuMode("eco", false)
            }
            Tile {
                text: "Стандарт"
                subtitle: "гибрид"
                iconName: "video-display"
                accent: Kirigami.Theme.highlightColor
                selected: !page.gpu.auto_eco && page.gpu.state !== "off"
                busy: page.gpu.switching && page.gpu.state === "off"
                enabled: !page.gpu.switching
                onClicked: backend.setGpuMode("standard", false)
            }
            Tile {
                text: "Оптимальный"
                subtitle: "Eco на батарее"
                iconName: "battery-good"
                accent: Kirigami.Theme.neutralTextColor
                selected: !!page.gpu.auto_eco
                enabled: !page.gpu.switching && page.gpu.mux_hybrid
                onClicked: backend.setGpuAutoEco(true)
            }
        }

        QQC2.Label {
            Layout.fillWidth: true
            visible: text !== ""
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            color: page.gpu.error ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.textColor
            opacity: page.gpu.error ? 1 : 0.7
            text: page.gpu.error ? page.gpu.error
                : page.gpu.holders && page.gpu.holders.length ? "Используют: " + page.gpu.holders.join(", ")
                : ""
        }
        QQC2.Button {
            Layout.fillWidth: true
            visible: !!page.gpu.error && page.gpu.error.indexOf("используют") !== -1 && !page.gpu.switching
            text: "Закрыть эти программы и выключить"
            icon.name: "process-stop"
            onClicked: backend.setGpuMode("eco", true)
        }
    }

    Kirigami.Separator { Layout.fillWidth: true; visible: !!page.gpu.supported }

    // ---------- экран ----------
    Section {
        visible: (page.disp.rates || []).length > 1
        title: "Экран"
        iconName: "preferences-desktop-display"
        info: page.disp.hz ? page.disp.hz + " Гц" : ""

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: page.disp.rates || []
                Tile {
                    required property int modelData
                    required property int index
                    text: modelData + " Гц"
                    subtitle: index === 0 ? "экономнее" : "плавнее"
                    selected: page.disp.hz === modelData
                    onClicked: backend.setRefreshRate(modelData)
                }
            }
        }
        QQC2.Switch {
            visible: page.st.toggles && page.st.toggles.panel_overdrive !== undefined
            text: "Overdrive (быстрее отклик матрицы)"
            checked: !!(page.st.toggles && page.st.toggles.panel_overdrive)
            onToggled: backend.setToggle("panel_overdrive", checked)
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    // ---------- клавиатура ----------
    Section {
        visible: page.kbd.mode !== undefined
        title: "Подсветка клавиатуры"
        iconName: "input-keyboard-brightness"

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: ["Выкл", "Низкая", "Средняя", "Высокая"]
                Tile {
                    required property string modelData
                    required property int index
                    text: modelData
                    selected: page.kbd.brightness === index
                    onClicked: backend.setKeyboardBrightness(index)
                }
            }
        }

        RowLayout {
            spacing: Kirigami.Units.smallSpacing
            Repeater {
                model: Theme.auraModes
                Tile {
                    required property var modelData
                    text: modelData.name
                    selected: page.kbd.mode === modelData.id
                    accent: page.kbd.color || Kirigami.Theme.highlightColor
                    onClicked: backend.setAura(modelData.id, page.kbd.color, page.kbd.color2, page.kbd.speed)
                }
            }
        }

        // цвета: готовые + свой
        Flow {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            visible: page.kbd.mode !== "cycle"
            Repeater {
                model: Theme.swatches.concat(Theme.swatches.indexOf(page.kbd.color) === -1 && page.kbd.color ? [page.kbd.color] : [])
                ColorSwatch {
                    required property string modelData
                    color: modelData
                    selected: page.kbd.color === modelData
                    onClicked: backend.setAura(page.kbd.mode, modelData, page.kbd.color2, page.kbd.speed)
                }
            }
            QQC2.ToolButton {
                icon.name: "color-picker"
                text: "Свой цвет"
                display: QQC2.AbstractButton.IconOnly
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.text: text
                onClicked: { colorDialog.selectedColor = page.kbd.color; colorDialog.open() }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: page.kbd.mode !== "static"
            QQC2.Label { text: "Скорость"; opacity: 0.8 }
            Repeater {
                model: [{ id: "slow", name: "Медленно" }, { id: "normal", name: "Обычно" }, { id: "fast", name: "Быстро" }]
                QQC2.Button {
                    required property var modelData
                    Layout.fillWidth: true
                    text: modelData.name
                    checkable: true
                    checked: page.kbd.speed === modelData.id
                    onClicked: backend.setAura(page.kbd.mode, page.kbd.color, page.kbd.color2, modelData.id)
                }
            }
        }

        Kirigami.LinkButton {
            text: lightStates.visible ? "Скрыть: когда светиться" : "Когда светиться…"
            onClicked: lightStates.visible = !lightStates.visible
        }
        GridLayout {
            id: lightStates
            visible: false
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
    }

    Kirigami.Separator { Layout.fillWidth: true }

    // ---------- батарея ----------
    Section {
        visible: page.bat.capacity !== undefined
        title: "Батарея"
        iconName: page.st.ac ? "battery-full-charging" : "battery-good"
        info: page.bat.capacity + "%"
              + (page.bat.status === "Discharging" ? "  ·  " + page.bat.power_w + " Вт" : page.st.ac ? "  ·  от сети" : "")
              + (page.bat.health ? "  ·  здоровье " + page.bat.health + "%" : "")

        RowLayout {
            Layout.fillWidth: true
            QQC2.Label { text: "Заряжать до" }
            QQC2.Slider {
                id: chargeSlider
                Layout.fillWidth: true
                from: 60; to: 100; stepSize: 5
                snapMode: QQC2.Slider.SnapAlways
                value: page.bat.charge_limit || 100
                onPressedChanged: if (!pressed && value !== page.bat.charge_limit) backend.setChargeLimit(value)
                Keys.onReleased: if (value !== page.bat.charge_limit) backend.setChargeLimit(value)
            }
            QQC2.Label {
                text: Math.round(chargeSlider.value) + "%"
                Layout.minimumWidth: Kirigami.Units.gridUnit * 2
                horizontalAlignment: Text.AlignRight
                font.weight: Font.DemiBold
            }
        }
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            text: "Если ноутбук почти всегда от сети, 80% заметно продлят жизнь батареи"
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    QQC2.Switch {
        visible: page.st.toggles && page.st.toggles.boot_sound !== undefined
        text: "Звук при включении"
        checked: !!(page.st.toggles && page.st.toggles.boot_sound)
        onToggled: backend.setToggle("boot_sound", checked)
    }

    ColorDialog {
        id: colorDialog
        title: "Цвет подсветки"
        onAccepted: backend.setAura(page.kbd.mode === "cycle" ? "static" : page.kbd.mode,
                                    selectedColor.toString().toUpperCase(), page.kbd.color2, page.kbd.speed)
    }
}
