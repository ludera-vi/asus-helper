// Графики: температура, вентиляторы и мощность за последний час; заряд за сутки; здоровье батареи.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: page

    signal back()

    readonly property var h: backend.history || {}
    readonly property var t: h.t || []
    property real span: 1800

    // средняя мощность разряда за показанный отрезок
    readonly property real avgDischarge: {
        let sum = 0, n = 0
        const w = h.battery_w || []
        for (let i = 0; i < w.length; i++)
            if (w[i] > 0 && t[i] >= (t[t.length - 1] || 0) - span) { sum += w[i]; n++ }
        return n ? sum / n : NaN
    }

    spacing: Kirigami.Units.largeSpacing

    Timer {
        interval: 5000
        running: true
        repeat: true
        triggeredOnStart: true
        onTriggered: backend.refreshHistory()
    }

    RowLayout {
        Layout.fillWidth: true
        QQC2.ToolButton {
            icon.name: "go-previous"
            text: Theme.tr("Назад")
            display: QQC2.AbstractButton.IconOnly
            onClicked: page.back()
        }
        Kirigami.Heading { level: 3; text: Theme.tr("Датчики и батарея"); Layout.fillWidth: true }
    }

    RowLayout {
        spacing: Kirigami.Units.smallSpacing
        Repeater {
            model: [{ s: 600, name: Theme.tr("10 мин") }, { s: 1800, name: Theme.tr("30 мин") }, { s: 3600, name: Theme.tr("1 час") }]
            Tile {
                required property var modelData
                compact: true
                text: modelData.name
                selected: page.span === modelData.s
                onClicked: page.span = modelData.s
            }
        }
    }

    Section {
        title: Theme.tr("Процессор")
        iconName: "temperature-normal-symbolic"
        info: (backend.state || {}).cpu_temp != null ? Math.round(backend.state.cpu_temp) + Theme.tr(" °C сейчас") : ""
        Chart {
            Layout.fillWidth: true
            times: page.t
            span: page.span
            unit: "°"
            yMin: 30; yMax: 90
            series: [{ values: page.h.cpu_temp || [], color: Theme.negative, name: "CPU" }]
        }
    }

    Section {
        title: Theme.tr("Вентиляторы")
        iconName: Qt.resolvedUrl("icons/fan-symbolic.svg")
        info: Theme.tr("процессор  ·  видеокарта")
        Chart {
            Layout.fillWidth: true
            times: page.t
            span: page.span
            yMin: 0
            series: [{ values: page.h.fan_cpu || [], color: Theme.highlight, name: "CPU" },
                     { values: page.h.fan_gpu || [], color: Theme.neutral, name: "GPU" }]
        }
    }

    Section {
        title: Theme.tr("Расход от батареи")
        iconName: "battery-good-symbolic"
        info: !isNaN(page.avgDischarge) ? Theme.tr("в среднем ") + page.avgDischarge.toFixed(1) + Theme.tr(" Вт")
              : (backend.state || {}).ac ? Theme.tr("от сети") : ""
        Chart {
            Layout.fillWidth: true
            times: page.t
            span: page.span
            unit: Theme.tr(" Вт")
            yMin: 0
            decimals: 0
            series: [{ values: (page.h.battery_w || []).map(w => w === null ? null : Math.max(0, w)),
                       color: Theme.positive, name: "" }]
        }
    }

    Section {
        title: Theme.tr("Заряд за сутки")
        iconName: "battery-full-symbolic"
        info: (backend.state || {}).battery ? backend.state.battery.capacity + Theme.tr("% сейчас") : ""
        Chart {
            Layout.fillWidth: true
            times: (page.h.charge || []).map(p => p[0])
            span: 86400
            unit: "%"
            yMin: 0; yMax: 100
            series: [{ values: (page.h.charge || []).map(p => p[1]), color: Theme.positive, name: "" }]
        }
    }

    Section {
        id: healthSection
        title: Theme.tr("Здоровье батареи")
        iconName: "battery-100-symbolic"
        readonly property var health: page.h.health || []
        info: health.length ? health[health.length - 1].health + Theme.tr("% от новой") : ""
        QQC2.Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            font: Theme.smallFont
            opacity: 0.75
            text: {
                const hs = healthSection.health
                if (!hs.length) return Theme.tr("Записывается раз в день — появится после первого дня работы демона")
                const first = hs[0], last = hs[hs.length - 1]
                const days = Math.round((new Date(last.date) - new Date(first.date)) / 86400000)
                return days > 0
                    ? Theme.tr("С ") + first.date + " (" + days + Theme.tr(" дн.): ") + first.health + "% → " + last.health + "%"
                    : Theme.tr("Сегодня ") + last.health + Theme.tr("% от паспортной ёмкости. Динамика появится через несколько дней")
            }
        }
    }
}
