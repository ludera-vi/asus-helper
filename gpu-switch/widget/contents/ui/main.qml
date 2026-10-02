import QtQuick
import QtQuick.Layouts
import org.kde.plasma.plasmoid
import org.kde.plasma.components as PlasmaComponents
import org.kde.plasma.plasma5support as P5Support
import org.kde.kirigami as Kirigami

PlasmoidItem {
    id: root

    readonly property string script: "/usr/local/bin/gpu-eco"
    // Дешёвая проверка: два системных файла через cat (~3 мс), без запуска gpu-eco (~40 мс).
    // Первая строка — флаг BIOS (1 = выключена), вторая — состояние карты, если драйвер её держит.
    readonly property string stateCmd: "sh -c 'cat /sys/class/firmware-attributes/asus-armoury/attributes/dgpu_disable/current_value 2>/dev/null"
        + " || cat /sys/devices/platform/asus-nb-wmi/dgpu_disable;"
        + " cat /sys/bus/pci/drivers/nvidia/0000:*/power/runtime_status 2>/dev/null || echo missing'"
    readonly property string whoCmd: script + " who"
    // Опрашивается только когда карта уже работает и окошко открыто — иначе сам опрос будил бы её
    readonly property string smiCmd: "nvidia-smi --query-gpu=utilization.gpu,power.draw,memory.used --format=csv,noheader,nounits"
    // Режимы экрана — через KDE (без root, NVIDIA не трогает)
    readonly property string screenCmd: "kscreen-doctor -j"

    // off | suspended | active | missing | unknown
    property string gpuState: "unknown"
    property string users: ""
    property string load: ""
    property bool switching: false
    property string lastOutput: ""
    // Встроенный экран: имя выхода, текущая частота и id режимов с тем же разрешением
    property string screenOutput: ""
    property int screenHz: 0
    property int lowHz: 0
    property int highHz: 0
    property string lowModeId: ""
    property string highModeId: ""
    property bool screenSwitching: false

    readonly property bool isOff: gpuState === "off"
    readonly property bool isActive: gpuState === "active"
    readonly property bool needsForce: lastOutput.indexOf("--force") !== -1
    readonly property bool canSwitchHz: screenOutput !== "" && highHz - lowHz > 1
    readonly property bool isLowHz: canSwitchHz && screenHz <= lowHz
    readonly property string usersText: users.split("\n").filter(s => s).join(", ")

    readonly property string stateText: {
        switch (gpuState) {
        case "off":       return "Выключена (Eco)"
        case "suspended": return "Включена, спит"
        case "active":    return "Работает"
        case "missing":   return "Включена, но драйвер не загружен"
        default:          return "Неизвестно"
        }
    }

    readonly property color stateColor: {
        switch (gpuState) {
        case "off":       return Kirigami.Theme.disabledTextColor
        case "suspended": return Kirigami.Theme.positiveTextColor
        case "active":    return Kirigami.Theme.neutralTextColor
        default:          return Kirigami.Theme.negativeTextColor
        }
    }

    Plasmoid.icon: "video-display"
    toolTipMainText: "NVIDIA: " + (switching ? "переключение…" : stateText)
    toolTipSubText: [usersText ? "Используют: " + usersText
                               : isActive ? "Разбудила система или драйвер" : "",
                     screenHz ? "Экран: " + screenHz + " Гц" : ""].filter(s => s).join("\n")

    P5Support.DataSource {
        id: executable
        engine: "executable"
        connectedSources: []
        onNewData: (source, data) => {
            const out = (data["stdout"] + data["stderr"]).trim()
            disconnectSource(source)
            if (source === root.stateCmd) {
                const lines = out.split("\n")
                root.gpuState = lines[0] === "1" ? "off" : (lines[1] || "unknown")
                if (root.isOff) { root.users = ""; root.load = "" }
            } else if (source === root.whoCmd) {
                root.users = out
            } else if (source === root.screenCmd) {
                root.parseScreen(data["stdout"])
            } else if (source.indexOf("kscreen-doctor output.") === 0) {
                root.screenSwitching = false
                executable.connectSource(root.screenCmd)
            } else if (source === root.smiCmd) {
                const v = out.split(",").map(s => s.trim())
                root.load = v.length === 3 ? "Нагрузка " + v[0] + "%  ·  " + Math.round(v[1]) + " Вт  ·  " + v[2] + " МБ" : ""
            } else if (source.indexOf("notify-send") !== 0) {
                root.switching = false
                root.lastOutput = out
                root.notify(out.split("\n").pop())
                root.poll()
            }
        }
    }

    // Постоянно — только дешёвая проверка состояния. «Кто использует» и нагрузка —
    // только пока открыто окошко или курсор на значке.
    function poll() {
        executable.connectSource(stateCmd)
        if (expanded) pollDetails()
        else load = ""
    }

    function pollDetails() {
        if (!screenSwitching) executable.connectSource(screenCmd)
        if (!isOff) executable.connectSource(whoCmd)
        if (isActive && expanded) executable.connectSource(smiCmd)
    }

    onExpandedChanged: if (expanded) poll()

    // Встроенный экран (Panel / eDP), иначе первый включённый. Пара частот — минимальная
    // (около 60) и максимальная среди режимов с текущим разрешением.
    function parseScreen(json) {
        let outputs = []
        try { outputs = JSON.parse(json).outputs.filter(o => o.enabled) } catch (e) {}
        const out = outputs.find(o => o.type === 7 || o.name.indexOf("eDP") === 0) || outputs[0]
        const cur = out && out.modes.find(m => m.id === out.currentModeId)
        if (!cur) { screenOutput = ""; screenHz = 0; return }
        const same = out.modes.filter(m => m.size.width === cur.size.width && m.size.height === cur.size.height)
        const low = same.reduce((a, m) => m.refreshRate < a.refreshRate ? m : a)
        const high = same.reduce((a, m) => m.refreshRate > a.refreshRate ? m : a)
        screenOutput = out.name
        screenHz = Math.round(cur.refreshRate)
        lowHz = Math.round(low.refreshRate);   lowModeId = low.id
        highHz = Math.round(high.refreshRate); highModeId = high.id
    }

    function toggleHz() {
        screenSwitching = true
        executable.connectSource("kscreen-doctor output." + screenOutput + ".mode."
                                 + (isLowHz ? highModeId : lowModeId) + " 2>&1")
    }

    function notify(text) {
        executable.connectSource("notify-send -a 'NVIDIA Eco' -i video-display NVIDIA '"
                                 + text.replace(/'/g, "") + "'")
    }

    function run(args) {
        switching = true
        lastOutput = ""
        executable.connectSource("sudo -n " + script + " " + args + " 2>&1")
    }

    Timer {
        interval: 5000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: root.poll()
    }

    // Плашка «GPU». mono — цвета текста, как остальные значки панели (на панели);
    // иначе — цвет состояния (в окошке). Выключена: бледная и перечёркнутая, спит: контур,
    // работает: залита и пульсирует.
    component Badge: Item {
        id: badge
        property bool mono: false
        property real chipHeight: 0   // 0 — по размеру места
        readonly property color ink: mono ? Kirigami.Theme.textColor : root.stateColor

        Rectangle {
            id: chip
            anchors.centerIn: parent
            height: badge.chipHeight > 0 ? badge.chipHeight
                    : Math.min(parent.height, parent.width / 1.9) * 0.8
            width: height * 1.9
            radius: height * 0.25
            color: root.isActive ? badge.ink : "transparent"
            border.color: badge.ink
            border.width: Math.max(1, Math.round(height * 0.09))
            opacity: root.switching ? 0.4 : (root.isOff && badge.mono ? 0.45 : 1)

            SequentialAnimation on opacity {
                running: root.isActive && !root.switching
                loops: Animation.Infinite
                alwaysRunToEnd: true
                NumberAnimation { to: 0.55; duration: 900; easing.type: Easing.InOutSine }
                NumberAnimation { to: 1; duration: 900; easing.type: Easing.InOutSine }
            }

            Text {
                anchors.centerIn: parent
                text: "GPU"
                font.bold: true
                font.pixelSize: chip.height * 0.55
                color: root.isActive ? Kirigami.Theme.backgroundColor : badge.ink
            }

            Rectangle {
                visible: root.isOff
                anchors.centerIn: parent
                width: chip.width * 1.05
                height: chip.border.width
                rotation: -30
                color: badge.ink
            }
        }
    }

    compactRepresentation: MouseArea {
        Layout.minimumWidth: Kirigami.Units.iconSizes.small * 1.9
        Layout.minimumHeight: Kirigami.Units.iconSizes.small
        hoverEnabled: true
        onEntered: root.pollDetails()  // для подсказки «Используют: …»
        onClicked: root.expanded = !root.expanded
        // размер — как у значков трея
        Badge { anchors.fill: parent; mono: true; chipHeight: Kirigami.Units.iconSizes.small }
    }

    fullRepresentation: ColumnLayout {
        Layout.preferredWidth: Kirigami.Units.gridUnit * 17
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            spacing: Kirigami.Units.largeSpacing
            Badge {
                Layout.preferredWidth: Kirigami.Units.iconSizes.large
                Layout.preferredHeight: Kirigami.Units.iconSizes.medium
            }
            ColumnLayout {
                spacing: 0
                Kirigami.Heading {
                    level: 3
                    text: "NVIDIA: " + root.stateText
                }
                PlasmaComponents.Label {
                    visible: root.load !== ""
                    text: root.load
                    font: Kirigami.Theme.smallFont
                }
            }
        }

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: !root.isOff
            wrapMode: Text.Wrap
            text: root.usersText ? "Используют: " + root.usersText
                : root.isActive ? "Программ на NVIDIA нет — разбудила система или драйвер"
                : "Программ на NVIDIA нет"
        }

        PlasmaComponents.Button {
            Layout.fillWidth: true
            enabled: !root.switching
            icon.name: root.isOff ? "media-playback-start" : "system-shutdown"
            text: root.isOff ? "Включить NVIDIA (гибрид)" : "Выключить NVIDIA (Eco)"
            onClicked: root.run(root.isOff ? "on" : "off")
        }

        PlasmaComponents.Button {
            Layout.fillWidth: true
            visible: root.needsForce && !root.switching
            icon.name: "process-stop"
            text: "Закрыть эти программы и выключить"
            onClicked: root.run("off --force")
        }

        Kirigami.Separator {
            Layout.fillWidth: true
            visible: root.canSwitchHz
        }

        RowLayout {
            Layout.fillWidth: true
            visible: root.canSwitchHz
            PlasmaComponents.Label {
                Layout.fillWidth: true
                text: "Экран: " + root.screenHz + " Гц"
            }
            PlasmaComponents.Button {
                enabled: !root.screenSwitching
                icon.name: "video-display"
                text: "Переключить на " + (root.isLowHz ? root.highHz : root.lowHz) + " Гц"
                onClicked: root.toggleHz()
            }
        }

        PlasmaComponents.BusyIndicator {
            Layout.alignment: Qt.AlignHCenter
            visible: root.switching
            running: visible
        }

        PlasmaComponents.Label {
            Layout.fillWidth: true
            visible: text !== ""
            text: root.lastOutput
            wrapMode: Text.Wrap
            font: Kirigami.Theme.smallFont
            opacity: 0.8
        }
    }
}
