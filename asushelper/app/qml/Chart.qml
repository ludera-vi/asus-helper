// Линейный график по времени: одна или несколько линий, ось времени справа налево («сейчас» справа).
// Наведение курсора показывает значения в этой точке. Цвета задаёт вызывающий (из темы KDE).
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Item {
    id: chart

    property var times: []                 // unix-секунды, по возрастанию
    property var series: []                // [{ values: [...], color, name }]
    property string unit: ""
    property real span: 3600               // сколько секунд показывать
    property real yMin: NaN                // NaN — по данным
    property real yMax: NaN
    property bool fill: true
    property int decimals: 0

    readonly property real now: times.length ? times[times.length - 1] : Date.now() / 1000
    readonly property real padL: Kirigami.Units.gridUnit * 2
    readonly property real padB: Kirigami.Units.gridUnit * 1.1
    readonly property real padT: Kirigami.Units.smallSpacing
    readonly property real plotW: width - padL - Kirigami.Units.smallSpacing
    readonly property real plotH: height - padT - padB
    property real hoverX: -1

    implicitHeight: Kirigami.Units.gridUnit * 6

    readonly property bool empty: !series.some(s => s.values.some((v, i) => v !== null && v !== undefined && times[i] >= now - span))

    // диапазон по оси Y: по данным с запасом, «круглые» границы
    readonly property var range: {
        let lo = Infinity, hi = -Infinity
        for (const s of series)
            for (let i = 0; i < s.values.length; i++) {
                const v = s.values[i]
                if (v === null || v === undefined || times[i] < now - span) continue
                lo = Math.min(lo, v); hi = Math.max(hi, v)
            }
        if (!isFinite(lo)) { lo = 0; hi = 1 }
        if (!isNaN(yMin)) lo = Math.min(lo, yMin)
        if (!isNaN(yMax)) hi = Math.max(hi, yMax)
        if (hi - lo < 1e-6) hi = lo + 1
        const step = Math.pow(10, Math.floor(Math.log10((hi - lo) / 2)))
        return [Math.floor(lo / step) * step, Math.ceil(hi / step) * step]
    }

    function xOf(t) { return padL + (1 - (now - t) / span) * plotW }
    function yOf(v) { return padT + (1 - (v - range[0]) / (range[1] - range[0])) * plotH }

    onSeriesChanged: canvas.requestPaint()
    onTimesChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHoverXChanged: canvas.requestPaint()

    QQC2.Label {
        anchors.centerIn: parent
        visible: chart.empty
        text: "нет данных"
        opacity: 0.5
    }

    Canvas {
        id: canvas
        anchors.fill: parent
        visible: !chart.empty
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const text = Kirigami.Theme.textColor
            ctx.font = Math.round(Kirigami.Theme.smallFont.pixelSize || 11) + "px sans-serif"
            ctx.lineWidth = 1

            // горизонтальные линии: низ, середина, верх
            for (const f of [0, 0.5, 1]) {
                const v = range[0] + (range[1] - range[0]) * f
                const y = Math.round(yOf(v)) + 0.5
                ctx.strokeStyle = Qt.alpha(text, 0.1)
                ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke()
                ctx.fillStyle = Qt.alpha(text, 0.55)
                ctx.textAlign = "right"; ctx.textBaseline = "middle"
                ctx.fillText(v.toFixed(decimals) + unit, padL - 4, y)
            }
            // подписи времени
            ctx.textAlign = "center"; ctx.textBaseline = "top"
            const marks = span >= 86400 ? [86400, 43200, 0] : [span, span / 2, 0]
            for (const ago of marks) {
                const x = xOf(now - ago)
                const label = ago === 0 ? "сейчас" : span >= 7200 ? "−" + Math.round(ago / 3600) + " ч" : "−" + Math.round(ago / 60) + " мин"
                ctx.fillText(label, Math.min(Math.max(x, padL + 16), padL + plotW - 16), padT + plotH + 3)
            }

            for (const s of series) {
                ctx.beginPath()
                let started = false, firstX = 0, lastX = 0
                for (let i = 0; i < s.values.length; i++) {
                    const v = s.values[i]
                    if (v === null || v === undefined || times[i] < now - span) continue
                    const x = xOf(times[i]), y = yOf(v)
                    if (!started) { ctx.moveTo(x, y); started = true; firstX = x } else ctx.lineTo(x, y)
                    lastX = x
                }
                if (!started) continue
                ctx.strokeStyle = s.color
                ctx.lineWidth = 2
                ctx.stroke()
                if (fill && series.length === 1) {
                    ctx.lineTo(lastX, padT + plotH); ctx.lineTo(firstX, padT + plotH); ctx.closePath()
                    ctx.fillStyle = Qt.alpha(s.color, 0.15)
                    ctx.fill()
                }
            }

            if (hoverX >= padL) {
                ctx.strokeStyle = Qt.alpha(text, 0.4)
                ctx.lineWidth = 1
                ctx.beginPath(); ctx.moveTo(hoverX + 0.5, padT); ctx.lineTo(hoverX + 0.5, padT + plotH); ctx.stroke()
            }
        }
    }

    // значение под курсором
    readonly property int hoverIndex: {
        if (hoverX < padL || !times.length) return -1
        const t = now - (1 - (hoverX - padL) / plotW) * span
        let best = -1, bestD = Infinity
        for (let i = 0; i < times.length; i++) {
            const d = Math.abs(times[i] - t)
            if (d < bestD) { best = i; bestD = d }
        }
        return best
    }

    QQC2.Label {
        visible: chart.hoverIndex >= 0
        x: Math.min(chart.width - width, Math.max(chart.padL, chart.hoverX + 8))
        y: chart.padT
        padding: 3
        font: Kirigami.Theme.smallFont
        text: {
            if (chart.hoverIndex < 0) return ""
            const ago = Math.round((chart.now - chart.times[chart.hoverIndex]) / 60)
            return (ago ? ago + " мин назад" : "сейчас") + "\n" + chart.series.map(s => {
                const v = s.values[chart.hoverIndex]
                return (s.name ? s.name + ": " : "") + (v === null || v === undefined ? "—" : Number(v).toFixed(chart.decimals) + chart.unit)
            }).join("\n")
        }
        background: Rectangle {
            color: Kirigami.Theme.backgroundColor
            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.2)
            radius: 3
        }
    }

    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        onPositionChanged: mouse => chart.hoverX = mouse.x
        onExited: chart.hoverX = -1
    }
}
