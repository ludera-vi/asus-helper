// Раздел окна, как в G-Helper: «Режим: Турбо» слева, датчики справа, под ними плитки.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

Item {
    id: section

    property string title: ""
    property string value: ""           // текущее значение после двоеточия: «Режим: Тихий»
    property string iconName: ""
    property string info: ""            // справа: «CPU 46 °C · 1900 об/мин»
    property color infoColor: Kirigami.Theme.textColor
    default property alias content: body.data

    // в оригинальной теме раздел — карточка со своим фоном, в системной — как в KDE, без рамок
    readonly property real pad: Theme.original ? Kirigami.Units.largeSpacing : 0
    Layout.fillWidth: true
    implicitWidth: column.implicitWidth + pad * 2
    implicitHeight: column.implicitHeight + pad * 2

    Rectangle {
        anchors.fill: parent
        visible: Theme.original
        radius: Kirigami.Units.cornerRadius * 3
        color: Theme.card
    }

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: section.pad
        spacing: Kirigami.Units.smallSpacing

        RowLayout {
            Layout.fillWidth: true
            Layout.bottomMargin: Kirigami.Units.smallSpacing / 2
            spacing: Kirigami.Units.smallSpacing
            Kirigami.Icon {
                implicitWidth: Kirigami.Units.iconSizes.small
                implicitHeight: Kirigami.Units.iconSizes.small
                source: section.iconName
                isMask: section.iconName.indexOf("-symbolic") !== -1
                color: Kirigami.Theme.textColor
                visible: section.iconName !== ""
            }
            QQC2.Label {
                text: section.title + (section.value ? ":" : "")
                font.weight: Font.DemiBold
            }
            QQC2.Label {
                visible: section.value !== ""
                text: section.value
                font.weight: Font.DemiBold
                color: Kirigami.Theme.highlightColor
            }
            Item { Layout.fillWidth: true }
            QQC2.Label {
                text: section.info
                color: section.infoColor
                font: Kirigami.Theme.smallFont
                opacity: 0.8
            }
        }

        ColumnLayout {
            id: body
            Layout.fillWidth: true
            spacing: Kirigami.Units.smallSpacing
        }
    }
}
