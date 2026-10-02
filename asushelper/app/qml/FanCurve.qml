// Редактор кривой вентилятора: 8 точек «температура → обороты», точки тянутся мышью.
// Температуры и обороты не убывают слева направо (этого требует BIOS) — соседние точки
// ограничивают перетаскивание. Вертикальная линия — текущая температура.
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Item {
    id: editor

    property var temp: [30, 40, 50, 60, 70, 80, 90, 100]
    property var pwm: [0, 20, 40, 80, 120, 170, 220, 255]   // 0–255
    property real currentTemp: NaN
    property bool editable: true
    property color accent: Kirigami.Theme.highlightColor
    signal edited()

    readonly property int tMin: 20
    readonly property int tMax: 100
    readonly property real padL: Kirigami.Units.gridUnit * 1.6
    readonly property real padB: Kirigami.Units.gridUnit * 1.2
    readonly property real padT: Kirigami.Units.smallSpacing * 2
    readonly property real padR: Kirigami.Units.smallSpacing * 2
    readonly property real plotW: width - padL - padR
    readonly property real plotH: height - padT - padB
    property int dragIndex: -1
    property int hoverIndex: -1

    implicitHeight: Kirigami.Units.gridUnit * 9

    function xOf(t) { return padL + (t - tMin) / (tMax - tMin) * plotW }
    function yOf(p) { return padT + (1 - p / 255) * plotH }
    function tOf(x) { return Math.round(tMin + (x - padL) / plotW * (tMax - tMin)) }
    function pOf(y) { return Math.round((1 - (y - padT) / plotH) * 255) }
    function pct(p) { return Math.round(p * 100 / 255) }

    function nearest(x, y) {
        let best = -1, bestD = Kirigami.Units.gridUnit * 1.2
        for (let i = 0; i < temp.length; i++) {
            const d = Math.hypot(xOf(temp[i]) - x, yOf(pwm[i]) - y)
            if (d < bestD) { best = i; bestD = d }
        }
        return best
    }

    onTempChanged: canvas.requestPaint()
    onPwmChanged: canvas.requestPaint()
    onCurrentTempChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onAccentChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const text = Kirigami.Theme.textColor
            ctx.font = Math.round(Kirigami.Theme.smallFont.pixelSize || 11) + "px sans-serif"

            // сетка: 25/50/75/100 % и каждые 20 °C
            ctx.strokeStyle = Qt.alpha(text, 0.12)
            ctx.fillStyle = Qt.alpha(text, 0.6)
            ctx.lineWidth = 1
            for (let p = 0; p <= 100; p += 25) {
                const y = Math.round(yOf(p * 2.55)) + 0.5
                ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(width - padR, y); ctx.stroke()
                ctx.textAlign = "right"; ctx.textBaseline = "middle"
                ctx.fillText(p + "%", padL - 4, y)
            }
            for (let t = tMin; t <= tMax; t += 20) {
                const x = Math.round(xOf(t)) + 0.5
                ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke()
                ctx.textAlign = "center"; ctx.textBaseline = "top"
                ctx.fillText(t + "°", x, padT + plotH + 3)
            }

            // заливка под кривой и сама кривая
            ctx.beginPath()
            ctx.moveTo(xOf(Math.max(tMin, temp[0])), yOf(0))
            for (let i = 0; i < temp.length; i++) ctx.lineTo(xOf(temp[i]), yOf(pwm[i]))
            ctx.lineTo(xOf(tMax), yOf(pwm[pwm.length - 1]))
            ctx.lineTo(xOf(tMax), yOf(0))
            ctx.closePath()
            ctx.fillStyle = Qt.alpha(accent, 0.15)
            ctx.fill()

            ctx.beginPath()
            for (let i = 0; i < temp.length; i++) {
                if (i === 0) ctx.moveTo(xOf(temp[i]), yOf(pwm[i]))
                else ctx.lineTo(xOf(temp[i]), yOf(pwm[i]))
            }
            ctx.lineTo(xOf(tMax), yOf(pwm[pwm.length - 1]))
            ctx.strokeStyle = accent
            ctx.lineWidth = 2
            ctx.stroke()

            // текущая температура
            if (!isNaN(currentTemp) && currentTemp >= tMin && currentTemp <= tMax) {
                const x = Math.round(xOf(currentTemp)) + 0.5
                ctx.setLineDash([3, 3])
                ctx.strokeStyle = Kirigami.Theme.neutralTextColor
                ctx.lineWidth = 1
                ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, padT + plotH); ctx.stroke()
                ctx.setLineDash([])
            }

            // точки
            for (let i = 0; i < temp.length; i++) {
                const r = (i === dragIndex || i === hoverIndex) ? 6 : 4
                ctx.beginPath()
                ctx.arc(xOf(temp[i]), yOf(pwm[i]), r, 0, 2 * Math.PI)
                ctx.fillStyle = editable ? accent : Qt.alpha(text, 0.5)
                ctx.fill()
                ctx.strokeStyle = Kirigami.Theme.backgroundColor
                ctx.lineWidth = 2
                ctx.stroke()
            }
        }
    }

    // подпись точки под курсором
    QQC2.Label {
        readonly property int i: editor.dragIndex >= 0 ? editor.dragIndex : editor.hoverIndex
        visible: i >= 0
        x: Math.min(editor.width - width, Math.max(0, editor.xOf(editor.temp[i] || 0) - width / 2))
        y: Math.max(0, editor.yOf(editor.pwm[i] || 0) - height - 8)
        text: i >= 0 ? editor.temp[i] + " °C → " + editor.pct(editor.pwm[i]) + "%" : ""
        font: Kirigami.Theme.smallFont
        padding: 3
        background: Rectangle {
            color: Kirigami.Theme.backgroundColor
            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.2)
            radius: 3
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: editor.editable
        hoverEnabled: true
        cursorShape: editor.dragIndex >= 0 || editor.hoverIndex >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
        onPressed: mouse => { editor.dragIndex = editor.nearest(mouse.x, mouse.y); canvas.requestPaint() }
        onReleased: { if (editor.dragIndex >= 0) editor.edited(); editor.dragIndex = -1; canvas.requestPaint() }
        onExited: { editor.hoverIndex = -1; canvas.requestPaint() }
        onPositionChanged: mouse => {
            const i = editor.dragIndex
            if (i < 0) {
                const h = editor.nearest(mouse.x, mouse.y)
                if (h !== editor.hoverIndex) { editor.hoverIndex = h; canvas.requestPaint() }
                return
            }
            const t = editor.temp.slice(), p = editor.pwm.slice()
            const lo = i > 0 ? t[i - 1] : editor.tMin, hi = i < t.length - 1 ? t[i + 1] : editor.tMax
            const plo = i > 0 ? p[i - 1] : 0, phi = i < p.length - 1 ? p[i + 1] : 255
            t[i] = Math.max(lo, Math.min(hi, editor.tOf(mouse.x)))
            p[i] = Math.max(plo, Math.min(phi, editor.pOf(mouse.y)))
            editor.temp = t
            editor.pwm = p
        }
    }
}
