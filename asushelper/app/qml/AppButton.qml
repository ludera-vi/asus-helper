// Кнопка. В своих темах (оригинальная, noctalia) — скруглённая, в цветах окна, как плитки; в теме KDE — как
// рисует стиль KDE (привязка ниже выключена).
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Button {
    id: button

    Binding { target: button; property: "background"; value: button.shape; when: Theme.original }

    // фон — значение свойства, а не дочерний элемент: в теме KDE он ни к чему не прикреплён и не рисуется
    // (дочерний был бы виден поверх кнопки полосой своего размера); в своих темах привязка выше делает его фоном
    readonly property Item shape: Rectangle {
        implicitWidth: Kirigami.Units.gridUnit * 4
        implicitHeight: Kirigami.Units.gridUnit * 1.8
        radius: Kirigami.Units.cornerRadius * 2
        color: button.down ? Qt.alpha(Kirigami.Theme.textColor, 0.16)
             : button.hovered ? Qt.alpha(Kirigami.Theme.textColor, 0.11)
             : Qt.alpha(Kirigami.Theme.textColor, 0.07)
        border.width: 1
        border.color: button.visualFocus ? Kirigami.Theme.highlightColor : Qt.alpha(Kirigami.Theme.textColor, 0.12)
        Behavior on color { ColorAnimation { duration: Kirigami.Units.shortDuration } }
    }
}
