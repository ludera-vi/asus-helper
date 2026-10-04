// Общие справочники окна: названия, иконки и цвета режимов. Цвета — из темы KDE или оригинальной темы.
pragma Singleton
import QtQuick

Item {
    // Цвета темы KDE передаёт окно (Main.qml): у одиночки вне окна своей палитры нет
    property color positive: "green"
    property color highlight: "steelblue"
    property color negative: "red"
    property color neutral: "orange"

    // Оформление: системное (цвета KDE) или оригинальное (своя тёмная тема) — задаёт окно
    property bool original: false
    property color card: "transparent"     // фон разделов-карточек в оригинальной теме
    // Мелкий шрифт подписей: в KDE — системный (Kirigami.Theme.smallFont), где система его не задаёт
    // (GNOME: он равен обычному) — на ступень меньше обычного. Задаёт окно (Main.qml)
    property font smallFont

    // Перевод: язык и словарь «русская строка → перевод» передаёт окно (Main.qml) из программы
    property string lang: "ru"
    property var dict: ({})
    function tr(s) { return lang !== "ru" && dict[s] !== undefined ? dict[s] : s }

    readonly property var profiles: [
        { id: "quiet", name: tr("Тихий"), hint: tr("тише и дольше"), icon: "battery-profile-powersave-symbolic" },
        { id: "balanced", name: tr("Баланс"), hint: tr("на каждый день"), icon: "battery-profile-balanced-symbolic" },
        { id: "performance", name: tr("Турбо"), hint: tr("максимум"), icon: "battery-profile-performance-symbolic" },
    ]

    readonly property var auraModes: [
        { id: "static", name: tr("Ровный") },
        { id: "breathe", name: tr("Дыхание") },
        { id: "cycle", name: tr("Радуга") },
        { id: "strobe", name: tr("Мигание") },
    ]

    readonly property var swatches: ["#FFFFFF", "#FF0000", "#FF6A00", "#FFD000", "#00FF40",
                                     "#00E5FF", "#0050FF", "#A000FF", "#FF00A0", "#80A68E"]

    // У каждого режима свой цвет, как в G-Helper: тихий — «хороший», турбо — «горячий»
    function profileColor(id) {
        switch (id) {
        case "quiet": return positive
        case "performance": return negative
        default: return highlight
        }
    }

    function profileName(id) {
        const p = profiles.find(x => x.id === id)
        return p ? p.name : (id || "—")
    }

    function profileIcon(id) {
        const p = profiles.find(x => x.id === id)
        return p ? p.icon : "speedometer-symbolic"
    }

    function gpuInfo(gpu, nv) {
        if (!gpu || !gpu.state) return ""
        const d = gpu.dgpu_name || "NVIDIA"
        if (gpu.switching) return (gpu.target === "eco" ? tr("выключаю %1…") : tr("включаю %1…")).arg(d)
        switch (gpu.state) {
        case "off": return tr("%1 выключена").arg(d)
        case "suspended": return tr("%1 спит").arg(d)
        case "active":
            return nv && nv.load !== undefined
                ? d + " " + nv.load + "% · " + Math.round(nv.power) + tr(" Вт · ") + nv.temp + " °C"
                : ((gpu.holders || []).length ? tr("%1 работает") : tr("%1 включена")).arg(d)
        case "missing": return tr("%1 без драйвера").arg(d)
        default: return gpu.state
        }
    }
}
