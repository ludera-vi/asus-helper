// Плитка выбора (режим, видеокарта, частота…) в духе G-Helper: иконка над подписью,
// у выбранной — цветная рамка и мягкая подсветка своим цветом. Все цвета — из темы KDE.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.AbstractButton {
    id: tile

    property string iconName: ""
    property string subtitle: ""
    property bool selected: false
    property bool busy: false
    property bool compact: false          // без иконки, ниже — для яркости, частоты и т. п.
    property color accent: Kirigami.Theme.highlightColor

    readonly property bool symbolic: iconName.indexOf("-symbolic") !== -1

    Layout.fillWidth: true
    Layout.fillHeight: true           // все плитки ряда одной высоты
    Layout.preferredWidth: 1          // плитки в ряду делят ширину поровну
    implicitHeight: compact ? Kirigami.Units.gridUnit * 2.2
                            : Math.max(Kirigami.Units.gridUnit * 4, content.implicitHeight + Kirigami.Units.largeSpacing * 2)
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    Accessible.description: subtitle
    opacity: enabled ? 1 : 0.45

    background: Rectangle {
        radius: Kirigami.Units.cornerRadius * 2
        color: tile.down ? Qt.alpha(Kirigami.Theme.textColor, 0.14)
             : tile.hovered ? Qt.alpha(Kirigami.Theme.textColor, 0.09)
             : Qt.alpha(Kirigami.Theme.textColor, 0.05)
        border.width: tile.selected ? 2 : (tile.visualFocus ? 1 : 0)
        border.color: tile.selected ? tile.accent : Kirigami.Theme.focusColor
        Behavior on color { ColorAnimation { duration: Kirigami.Units.shortDuration } }
        Behavior on border.color { ColorAnimation { duration: Kirigami.Units.longDuration } }

        // выбранная плитка светится своим цветом сверху вниз
        Rectangle {
            anchors.fill: parent
            anchors.margins: parent.border.width
            radius: parent.radius - parent.border.width
            opacity: tile.selected ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Kirigami.Units.longDuration } }
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.alpha(tile.accent, 0.28) }
                GradientStop { position: 1; color: Qt.alpha(tile.accent, 0.08) }
            }
        }
    }

    contentItem: ColumnLayout {
        id: content
        spacing: tile.compact ? 0 : Kirigami.Units.smallSpacing

        Item { Layout.fillHeight: true }
        Item {
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: Kirigami.Units.iconSizes.smallMedium
            implicitHeight: Kirigami.Units.iconSizes.smallMedium
            visible: tile.iconName !== "" && !tile.compact
            Kirigami.Icon {
                anchors.fill: parent
                source: tile.iconName
                // символьные иконки красим цветом плитки, цветные оставляем как есть
                isMask: tile.symbolic
                color: tile.selected ? tile.accent : Kirigami.Theme.textColor
                visible: !tile.busy
                Behavior on color { ColorAnimation { duration: Kirigami.Units.longDuration } }
            }
            QQC2.BusyIndicator {
                anchors.centerIn: parent
                width: parent.width * 1.4
                height: width
                running: tile.busy
                visible: tile.busy
            }
        }
        QQC2.Label {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            text: tile.text
            font.weight: tile.selected ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
        }
        QQC2.Label {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            visible: text !== "" && !tile.compact
            text: tile.subtitle
            font: Kirigami.Theme.smallFont
            opacity: 0.6
            elide: Text.ElideRight
        }
        Item { Layout.fillHeight: true }
    }
}
