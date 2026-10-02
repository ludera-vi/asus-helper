// Плитка выбора (режим, видеокарта, частота…): иконка, название, подпись.
// Выбранная — с цветной рамкой и подкраской своим цветом (как в G-Helper), цвета — из темы KDE.
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
    property color accent: Kirigami.Theme.highlightColor

    Layout.fillWidth: true
    Layout.preferredWidth: 1          // плитки в ряду делят ширину поровну
    implicitHeight: content.implicitHeight + Kirigami.Units.largeSpacing * 2
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text
    Accessible.description: subtitle

    background: Rectangle {
        radius: Kirigami.Units.cornerRadius * 2
        color: tile.selected ? Qt.alpha(tile.accent, 0.18)
             : tile.down ? Qt.alpha(Kirigami.Theme.textColor, 0.12)
             : tile.hovered ? Qt.alpha(Kirigami.Theme.textColor, 0.07)
             : Qt.alpha(Kirigami.Theme.textColor, 0.04)
        border.width: tile.selected ? 2 : (tile.visualFocus ? 1 : 0)
        border.color: tile.selected ? tile.accent : Kirigami.Theme.focusColor
        Behavior on color { ColorAnimation { duration: Kirigami.Units.shortDuration } }
    }

    contentItem: ColumnLayout {
        id: content
        spacing: Kirigami.Units.smallSpacing

        Item {
            Layout.alignment: Qt.AlignHCenter
            implicitWidth: Kirigami.Units.iconSizes.medium
            implicitHeight: Kirigami.Units.iconSizes.medium
            visible: tile.iconName !== ""
            Kirigami.Icon {
                anchors.fill: parent
                source: tile.iconName
                // символьные иконки красим цветом плитки, цветные оставляем как есть
                isMask: tile.iconName.endsWith("-symbolic")
                color: tile.selected ? tile.accent : Kirigami.Theme.textColor
                visible: !tile.busy
            }
            QQC2.BusyIndicator {
                anchors.fill: parent
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
            visible: text !== ""
            text: tile.subtitle
            font: Kirigami.Theme.smallFont
            opacity: 0.7
            elide: Text.ElideRight
        }
    }
}
