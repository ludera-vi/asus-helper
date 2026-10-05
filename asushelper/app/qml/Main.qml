// Окно Asus-helper. В KDE и niri на Wayland — всплывающая панель у трея (layer-shell): прикреплена к углу
// экрана со стороны панели, закрывается по Esc и по клику мимо. В других средах — обычное окно;
// в GNOME (layer-shell там нет) его можно перетащить за шапку.
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
    // movable задаёт Python: окно без layer-shell (GNOME) — таскается за шапку
    property bool movable: false
    // underPanels задаёт Python: niri и др. (не KDE и не GNOME) — панель (noctalia, waybar) тоже layer-shell,
    // окно встаёт под неё; закрывается кликом мимо (catcher), а не потерей фокуса
    property bool underPanels: false
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
    LayerShell.Window.exclusionZone: underPanels ? 0 : -1

    onVisibleChanged: {
        backend.active = visible
        if (!visible) catcher.visible = false
        if (visible) { requestActivate(); stack.pop(null) }
    }
    // клик мимо окна — закрыть, как всплывающие окна Plasma. Вне KDE (niri) по потере фокуса не закрываем: там
    // часто «фокус за мышью», и окно закрывалось, стоило мыши чуть выйти за край. Клик мимо ловит catcher
    onActiveChanged: if (!active && visible && !keepOpen.running && !underPanels) visible = false

    // Вне KDE: прозрачный слой на весь экран под окном, пока оно открыто. Клик по нему (мимо окна) закрывает
    // окно; мышь над ним не отдаёт фокус окнам под ним. Слой Top — всегда ниже окна (Overlay); поверх
    // полноэкранной игры его не видно, там окно закрывают Esc, крестик и значок
    Window {
        id: catcher
        visible: false
        color: "transparent"
        flags: Qt.FramelessWindowHint
        LayerShell.Window.scope: "asus-helper-catcher"
        LayerShell.Window.layer: LayerShell.Window.LayerTop
        LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorBottom
                                   | LayerShell.Window.AnchorLeft | LayerShell.Window.AnchorRight
        LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
        LayerShell.Window.exclusionZone: -1
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onPressed: win.visible = false
        }
    }

    // после открытия окно ещё не получило фокус — не закрываем его сразу
    Timer { id: keepOpen; interval: 400 }
    function openMonitor() {
        if (stack.depth === 1) stack.push(scrolled.createObject(stack, { page: monitorPage }))
    }
    function openFans() {
        if (stack.depth === 1) stack.push(scrolled.createObject(stack, { page: fansPage }))
    }
    property string powerProfile: "balanced"
    function openPower(profile) {
        powerProfile = profile
        if (stack.depth === 2) stack.push(scrolled.createObject(stack, { page: powerPage }))
    }
    function toggle() {
        if (visible) { visible = false; return }
        keepOpen.restart()
        if (underPanels) catcher.visible = true
        visible = true
    }

    Binding { target: Theme; property: "lang"; value: backend.language }
    Binding { target: Theme; property: "dict"; value: backend.translations }
    // свои цвета (Fusion, карточки): оригинальная тема и тема noctalia (цвета меняются вместе с темой noctalia)
    readonly property bool original: backend.theme !== "system"
    readonly property var oc: backend.colors
    Binding { target: Theme; property: "original"; value: win.original }
    Binding {
        target: Theme; property: "smallFont"
        value: Kirigami.Theme.smallFont.pointSize < Kirigami.Theme.defaultFont.pointSize
               ? Kirigami.Theme.smallFont
               : Qt.font({ family: Kirigami.Theme.defaultFont.family,
                           pointSize: Math.round(Kirigami.Theme.defaultFont.pointSize * 0.82) })
    }
    Binding { target: Theme; property: "card"; value: win.oc.card; when: win.original }
    Binding { target: Theme; property: "colors"; value: win.oc; when: win.original }
    Binding { target: Theme; property: "positive"; value: win.original ? win.oc.positive : Kirigami.Theme.positiveTextColor }
    Binding { target: Theme; property: "highlight"; value: win.original ? win.oc.accent : Kirigami.Theme.highlightColor }
    Binding { target: Theme; property: "negative"; value: win.original ? win.oc.negative : Kirigami.Theme.negativeTextColor }
    Binding { target: Theme; property: "neutral"; value: win.original ? win.oc.neutral : Kirigami.Theme.neutralTextColor }

    // Свои цвета и для элементов Qt Quick (кнопки, переключатели, ползунки, списки) — палитрой самого окна. Одной
    // палитры приложения мало: при запуске Qt Quick берёт палитру платформенной темы (в niri часто
    // QT_QPA_PLATFORMTHEME=gtk3 — белый текст и синие переключатели на светлой теме noctalia)
    Binding { target: win.palette; property: "window"; value: win.oc.window; when: win.original }
    Binding { target: win.palette; property: "windowText"; value: win.oc.text; when: win.original }
    Binding { target: win.palette; property: "base"; value: win.oc.card; when: win.original }
    Binding { target: win.palette; property: "alternateBase"; value: win.oc.button; when: win.original }
    Binding { target: win.palette; property: "text"; value: win.oc.text; when: win.original }
    Binding { target: win.palette; property: "button"; value: win.oc.button; when: win.original }
    Binding { target: win.palette; property: "buttonText"; value: win.oc.text; when: win.original }
    Binding { target: win.palette; property: "brightText"; value: win.oc.negative; when: win.original }
    Binding { target: win.palette; property: "highlight"; value: win.oc.accent; when: win.original }
    Binding { target: win.palette; property: "highlightedText"; value: win.oc.on_accent || "#ffffff"; when: win.original }
    Binding { target: win.palette; property: "toolTipBase"; value: win.oc.card; when: win.original }
    Binding { target: win.palette; property: "toolTipText"; value: win.oc.text; when: win.original }
    Binding { target: win.palette; property: "placeholderText"; value: win.oc.dim; when: win.original }
    Binding { target: win.palette; property: "link"; value: win.oc.accent; when: win.original }
    Binding { target: win.palette; property: "accent"; value: win.oc.accent; when: win.original }
    Binding { target: win.palette; property: "mid"; value: win.oc.border; when: win.original }
    Binding { target: win.palette; property: "dark"; value: win.oc.window; when: win.original }
    Binding { target: win.palette; property: "light"; value: win.oc.button; when: win.original }
    Binding { target: win.palette; property: "midlight"; value: win.oc.button; when: win.original }
    Binding { target: win.palette.disabled; property: "windowText"; value: win.oc.disabled; when: win.original }
    Binding { target: win.palette.disabled; property: "text"; value: win.oc.disabled; when: win.original }
    Binding { target: win.palette.disabled; property: "buttonText"; value: win.oc.disabled; when: win.original }

    // Оригинальная тема: свои цвета для всего, что рисует Kirigami. На корне окна, а не на рамке: всплывающие
    // окна (слой Overlay) — тоже его дети, иначе в них были бы цвета платформенной темы (заголовки, сообщения, иконки, плитки)
    Binding { target: win.contentItem.Kirigami.Theme; property: "backgroundColor"; value: win.oc.window; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "alternateBackgroundColor"; value: win.oc.card; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "textColor"; value: win.oc.text; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "disabledTextColor"; value: win.oc.disabled; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "highlightColor"; value: win.oc.accent; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "highlightedTextColor"; value: "#ffffff"; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "focusColor"; value: win.oc.accent; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "hoverColor"; value: win.oc.accent; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "linkColor"; value: win.oc.accent; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "activeTextColor"; value: win.oc.accent; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "positiveTextColor"; value: win.oc.positive; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "negativeTextColor"; value: win.oc.negative; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "neutralTextColor"; value: win.oc.neutral; when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "positiveBackgroundColor"; value: Qt.alpha(win.oc.positive, 0.2); when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "negativeBackgroundColor"; value: Qt.alpha(win.oc.negative, 0.2); when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "neutralBackgroundColor"; value: Qt.alpha(win.oc.neutral, 0.2); when: win.original }
    Binding { target: win.contentItem.Kirigami.Theme; property: "activeBackgroundColor"; value: Qt.alpha(win.oc.accent, 0.2); when: win.original }

    Shortcut { sequence: "Escape"; onActivated: stack.depth > 1 ? stack.pop() : (win.visible = false) }

    Rectangle {
        id: frame
        anchors.fill: parent
        radius: Kirigami.Units.cornerRadius * 3
        color: Kirigami.Theme.backgroundColor
        border.color: win.original ? win.oc.border : Qt.alpha(Kirigami.Theme.textColor, 0.15)
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
                DragHandler {
                    enabled: win.movable
                    target: null
                    onActiveChanged: if (active) win.startSystemMove()
                }
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
                                                : Theme.tr("демон не запущен")
                        color: backend.connected ? Kirigami.Theme.textColor : Kirigami.Theme.negativeTextColor
                        font: Theme.smallFont
                        opacity: backend.connected ? 0.7 : 1
                    }
                }
                Item { Layout.fillWidth: true }
                QQC2.ToolButton {
                    icon.name: "office-chart-line-forecast-symbolic"
                    // своя тема: значок цветом текста (без этого после смены светлой/тёмной темы noctalia он остаётся старым)
                    Binding on icon.color { value: Kirigami.Theme.textColor; when: Theme.original }
                    text: Theme.tr("Графики")
                    display: QQC2.AbstractButton.TextBesideIcon
                    visible: stack.depth === 1
                    onClicked: win.openMonitor()
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    QQC2.ToolTip.text: Theme.tr("Графики температуры, вентиляторов и батареи")
                }
                QQC2.ToolButton {
                    icon.name: "window-close-symbolic"
                    Binding on icon.color { value: Kirigami.Theme.textColor; when: Theme.original }
                    text: Theme.tr("Закрыть окно")
                    display: QQC2.AbstractButton.IconOnly
                    onClicked: win.visible = false
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    QQC2.ToolTip.text: Theme.tr("Закрыть окно (Asus-helper остаётся в трее; выйти — правый клик по значку)")
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
            // только вертикально: Flickable по умолчанию даёт тянуть и вбок, если ширина содержимого хоть
            // на пиксель не совпала с окном, — страница уезжала влево и перехватывала перетаскивание точек
            Component.onCompleted: {
                contentItem.flickableDirection = Flickable.VerticalFlick
                contentItem.boundsBehavior = Flickable.StopAtBounds
            }
            Loader {
                id: loader
                width: sv.availableWidth
                sourceComponent: sv.page
            }
        }
    }

    Component { id: mainPage; MainPage { onOpenFans: win.openFans(); onOpenMonitor: win.openMonitor() } }
    Component { id: fansPage; FansPage { onBack: stack.pop(); onOpenPower: p => win.openPower(p) } }
    Component { id: powerPage; PowerPage { profile: win.powerProfile; onBack: stack.pop() } }
    Component { id: monitorPage; MonitorPage { onBack: stack.pop() } }

    // высота содержимого текущей страницы — по ней окно подбирает свою высоту
    readonly property real pageHeight: stack.currentItem ? stack.currentItem.pageHeight || 0 : 0
}
