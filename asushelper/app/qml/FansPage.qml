// Вентиляторы и мощность для каждого режима: кривые CPU/GPU, лимиты мощности, EPP.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: page

    signal back()

    readonly property var st: backend.state || {}
    readonly property var cfg: backend.config || {}
    property string profile: st.profile || "balanced"
    readonly property var pcfg: (cfg.profiles || {})[profile] || {}
    readonly property bool isCurrent: profile === st.profile
    // заводские кривые, полученные у BIOS за этот запуск: {profile: {cpu, gpu}}
    property var factory: ({})

    readonly property var powerNames: ({
        ppt_pl1_spl: [Theme.tr("Процессор, долго"), Theme.tr("PL1 — сколько CPU берёт под длительной нагрузкой"), Theme.tr(" Вт")],
        ppt_pl2_sppt: [Theme.tr("Процессор, рывком"), Theme.tr("PL2 — короткий разгон на несколько секунд"), Theme.tr(" Вт")],
        ppt_fppt: [Theme.tr("Процессор, пик"), Theme.tr("fPPT — самые короткие всплески"), Theme.tr(" Вт")],
        ppt_pl3_fppt: [Theme.tr("Процессор, пик"), Theme.tr("PL3/fPPT — самые короткие всплески"), Theme.tr(" Вт")],
        ppt_apu_sppt: [Theme.tr("Процессор (APU), рывком"), Theme.tr("sPPT встроенного графического ядра AMD"), Theme.tr(" Вт")],
        ppt_platform_sppt: [Theme.tr("Вся платформа, рывком"), Theme.tr("общий лимит процессора и видеокарты"), Theme.tr(" Вт")],
        nv_base_tgp: [Theme.tr("NVIDIA, базовая мощность"), Theme.tr("базовый TGP видеокарты"), Theme.tr(" Вт")],
        nv_dynamic_boost: ["NVIDIA Dynamic Boost", Theme.tr("сколько ватт CPU может отдать видеокарте"), Theme.tr(" Вт")],
        nv_temp_target: [Theme.tr("NVIDIA, предел температуры"), Theme.tr("выше — карта замедляется"), " °C"],
        nv_tgp: ["NVIDIA TGP", Theme.tr("мощность видеокарты"), Theme.tr(" Вт")],
    })

    spacing: Kirigami.Units.largeSpacing

    Connections {
        target: backend
        function onFactoryCurves(r) {
            const f = Object.assign({}, page.factory)
            f[r.profile] = r.curves
            page.factory = f
            page.factoryLoaded()
        }
    }

    RowLayout {
        Layout.fillWidth: true
        QQC2.ToolButton {
            icon.name: "go-previous"
            text: Theme.tr("Назад")
            display: QQC2.AbstractButton.IconOnly
            onClicked: page.back()
            QQC2.ToolTip.visible: hovered
            QQC2.ToolTip.text: text
        }
        Kirigami.Heading { level: 3; text: Theme.tr("Вентиляторы и мощность"); Layout.fillWidth: true }
    }

    // ---------- выбор режима ----------
    RowLayout {
        spacing: Kirigami.Units.smallSpacing
        Repeater {
            model: Theme.profiles
            Tile {
                required property var modelData
                text: modelData.name
                subtitle: page.st.profile === modelData.id ? Theme.tr("сейчас") : ""
                iconName: modelData.icon
                accent: Theme.profileColor(modelData.id)
                selected: page.profile === modelData.id
                onClicked: page.profile = modelData.id
            }
        }
    }
    QQC2.Label {
        Layout.fillWidth: true
        visible: !page.isCurrent
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: Theme.tr("Настройки сохранятся и включатся, когда будет включён режим «%1»").arg(Theme.profileName(page.profile))
    }

    // ---------- кривые ----------
    Repeater {
        // вентиляторы, которым этот ноутбук позволяет задать кривую
        model: Object.keys(page.st.fan_curves || {}).map(f => ({
            fan: f, name: ({ cpu: Theme.tr("Вентилятор процессора"), gpu: Theme.tr("Вентилятор видеокарты"), mid: Theme.tr("Средний вентилятор") })[f] || f }))
        delegate: Section {
            id: fanSection
            required property var modelData
            readonly property string fan: modelData.fan
            readonly property var saved: (page.pcfg.fan_curves || {})[fan] || null
            readonly property var factoryCurve: ((page.factory[page.profile] || {})[fan])
                || (((page.cfg.factory_curves || {})[page.profile] || {})[fan]) || null
            readonly property real rpm: (page.st.fans || {})[fan] || 0
            property bool dirty: false

            title: modelData.name
            iconName: "temperature-normal-symbolic"
            info: page.isCurrent && rpm ? rpm + Theme.tr(" об/мин") : ""


            QQC2.Switch {
                id: custom
                text: Theme.tr("Своя кривая")
                checked: fanSection.saved !== null
                // начинать свою кривую можно только с известной (своей или заводской)
                enabled: fanSection.saved !== null || fanSection.factoryCurve !== null
                onToggled: {
                    if (!checked) { backend.resetFanCurve(page.profile, fanSection.fan); fanSection.dirty = false }
                    else fanSection.dirty = true
                }
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.text: Theme.tr("Выключено — вентилятором управляет BIOS по своей заводской кривой")
            }

            QQC2.Label {
                Layout.fillWidth: true
                visible: !editor.known
                wrapMode: Text.Wrap
                opacity: 0.7
                text: Theme.tr("Заводская кривая режима «%1» ещё неизвестна — ").arg(Theme.profileName(page.profile))
                      + Theme.tr("она появится, когда этот режим хотя бы раз будет включён")
            }

            FanCurve {
                id: editor
                property bool known: true
                visible: known
                Layout.fillWidth: true
                editable: custom.checked
                accent: Theme.profileColor(page.profile)
                currentTemp: !page.isCurrent ? NaN
                    : fanSection.fan !== "gpu" ? (page.st.cpu_temp || NaN)
                    : (backend.nvidia && backend.nvidia.temp !== undefined ? backend.nvidia.temp : NaN)
                onEdited: fanSection.dirty = true

                // своя кривая этого режима, иначе его заводская (из BIOS); чужих точек не показываем
                function load() {
                    const c = fanSection.saved || fanSection.factoryCurve
                    known = !!c
                    if (c) { temp = c.temp.slice(); pwm = c.pwm.slice() }
                    fanSection.dirty = false
                }
                function loadFactory() {
                    const c = (page.factory[page.profile] || {})[fanSection.fan]
                    if (c) { temp = c.temp.slice(); pwm = c.pwm.slice(); fanSection.dirty = custom.checked }
                }
                Connections {
                    target: page
                    function onFactoryLoaded() { editor.loadFactory() }
                    function onProfileChanged() { editor.load() }
                    function onPcfgChanged() { if (!fanSection.dirty) editor.load() }
                    function onCfgChanged() { if (!fanSection.dirty) editor.load() }
                }
                Component.onCompleted: load()
            }

            RowLayout {
                Layout.fillWidth: true
                QQC2.Button {
                    text: Theme.tr("Заводская")
                    icon.name: "edit-undo"
                    enabled: page.isCurrent
                    onClicked: backend.requestFactoryCurves()
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.text: page.isCurrent ? Theme.tr("Загрузить кривую BIOS для этого режима как отправную точку")
                                                      : Theme.tr("BIOS отдаёт заводскую кривую только для включённого режима")
                }
                Item { Layout.fillWidth: true }
                QQC2.Button {
                    text: Theme.tr("Применить")
                    icon.name: "dialog-ok-apply"
                    highlighted: fanSection.dirty
                    enabled: fanSection.dirty && custom.checked
                    onClicked: {
                        backend.setFanCurve(page.profile, fanSection.fan, editor.temp, editor.pwm)
                        fanSection.dirty = false
                    }
                }
            }
        }
    }

    Kirigami.Separator { Layout.fillWidth: true }

    // ---------- мощность ----------
    Section {
        title: Theme.tr("Мощность")
        iconName: "cpu"
        info: page.st.ac ? Theme.tr("от сети") : Theme.tr("на батарее — пределы ниже")

        Repeater {
            model: Object.keys(page.st.power_limits || {}).filter(a => {
                const l = page.st.power_limits[a]
                return l.min !== null && l.max !== null && l.max > l.min
            })
            delegate: ColumnLayout {
                id: limit
                required property string modelData
                readonly property var info: page.st.power_limits[modelData]
                readonly property var names: page.powerNames[modelData] || [modelData, "", ""]
                readonly property var mine: (page.pcfg.power_limits || {})[modelData]
                Layout.fillWidth: true
                spacing: 0

                RowLayout {
                    Layout.fillWidth: true
                    QQC2.Label { text: limit.names[0]; Layout.fillWidth: true }
                    QQC2.Label {
                        text: Math.round(slider.value) + limit.names[2] + (limit.mine === undefined ? "  (BIOS)" : "")
                        font.weight: Font.DemiBold
                    }
                }
                QQC2.Slider {
                    id: slider
                    Layout.fillWidth: true
                    from: limit.info.min
                    to: limit.info.max
                    stepSize: 1
                    snapMode: QQC2.Slider.SnapAlways
                    value: limit.mine !== undefined ? limit.mine
                         : page.isCurrent ? limit.info.value : (limit.info.default || limit.info.max)
                    onPressedChanged: if (!pressed) backend.setPowerLimit(page.profile, limit.modelData, Math.round(value))
                }
                QQC2.Label {
                    text: limit.names[1] + "  ·  " + limit.info.min + "–" + limit.info.max + limit.names[2]
                    font: Kirigami.Theme.smallFont
                    opacity: 0.6
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: page.st.cpu_boost !== null && page.st.cpu_boost !== undefined
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                QQC2.Label { text: Theme.tr("Turbo Boost процессора") }
                QQC2.Label {
                    text: Theme.tr("выключен — холоднее и тише, но медленнее в тяжёлых задачах")
                    font: Kirigami.Theme.smallFont
                    opacity: 0.6
                }
            }
            QQC2.Switch {
                readonly property var mine: page.pcfg.cpu_boost
                checked: mine === null || mine === undefined ? page.profile !== "quiet" : mine
                onToggled: backend.setCpuBoost(page.profile, checked)
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: (page.st.epp_choices || []).length > 0     // процессор поддерживает EPP
            QQC2.Label { text: Theme.tr("Энергосбережение CPU (EPP)"); Layout.fillWidth: true }
            QQC2.ComboBox {
                id: epp
                readonly property var choices: ["", ...(page.st.epp_choices || []).filter(c => c !== "default")]
                model: choices.map(c => c === "" ? Theme.tr("по режиму") : c)
                currentIndex: Math.max(0, choices.indexOf(page.pcfg.epp || ""))
                onActivated: i => backend.setEpp(page.profile, choices[i])
            }
        }

        QQC2.Button {
            text: Theme.tr("Мощность — как в BIOS")
            icon.name: "edit-undo"
            enabled: Object.keys(page.pcfg.power_limits || {}).length > 0
            onClicked: backend.resetPowerLimits(page.profile)
        }
    }

    signal factoryLoaded()
}
