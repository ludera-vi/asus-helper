// Кружок цвета подсветки.
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.AbstractButton {
    id: swatch
    property color color
    property bool selected: false

    implicitWidth: Kirigami.Units.iconSizes.medium
    implicitHeight: implicitWidth
    hoverEnabled: true
    Accessible.name: color.toString()

    background: Rectangle {
        radius: width / 2
        color: swatch.color
        border.width: swatch.selected ? 3 : 1
        border.color: swatch.selected ? Kirigami.Theme.textColor : Qt.alpha(Kirigami.Theme.textColor, 0.25)
        scale: swatch.hovered ? 1.1 : 1
        Behavior on scale { NumberAnimation { duration: Kirigami.Units.shortDuration } }
    }
}
