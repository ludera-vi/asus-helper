// Выпадающий список. В своих темах (оригинальная, noctalia) — поле и список со скруглёнными углами в цветах
// окна, как плитки; в теме KDE — как рисует стиль KDE (привязки ниже выключены).
import QtQuick
import QtQuick.Effects
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.ComboBox {
    id: combo

    Binding { target: combo; property: "background"; value: combo.field; when: Theme.original }
    Binding { target: combo.popup; property: "background"; value: combo.list; when: Theme.original }
    Binding { target: combo.popup; property: "padding"; value: Kirigami.Units.smallSpacing; when: Theme.original }

    // фон — значение свойства, а не дочерний элемент: в теме KDE он ни к чему не прикреплён и не рисуется
    // (дочерний был бы виден поверх кнопки полосой своего размера); в своих темах привязка выше делает его фоном
    readonly property Item field: Rectangle {
        implicitWidth: Kirigami.Units.gridUnit * 6
        implicitHeight: Kirigami.Units.gridUnit * 1.8
        radius: Kirigami.Units.cornerRadius * 2
        color: combo.down ? Qt.alpha(Kirigami.Theme.textColor, 0.14)
             : combo.hovered ? Qt.alpha(Kirigami.Theme.textColor, 0.10)
             : Qt.alpha(Kirigami.Theme.textColor, 0.06)
        border.width: 1
        border.color: combo.visualFocus ? Kirigami.Theme.highlightColor : Qt.alpha(Kirigami.Theme.textColor, 0.12)
    }

    readonly property Item list: Item {
        RectangularShadow {
            anchors.fill: parent
            radius: Kirigami.Units.cornerRadius * 2
            blur: Kirigami.Units.gridUnit
            offset.y: Kirigami.Units.smallSpacing / 2
            color: Qt.alpha("black", 0.4)
        }
        Rectangle {
            anchors.fill: parent
            radius: Kirigami.Units.cornerRadius * 2
            color: Kirigami.Theme.alternateBackgroundColor
            border.width: 1
            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.14)
        }
    }
}
