// Выбор режима, для которого настраиваются вентиляторы или мощность; «сейчас» — включённый режим.
import QtQuick
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami

ColumnLayout {
    id: tabs
    property string profile
    readonly property string current: (backend.state || {}).profile || ""
    Layout.fillWidth: true
    spacing: Kirigami.Units.smallSpacing

    RowLayout {
        spacing: Kirigami.Units.smallSpacing
        Repeater {
            model: Theme.profiles
            Tile {
                required property var modelData
                text: modelData.name
                subtitle: tabs.current === modelData.id ? Theme.tr("сейчас") : ""
                iconName: modelData.icon
                accent: Theme.profileColor(modelData.id)
                selected: tabs.profile === modelData.id
                onClicked: tabs.profile = modelData.id
            }
        }
    }
    QQC2.Label {
        Layout.fillWidth: true
        visible: tabs.profile !== tabs.current
        wrapMode: Text.Wrap
        font: Kirigami.Theme.smallFont
        opacity: 0.7
        text: Theme.tr("Настройки сохранятся и включатся, когда будет включён режим «%1»").arg(Theme.profileName(tabs.profile))
    }
}
