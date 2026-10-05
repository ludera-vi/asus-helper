// Мощность и процессор для каждого режима: лимиты мощности (BIOS), Turbo Boost, EPP.
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
        Kirigami.Heading { level: 3; text: Theme.tr("Мощность и процессор"); Layout.fillWidth: true }
    }

    ProfileTabs {
        profile: page.profile
        onProfileChanged: page.profile = profile
    }

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
                    QQC2.Label { text: limit.names[0]; Layout.fillWidth: true; elide: Text.ElideRight }
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
                    font: Theme.smallFont
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
                QQC2.Label { text: Theme.tr("Turbo Boost процессора"); Layout.fillWidth: true; elide: Text.ElideRight }
                QQC2.Label {
                    // не помещается в строку (крупный шрифт GNOME) — переносится, а не раздвигает окно
                    text: Theme.tr("выключен — холоднее и тише, но медленнее в тяжёлых задачах")
                    font: Theme.smallFont
                    opacity: 0.6
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                }
            }
            QQC2.Switch {
                readonly property var mine: page.pcfg.cpu_boost
                checked: mine === null || mine === undefined ? page.profile !== "quiet" : mine
                onToggled: backend.setCpuBoost(page.profile, checked)
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
            visible: (page.st.epp_choices || []).length > 0     // процессор поддерживает EPP
            QQC2.Label { text: Theme.tr("Приоритет процессора"); Layout.fillWidth: true; elide: Text.ElideRight }
            AppComboBox {
                // под подписью и во всю ширину: длинное «Как у режима: …» не раздвигает окно
                id: epp
                Layout.fillWidth: true
                readonly property var choices: ["", ...(page.st.epp_choices || []).filter(c => c !== "default")]
                readonly property string modeValue: Theme.eppDefaults[page.profile] || ""
                model: choices.map(c => c === "" ? Theme.tr("Как у режима: «%1»").arg(Theme.eppName(modeValue))
                                               : Theme.eppName(c))
                currentIndex: Math.max(0, choices.indexOf(page.pcfg.epp || ""))
                onActivated: i => backend.setEpp(page.profile, choices[i])
                // значение, которое уходит в ядро, — для тех, кто знает EPP, и для отчётов об ошибках
                QQC2.ToolTip.visible: hovered
                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                QQC2.ToolTip.text: "EPP: " + (choices[currentIndex] || modeValue)
            }
        }

        AppButton {
            text: Theme.tr("Мощность — как в BIOS")
            icon.name: "edit-undo"
            Binding on icon.color { value: Kirigami.Theme.textColor; when: Theme.original }
            enabled: Object.keys(page.pcfg.power_limits || {}).length > 0
            onClicked: backend.resetPowerLimits(page.profile)
        }
    }

}
