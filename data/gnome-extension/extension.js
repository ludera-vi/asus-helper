// Asus-helper в GNOME — то, что программа под Wayland сама сделать не может:
//  • карточки GNOME (OSD) при смене режима и яркости подсветки — программа зовёт ShowOSD по D-Bus
//    (в KDE это делает сам Plasma через org.kde.osdService);
//  • окно Asus-helper открывается в правом верхнем углу, под треем, а не посередине экрана
//    (в KDE это делает layer-shell).
import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const BUS_NAME = 'org.asushelper.Shell';
const PATH = '/org/asushelper/Shell';
const IFACE = `<node><interface name="org.asushelper.Shell">
  <method name="ShowOSD">
    <arg type="s" name="icon" direction="in"/>
    <arg type="s" name="label" direction="in"/>
    <arg type="d" name="level" direction="in"/>
  </method>
</interface></node>`;
const APP_ID = 'asus-helper';     // app_id окна (setDesktopFileName в программе)
const MARGIN = 8;                 // отступ от панели и края экрана, как у всплывающих меню

export default class AsusHelperExtension extends Extension {
    enable() {
        this._dbus = Gio.DBusExportedObject.wrapJSObject(IFACE, this);
        this._dbus.export(Gio.DBus.session, PATH);
        this._name = Gio.bus_own_name_on_connection(Gio.DBus.session, BUS_NAME,
            Gio.BusNameOwnerFlags.NONE, null, null);
        this._created = global.display.connect('window-created', (_d, win) => this._watch(win));
    }

    disable() {
        global.display.disconnect(this._created);
        Gio.bus_unown_name(this._name);
        this._dbus.unexport();
        this._dbus = null;
    }

    // level от 0 до 1 — полоска (яркость подсветки); меньше 0 — без полоски (режим)
    ShowOSD(icon, label, level) {
        Main.osdWindowManager.showOne(Main.layoutManager.primaryIndex, Gio.ThemedIcon.new(icon),
            label || null, level < 0 ? null : level, 1);
    }

    _watch(win) {
        const actor = win.get_compositor_private();
        if (!actor)
            return;
        // app_id и размер окна известны к первому кадру
        const id = actor.connect('first-frame', () => {
            actor.disconnect(id);
            if (win.get_wm_class() === APP_ID && win.get_window_type() === Meta.WindowType.NORMAL)
                this._place(win);
        });
    }

    _place(win) {
        const area = win.get_work_area_for_monitor(win.get_monitor());   // без верхней панели
        const frame = win.get_frame_rect();
        win.move_frame(true, area.x + area.width - frame.width - MARGIN, area.y + MARGIN);
        win.make_above();
    }
}
