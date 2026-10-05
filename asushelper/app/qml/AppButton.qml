// Кнопка. В своих темах (оригинальная, noctalia) — скруглённая, в цветах окна, как плитки; в теме KDE — как
// рисует стиль KDE (привязка ниже выключена).
import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Button {
    id: button

    Binding { target: button; property: "background"; value: shape; when: Theme.original }

    Rectangle {
        id: shape
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
