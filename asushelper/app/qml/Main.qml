// Окно Asus-helper. В KDE на Wayland — всплывающая панель у трея (layer-shell): прикреплена к углу
// экрана со стороны панели, закрывается по Esc и по клику мимо. В других средах — обычное окно.
import QtQuick
import QtQuick.Window
import QtQuick.Layouts
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.layershell as LayerShell

Window {
    id: win

    // anchorTop задаёт Python: панель сверху — окно у верхнего края, снизу — у нижнего
    property bool anchorTop: true
    readonly property int edge: Kirigami.Units.smallSpacing * 2

    width: Kirigami.Units.gridUnit * 25
    height: Math.min(pageHeight + edge * 2 + header.implicitHeight + Kirigami.Units.largeSpacing * 2
                     + (toast.visible ? toast.implicitHeight + Kirigami.Units.largeSpacing : 0),
                     Screen.desktopAvailableHeight - Kirigami.Units.gridUnit * 2)
    visible: false
    color: "transparent"
    title: "Asus-helper"
    flags: Qt.FramelessWindowHint

    LayerShell.Window.scope: "asus-helper"
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay   // поверх полноэкранных игр и видео
    LayerShell.Window.anchors: (anchorTop ? LayerShell.Window.AnchorTop : LayerShell.Window.AnchorBottom)
                               | LayerShell.Window.AnchorRight
    LayerShell.Window.margins: Qt.rect(0, edge, edge, edge)   // left, top, right, bottom
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityOnDemand
    LayerShell.Window.exclusionZone: -1

    onVisibleChanged: {
        backend.active = visible
        if (visible) { requestActivate(); stack.pop(null) }
    }
    // клик мимо окна — закрыть, как всплывающие окна Plasma
    onActiveChanged: if (!active && visible && !keepOpen.running) visible = false

    // после открытия окно ещё не получило фокус — не закрываем его сразу
    Timer { id: keepOpen; interval: 400 }
    function openMonitor() {
        if (stack.depth === 1) stack.push(scrolled.createObject(stack, { page: monitorPage }))
    }
    function openFans() {
        if (stack.depth === 1) stack.push(scrolled.createObject(stack, { page: fansPage }))
    }
    function toggle() {
        if (visible) { visible = false; return }
        keepOpen.restart()
        visible = true
    }

    Binding { target: Theme; property: "positive"; value: Kirigami.Theme.positiveTextColor }
    Binding { target: Theme; property: "highlight"; value: Kirigami.Theme.highlightColor }
    Binding { target: Theme; property: "negative"; value: Kirigami.Theme.negativeTextColor }
    Binding { target: Theme; property: "neutral"; value: Kirigami.Theme.neutralTextColor }

    Shortcut { sequence: "Escape"; onActivated: stack.depth > 1 ? stack.pop() : (win.visible = false) }

    Rectangle {
        anchors.fill: parent
        radius: Kirigami.Units.cornerRadius * 3
        color: Kirigami.Theme.backgroundColor
        border.color: Qt.alpha(Kirigami.Theme.textColor, 0.15)
        border.width: 1
        clip: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: win.edge
            spacing: Kirigami.Units.largeSpacing

            // ---------- шапка ----------
            RowLayout {
                id: header
                Layout.fillWidth: true
                Layout.leftMargin: Kirigami.Units.smallSpacing
                Kirigami.Icon {
                    implicitWidth: Kirigami.Units.iconSizes.medium
                    implicitHeight: implicitWidth
                    source: Theme.profileIcon((backend.state || {}).profile)
                    color: Theme.profileColor((backend.state || {}).profile)
                    isMask: true
                }
                ColumnLayout {
                    spacing: 0
                    Kirigami.Heading { level: 3; text: "Asus-helper" }
                    QQC2.Label {
                        text: backend.connected ? (((backend.state || {}).model || {}).name || "ASUS") + " · " + Theme.profileName((backend.state || {}).profile)
                                                : "демон не запущен"
                        color: backend.connected ? Kirigami.Theme.textColor : Kirigami.Theme.negativeTextColor
                        font: Kirigami.Theme.smallFont
                        opacity: backend.connected ? 0.7 : 1
                    }
                }
                Item { Layout.fillWidth: true }
                QQC2.ToolButton {
                    icon.name: "office-chart-line-forecast-symbolic"
                    text: "Графики"
                    display: QQC2.AbstractButton.TextBesideIcon
                    visible: stack.depth === 1
                    onClicked: win.openMonitor()
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    QQC2.ToolTip.text: "Графики температуры, вентиляторов и батареи"
                }
                QQC2.ToolButton {
                    icon.name: "window-close-symbolic"
                    text: "Закрыть окно"
                    display: QQC2.AbstractButton.IconOnly
                    onClicked: win.visible = false
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    QQC2.ToolTip.text: "Закрыть окно (Asus-helper остаётся в трее; выйти — правый клик по значку)"
                }
            }

            Kirigami.InlineMessage {
                id: toast
                Layout.fillWidth: true
                showCloseButton: true
                Timer { id: toastTimer; interval: 5000; onTriggered: toast.visible = false }
                Connections {
                    target: backend
                    function onMessage(text, isError) {
                        toast.text = text
                        toast.type = isError ? Kirigami.MessageType.Error : Kirigami.MessageType.Positive
                        toast.visible = true
                        toastTimer.restart()
                    }
                }
            }

            QQC2.StackView {
                id: stack
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                initialItem: scrolled.createObject(stack, { page: mainPage })
            }
        }
    }

    // страница в прокрутке: окно ограничено высотой экрана
    Component {
        id: scrolled
        QQC2.ScrollView {
            id: sv
            property Component page
            readonly property real pageHeight: loader.implicitHeight
            contentWidth: availableWidth
            QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff
            Loader {
                id: loader
                width: sv.availableWidth
                sourceComponent: sv.page
            }
        }
    }

    Component { id: mainPage; MainPage { onOpenFans: win.openFans(); onOpenMonitor: win.openMonitor() } }
    Component { id: fansPage; FansPage { onBack: stack.pop() } }
    Component { id: monitorPage; MonitorPage { onBack: stack.pop() } }

    // высота содержимого текущей страницы — по ней окно подбирает свою высоту
    readonly property real pageHeight: stack.currentItem ? stack.currentItem.pageHeight || 0 : 0
}
