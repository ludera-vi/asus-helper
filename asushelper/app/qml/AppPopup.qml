// Всплывающее окно (подсветка «Ещё», цвет, Slash, предупреждения). В своих темах (оригинальная, noctalia) —
// карточка со скруглёнными углами, рамкой и тенью, фон окна затемняется, появляется плавно. В теме KDE —
// как рисует стиль KDE: привязки ниже тогда выключены и ничего не меняют.
import QtQuick
import QtQuick.Effects
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

QQC2.Popup {
    id: popup

    readonly property real cardRadius: Kirigami.Units.cornerRadius * 3

    Binding { target: popup; property: "background"; value: popup.card; when: Theme.original }
    // палитра окна: всплывающее живёт в слое Overlay и иначе берёт палитру платформенной темы (синие
    // переключатели, бледные ползунки)
    readonly property var c: Theme.colors
    Binding { target: popup.palette; property: "window"; value: popup.c.card; when: Theme.original }
    Binding { target: popup.palette; property: "windowText"; value: popup.c.text; when: Theme.original }
    Binding { target: popup.palette; property: "base"; value: popup.c.window; when: Theme.original }
    Binding { target: popup.palette; property: "text"; value: popup.c.text; when: Theme.original }
    Binding { target: popup.palette; property: "button"; value: popup.c.button; when: Theme.original }
    Binding { target: popup.palette; property: "buttonText"; value: popup.c.text; when: Theme.original }
    Binding { target: popup.palette; property: "highlight"; value: popup.c.accent; when: Theme.original }
    Binding { target: popup.palette; property: "highlightedText"; value: popup.c.on_accent || "#ffffff"; when: Theme.original }
    Binding { target: popup.palette; property: "accent"; value: popup.c.accent; when: Theme.original }
    Binding { target: popup.palette; property: "placeholderText"; value: popup.c.dim; when: Theme.original }
    Binding { target: popup.palette; property: "mid"; value: popup.c.border; when: Theme.original }
    Binding { target: popup.palette; property: "dark"; value: popup.c.window; when: Theme.original }
    Binding { target: popup.palette; property: "light"; value: popup.c.button; when: Theme.original }
    Binding { target: popup.palette; property: "midlight"; value: popup.c.button; when: Theme.original }
    Binding { target: popup.palette.disabled; property: "text"; value: popup.c.disabled; when: Theme.original }
    Binding { target: popup.palette.disabled; property: "windowText"; value: popup.c.disabled; when: Theme.original }
    Binding { target: popup.palette.disabled; property: "buttonText"; value: popup.c.disabled; when: Theme.original }
    Binding { target: popup.QQC2.Overlay; property: "modal"; value: dim; when: Theme.original }
    Binding { target: popup; property: "enter"; value: appear; when: Theme.original }
    Binding { target: popup; property: "exit"; value: disappear; when: Theme.original }

    // фон — значение свойства, а не дочерний элемент: в теме KDE он ни к чему не прикреплён и не входит в
    // содержимое окна (иначе сбивал бы его размер); в своих темах привязка выше делает его фоном
    readonly property Item card: Item {
        RectangularShadow {
            anchors.fill: parent
            radius: popup.cardRadius
            blur: Kirigami.Units.gridUnit * 1.5
            offset.y: Kirigami.Units.smallSpacing
            color: Qt.alpha("black", 0.45)
        }
        Rectangle {
            anchors.fill: parent
            radius: popup.cardRadius
            color: Kirigami.Theme.alternateBackgroundColor
            border.color: Qt.alpha(Kirigami.Theme.textColor, 0.14)
            border.width: 1
        }
    }

    // затемнение — по форме окна (у окна скруглённые углы и прозрачный фон вокруг)
    Component {
        id: dim
        Rectangle { color: Qt.alpha("black", 0.35); radius: Kirigami.Units.cornerRadius * 3 }
    }

    Transition {
        id: appear
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Kirigami.Units.shortDuration }
        NumberAnimation { property: "scale"; from: 0.96; to: 1; duration: Kirigami.Units.shortDuration; easing.type: Easing.OutCubic }
    }
    Transition {
        id: disappear
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Kirigami.Units.shortDuration }
    }
}
