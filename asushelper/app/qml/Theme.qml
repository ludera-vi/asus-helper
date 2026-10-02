// Общие справочники окна: названия, иконки и цвета режимов. Цвета — только из темы KDE.
pragma Singleton
import QtQuick
import org.kde.kirigami as Kirigami

Item {
    readonly property var profiles: [
        { id: "quiet", name: "Тихий", hint: "тише и дольше", icon: "battery-profile-powersave" },
        { id: "balanced", name: "Баланс", hint: "на каждый день", icon: "battery-profile-balanced" },
        { id: "performance", name: "Турбо", hint: "максимум", icon: "battery-profile-performance" },
    ]

    readonly property var auraModes: [
        { id: "static", name: "Ровный" },
        { id: "breathe", name: "Дыхание" },
        { id: "cycle", name: "Радуга" },
        { id: "strobe", name: "Мигание" },
    ]

    readonly property var swatches: ["#FFFFFF", "#FF0000", "#FF6A00", "#FFD000", "#00FF40",
                                     "#00E5FF", "#0050FF", "#A000FF", "#FF00A0", "#80A68E"]

    // У каждого режима свой цвет, как в G-Helper: тихий — «хороший», турбо — «горячий»
    function profileColor(id) {
        switch (id) {
        case "quiet": return Kirigami.Theme.positiveTextColor
        case "performance": return Kirigami.Theme.negativeTextColor
        default: return Kirigami.Theme.highlightColor
        }
    }

    function profileName(id) {
        const p = profiles.find(x => x.id === id)
        return p ? p.name : (id || "—")
    }

    function profileIcon(id) {
        const p = profiles.find(x => x.id === id)
        return p ? p.icon : "speedometer"
    }

    function gpuInfo(gpu, nv) {
        if (!gpu || !gpu.state) return ""
        if (gpu.switching) return "переключается…"
        switch (gpu.state) {
        case "off": return "NVIDIA выключена"
        case "suspended": return "NVIDIA спит"
        case "active":
            return nv && nv.load !== undefined
                ? "NVIDIA " + nv.load + "% · " + Math.round(nv.power) + " Вт · " + nv.temp + " °C"
                : "NVIDIA работает"
        case "missing": return "NVIDIA без драйвера"
        default: return gpu.state
        }
    }
}
