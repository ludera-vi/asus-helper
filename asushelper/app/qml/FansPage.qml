// Вентиляторы и мощность для каждого режима: кривые CPU/GPU, лимиты мощности, EPP.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: page

    signal back()
    signal openPower(string profile)

    readonly property var st: backend.state || {}
    readonly property var cfg: backend.config || {}
    property string profile: st.profile || "balanced"
    readonly property var pcfg: (cfg.profiles || {})[profile] || {}
    readonly property bool isCurrent: profile === st.profile
    // заводские кривые, полученные у BIOS за этот запуск: {profile: {cpu, gpu}}
    property var factory: ({})

    // есть ли что показать на странице «Мощность и процессор»
    readonly property bool hasPower: Object.keys(st.power_limits || {}).some(a => {
            const l = st.power_limits[a]; return l.min !== null && l.max !== null && l.max > l.min })
        || (st.cpu_boost !== null && st.cpu_boost !== undefined) || (st.epp_choices || []).length > 0

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
            // своя тема: значок цветом текста (без этого после смены светлой/тёмной темы noctalia он остаётся старым)
            Binding on icon.color { value: Kirigami.Theme.textColor; when: Theme.original }
            text: Theme.tr("Назад")
            display: QQC2.AbstractButton.IconOnly
            onClicked: page.back()
            QQC2.ToolTip.visible: hovered
            QQC2.ToolTip.text: text
        }
        Kirigami.Heading { level: 3; text: Theme.tr("Вентиляторы и мощность"); Layout.fillWidth: true }
    }

    // ---------- выбор режима ----------
    ProfileTabs {
        profile: page.profile
        onProfileChanged: page.profile = profile
    }

    // мощность и процессор — отдельной страницей
    QQC2.ItemDelegate {
        Layout.fillWidth: true
        visible: page.hasPower
        onClicked: page.openPower(page.profile)
        contentItem: RowLayout {
            spacing: Kirigami.Units.largeSpacing
            Kirigami.Icon { source: "cpu"; implicitWidth: Kirigami.Units.iconSizes.smallMedium; implicitHeight: implicitWidth }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                QQC2.Label { text: Theme.tr("Мощность и процессор"); font.weight: Font.DemiBold }
                QQC2.Label {
                    Layout.fillWidth: true
                    text: Theme.tr("лимиты мощности, Turbo Boost, энергосбережение")
                    font: Theme.smallFont
                    opacity: 0.6
                    elide: Text.ElideRight
                }
            }
            Kirigami.Icon { source: "go-next-symbolic"; implicitWidth: Kirigami.Units.iconSizes.small; implicitHeight: implicitWidth }
        }
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
                AppButton {
                    text: Theme.tr("Заводская")
                    icon.name: "edit-undo"
                    Binding on icon.color { value: Kirigami.Theme.textColor; when: Theme.original }
                    enabled: page.isCurrent
                    onClicked: backend.requestFactoryCurves()
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.text: page.isCurrent ? Theme.tr("Загрузить кривую BIOS для этого режима как отправную точку")
                                                      : Theme.tr("BIOS отдаёт заводскую кривую только для включённого режима")
                }
                Item { Layout.fillWidth: true }
                AppButton {
                    text: Theme.tr("Применить")
                    icon.name: "dialog-ok-apply"
                    Binding on icon.color { value: Kirigami.Theme.textColor; when: Theme.original }
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

    signal factoryLoaded()
}
