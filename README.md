# Asus-helper

**English · [Русский](README.ru.md)**

**Your ASUS ROG / TUF laptop on Linux — as easy as G-Helper on Windows.** 

Performance profiles, fans, power limits, turning NVIDIA off without a reboot, keyboard lighting, the Slash
light bar on the lid and the battery — all in one tidy window next to the tray. No terminal, no reboots,
no pile of separate tools. English and Russian interface.

> **Works well on:** **KDE Plasma 6**, **GNOME** and **niri** on **Arch Linux and derivatives**
> (CachyOS, EndeavourOS, Manjaro, Garuda). How it fits into each desktop — see [Desktops](#desktops).
>
> **Still in development:** other desktops (Hyprland, Sway, COSMIC…) and other distributions
> (Fedora, openSUSE, Ubuntu). The daemon and `asus-helper-cli` already work on any system with systemd;
> the window and tray icon are polished for KDE, GNOME and niri so far.

Asus-helper replaces `asusctl` / `asusd`, `rog-control-center`, `supergfxctl` and `power-profiles-daemon` —
no need to install them separately.

## Features

| | |
|---|---|
| **Profiles** | Quiet / Balanced / Turbo — with a click, with Fn+F5, or automatically by power source: Balanced on AC, Quiet on battery (changeable). Your desktop sees the profile: KDE battery widget, GNOME power menu, noctalia bar, a pop-up when it changes |
| **Fans and power** | your own CPU and GPU fan curve for every profile — just drag the points; the BIOS factory curves are always at hand. On the *Power and CPU* page — PL1/PL2 limits, NVIDIA Dynamic Boost and temperature limit, EPP, Turbo Boost |
| **GPU** | **Eco** — NVIDIA fully off (longer battery life), **Standard** — hybrid, **Auto** — on with the charger, off without it. All without a reboot and without logging out |
| **Display** | refresh rate: Auto (60 Hz on battery, maximum on AC) / 60 / 240 Hz, panel Overdrive |
|  **Keyboard** | brightness (the keys show a pop-up too), Aura effects, color and speed, turns off when you're not typing, when to light up (at boot, in sleep…) |
| **Lid (Slash)** | brightness, 15 animations, static light, battery level; whether to light up on battery and with the lid closed |
| **Battery** | charge limit (e.g. 80 % for a long battery life), charts of temperature, fans and drain, charge over 24 h, battery health by day |
| **Appearance** | in KDE — *system* (KDE colors and style) or *original* — our own dark theme in the spirit of G-Helper; in niri with noctalia — *system* follows the noctalia theme (palette, light/dark) live, or original; in GNOME and other desktops — original |
| **Little things** | the ROG key above the keyboard opens the window; tray icon: color — profile, purple dot — NVIDIA is working |

**No model lists.** Asus-helper finds out what your particular laptop can do (from the kernel and its
devices) and shows only that — no useless buttons. Tested on **ROG Zephyrus G16 GU605MZ** (Core Ultra 9 +
RTX 4080) with KDE Plasma, GNOME and niri (noctalia).

### The GPU in plain words

- **Eco** — NVIDIA is completely off, everything runs on the integrated GPU. Quieter, cooler, and the
  battery lasts noticeably longer. Switching takes a couple of seconds.
- **Standard** — both GPUs are on; games and heavy programs use NVIDIA by themselves.
- **Auto** — don't think about it: plug in the charger — NVIDIA turns on, unplug it — it turns off.

What if something is running on NVIDIA right then (a game, DaVinci Resolve)? **Nothing is closed
silently.** A notification asks: *Close and turn off* or *Wait*. Choose wait — the tile dims and says
"waiting: resolve", and once you finish and close the program, the GPU turns off by itself.

## Installation

You need: an ASUS laptop (ROG, TUF, Zephyrus, Strix, Flow…), Arch or a derivative, KDE Plasma 6, GNOME or
niri.
To turn NVIDIA off — the `nvidia-open` (or `nvidia`) driver and MUX in hybrid mode (the default).

```bash
git clone https://github.com/ludera-vi/asus-helper
cd asus-helper
./install.sh
```

The installer does everything itself and explains every step in plain words:

- asks for the language (and the window appearance if you're on KDE; on niri with noctalia the window takes
  the noctalia theme by itself);
- finds out your desktop and from then on talks only about it;
- offers to install missing packages and to remove programs that do the same job (`asusctl`,
  `power-profiles-daemon`…) — and remembers what it changed, so uninstalling brings it all back;
- offers a snapper snapshot if you have snapper set up;
- imports your `asusctl` settings if there were any (curves, lighting, profiles);
- shows at the end what it found on the laptop.

**After the first install, log out and back in once.** The desktop started before the install and holds
NVIDIA; after logging in again it runs on the integrated GPU, and Eco turns NVIDIA off instantly. The
installer offers to log out right away. If your login screen is SDDM on X11, a reboot is needed instead —
the installer says so and offers it (see [Login screen](#login-screen)).

What the installer sets up for your particular desktop is described in [Desktops](#desktops).

An AUR package is ready (`packaging/aur/PKGBUILD`) and will be published once AUR registration reopens.

## Desktops

Everything the laptop can do works the same everywhere: the daemon does not depend on the desktop. What
differs is how the window, the tray icon, the pop-ups and the GPU setting fit into each desktop. The
installer finds out which one you have and sets up only that.

### KDE Plasma 6

- **Tray and window**: the icon is in the Plasma tray; the window opens next to it on the panel's side (top
  or bottom) and closes on Esc or a click outside.
- **Appearance**: *System* — KDE colors and style (`qqc2-desktop-style`), or *Original*.
- **Pop-ups**: the regular Plasma cards when the profile or keyboard brightness changes; the battery widget
  shows and switches the profile.
- **ROG key**: registered in *System Settings → Shortcuts → "Open Asus-helper"*, change it there.
- **Refresh rate**: switched through KDE (kscreen) and kept after a reboot.
- **GPU**: KWin runs on the integrated GPU (`/run/asus-helper/kwin.env` for `plasma-kwin_wayland.service`),
  so Eco works without logging out. Needed once: log out and back in after the first install.

### GNOME

- **Tray**: GNOME has no tray of its own — the installer installs and enables the AppIndicator extension.
- **Asus-helper extension** (installed and enabled as well): GNOME-style pop-ups for the profile and keyboard
  brightness, and the window opens top-right under the tray; it can be dragged by its header.
- **Appearance**: *Original*.
- **ROG key**: *Settings → Keyboard → Custom Shortcuts → "Open Asus-helper"*.
- **Power menu**: GNOME's power mode menu shows and switches the profile.
- **Refresh rate**: in GNOME settings. The window's *Display* section (refresh rate, Overdrive) appears on KDE
  and niri; here Overdrive is available with `asus-helper-cli`.
- **GPU**: GNOME and the GDM login screen run on the integrated GPU (a udev tag `mutter-device-ignore` on
  NVIDIA and an environment for gnome-shell), so Eco works without logging out. Monitors connected to
  NVIDIA outputs do not work in this mode. Needed once: log out and back in after the install — GNOME
  also loads the extensions then.

### niri

- **Tray and window**: the icon is in the bar tray (noctalia, or waybar with the tray module); the window
  opens next to it under the bar and closes on Esc or a click outside — with `focus-follows-mouse` too.
- **Appearance**: with noctalia, *System* follows the noctalia theme live — color scheme, wallpaper colors,
  light and dark. A noctalia template (`~/.config/noctalia/asus-helper.toml`) writes the colors and the
  window repaints itself. Or *Original*.
- **Pop-ups**: keyboard brightness — the noctalia card; profile change — a short notification. The noctalia
  bar shows and switches the profile.
- **ROG key**: the `binds` in `~/.config/niri/asus-helper.kdl` — yours to change.
- **Refresh rate**: through `niri msg`; niri keeps it until you log out, *Auto* sets it again.
- **GPU**: niri does not open NVIDIA (`/run/asus-helper/niri.kdl` with `debug { ignore-drm-device }`) and its
  OpenGL runs on the integrated GPU (`/run/asus-helper/niri.env` for `niri.service`), so Eco works without
  logging out, and niri does not take the card back after it is turned on. Programs started from niri use
  the integrated GPU as well; for NVIDIA use `prime-run` (in Steam: `prime-run %command%`). Monitors
  connected to NVIDIA outputs do not work in this mode. Needed once: log out and back in after the install.
- **Your niri config**: two `include optional=true` lines are added to the end of
  `~/.config/niri/config.kdl` (a backup `config.kdl.asus-helper.bak` is kept next to it); `./uninstall.sh`
  removes them. Without the daemon or without NVIDIA niri works as usual.

### Login screen

- **SDDM on X11** (often with KDE and niri): the login screen uses only the GPU that drives the display
  (`/etc/sddm.conf.d/asus-helper.conf`). Otherwise its Xorg takes NVIDIA as a second GPU and keeps it busy
  in the background for the whole session: Eco cannot turn the card off, and the session could be closed
  when the card changes state. It takes effect after one reboot — the installer offers it.
- **GDM**: see GNOME above.

## Usage

- **Tray icon**: left click — window, right click — quick menu (profiles, Eco). The icon color is the
  profile (Quiet green, Balanced blue, Turbo red), a purple dot — NVIDIA is working.
- **The ROG key** above the keyboard opens the window. No such key? Assign any:
  KDE — *System Settings → Shortcuts → "Open Asus-helper"*,
  GNOME — *Settings → Keyboard → Custom Shortcuts → "Open Asus-helper"*,
  niri — the `binds` in `~/.config/niri/asus-helper.kdl`.
- **Language** — the RU / EN switch at the bottom of the window. **Appearance** (KDE, niri with noctalia) — next to it: "System" or "Original".
- **Games on NVIDIA**: in Standard programs use NVIDIA by themselves; for old OpenGL games —
  `prime-run program` (in Steam: launch options `prime-run %command%`).
- **Terminal**: `asus-helper-cli` — status, `asus-helper-cli --help` — all commands.

## Updating and uninstalling

```bash
git pull && ./install.sh --update     # update: no questions, everything restarts by itself
./uninstall.sh                        # uninstall
```

Uninstalling brings the laptop back to how it was: factory power limits and fan curves, NVIDIA on. It also
offers to bring back the programs the installer removed (e.g. `power-profiles-daemon`) and to remove the
packages it installed. `./uninstall.sh --keep-config` — uninstall but keep the settings.

## If something is wrong

- **No icon on GNOME** — log out and back in (GNOME loads extensions at login). Make sure the AppIndicator
  extension is on: *Extensions → AppIndicator and KStatusNotifierItem Support*.
- **Eco says the desktop runs on NVIDIA** — one log out and back in is needed (see above).
- **Eco says Xorg holds NVIDIA** (SDDM login screen on X11) — one reboot is needed, see
  [Login screen](#login-screen).
- **No icon on niri** — your bar needs a tray: noctalia has one, in waybar add the `tray` module.
- **"The NVIDIA driver hung, a reboot is needed"** — this occasionally happens with the NVIDIA driver if it
  is switched at an unlucky moment. Asus-helper notices it and doesn't hang along with it — just reboot.
- **The daemon doesn't start** — most likely `asusd` (from `asusctl`) is running: two daemons would fight
  over the fans. `sudo pacman -Rns asusctl`, or run `./install.sh` again — it offers to remove it itself.
- **Anything else** — open an [issue](https://github.com/ludera-vi/asus-helper/issues) and attach the output
  of `asus-helper-cli diag` and `journalctl -u asus-helperd -b`. Thank you — it helps a lot!

## How it works (for the curious)

```
asus-helperd (root, systemd)   — the only one writing to sysfs and HID; D-Bus org.asushelper.Daemon
  ├─ profiles, curves, limits, EPP, Turbo Boost, AC/battery automation, restore after sleep
  ├─ GPU: close programs on it (after asking) → remove from the PCI bus → dgpu_disable (like Eco in
  │   G-Helper) → unload the driver if possible; every kernel step has a time limit
  ├─ Aura and Slash over HID (protocols from G-Helper), charge limit, sensor history
  └─ answers the desktop in place of power-profiles-daemon (battery widget, Fn+F5)
asus-helper (Qt/QML, session)  — tray icon, window next to the tray, KDE / GNOME / noctalia pop-ups, refresh rate
asus-helper-cli                — the same from a terminal
```

Permissions go through polkit: whoever sits at the laptop needs no password. Daemon log:
`journalctl -u asus-helperd -f`.

To turn NVIDIA off without logging out, the desktop runs on the integrated GPU: at boot the daemon decides
whether that is safe (NVIDIA present, MUX in hybrid mode) and only then writes a setting for KWin
(`/run/asus-helper/kwin.env`), for GNOME and the GDM login screen (`/run/asus-helper/gnome.env` and a udev
rule) or for niri (`/run/asus-helper/niri.kdl` with `debug { ignore-drm-device }` and `niri.env`). Without NVIDIA, with MUX in "NVIDIA only" mode or without the daemon nothing changes.

## For developers

```bash
make test                          # tests on a fake sysfs, hardware is not touched
sudo ./dev-run.sh                  # daemon from the source tree in a terminal
python3 -m asushelper.app --show   # window from the source tree
python3 -m tests.hw_check --gpu    # full check of every feature on a real laptop
```

Translations: `asushelper/i18n/en.json` (Russian string → English). Pull requests and bug reports are very
welcome.

## Author, credits and license

Author — **Gunichev Ivan** ([@ludera-vi](https://github.com/ludera-vi)).

The Aura lighting and Slash protocols and the profile logic come from
[G-Helper](https://github.com/seerge/g-helper) (seerge, GPL-3.0) — a huge thank you!

Asus-helper is licensed under [GPL-3.0-or-later](LICENSE).
