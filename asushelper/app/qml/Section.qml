// Раздел окна: заголовок с иконкой и сводкой справа, под ним содержимое.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: section

    property string title: ""
    property string iconName: ""
    property string info: ""            // справа от заголовка: «41 °C · 1900 об/мин»
    property color infoColor: Kirigami.Theme.textColor
    default property alias content: body.data

    Layout.fillWidth: true
    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
        Kirigami.Icon {
            implicitWidth: Kirigami.Units.iconSizes.small
            implicitHeight: Kirigami.Units.iconSizes.small
            source: section.iconName
            visible: section.iconName !== ""
        }
        Kirigami.Heading {
            level: 4
            text: section.title
        }
        Item { Layout.fillWidth: true }
        QQC2.Label {
            text: section.info
            color: section.infoColor
            font: Kirigami.Theme.smallFont
            opacity: 0.85
        }
    }

    ColumnLayout {
        id: body
        Layout.fillWidth: true
        spacing: Kirigami.Units.smallSpacing
    }
}
