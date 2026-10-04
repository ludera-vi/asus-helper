# Asus-helper

**English · [Русский](README.ru.md)**

**Your ASUS ROG / TUF laptop on Linux — as easy as G-Helper on Windows.** 

Performance profiles, fans, power limits, turning NVIDIA off without a reboot, keyboard lighting, the Slash
light bar on the lid and the battery — all in one tidy window next to the tray. No terminal, no reboots,
no pile of separate tools. English and Russian interface.

> **Works well on:** **KDE Plasma 6** and **GNOME** on **Arch Linux and derivatives**
> (CachyOS, EndeavourOS, Manjaro, Garuda).
>
> **Still in development:** 🛠 other desktops (Hyprland, niri, Sway, COSMIC…) and other distributions
> (Fedora, openSUSE, Ubuntu). The daemon and `asus-helper-cli` already work on any system with systemd;
> the window and tray icon are polished for KDE and GNOME so far.

Asus-helper replaces `asusctl` / `asusd`, `rog-control-center`, `supergfxctl` and `power-profiles-daemon` —
no need to install them separately.

## Features

| | |
|---|---|
| **Profiles** | Quiet / Balanced / Turbo — with a click, with Fn+F5, or automatically by power source: Balanced on AC, Quiet on battery (changeable). Your desktop sees the profile: KDE battery widget, GNOME menu, a pop-up when it changes |
| **Fans and power** | your own CPU and GPU fan curve for every profile — just drag the points; the BIOS factory curves are always at hand. On the *Power and CPU* page — PL1/PL2 limits, NVIDIA Dynamic Boost and temperature limit, EPP, Turbo Boost |
| **GPU** | **Eco** — NVIDIA fully off (longer battery life), **Standard** — hybrid, **Auto** — on with the charger, off without it. All without a reboot and without logging out |
| **Display** | refresh rate: Auto (60 Hz on battery, maximum on AC) / 60 / 240 Hz, panel Overdrive |
|  **Keyboard** | brightness (the keys show a pop-up too), Aura effects, color and speed, turns off when you're not typing, when to light up (at boot, in sleep…) |
| **Lid (Slash)** | brightness, 15 animations, static light, battery level; whether to light up on battery and with the lid closed |
| **Battery** | charge limit (e.g. 80 % for a long battery life), charts of temperature, fans and drain, charge over 24 h, battery health by day |
| **Appearance** | in KDE — *system* (KDE colors and style) or *original* — our own dark theme in the spirit of G-Helper; in GNOME and other desktops — original |
| **Little things** | the ROG key above the keyboard opens the window, boot sound; tray icon: color — profile, purple dot — NVIDIA is working |

**No model lists.** Asus-helper finds out what your particular laptop can do (from the kernel and its
devices) and shows only that — no useless buttons. Tested on **ROG Zephyrus G16 GU605MZ** (Core Ultra 9 +
RTX 4080) with KDE Plasma and GNOME.

### The GPU in plain words

- **Eco** — NVIDIA is completely off, everything runs on the integrated GPU. Quieter, cooler, and the
  battery lasts noticeably longer. Switching takes a couple of seconds.
- **Standard** — both GPUs are on; games and heavy programs use NVIDIA by themselves.
- **Auto** — don't think about it: plug in the charger — NVIDIA turns on, unplug it — it turns off.

What if something is running on NVIDIA right then (a game, DaVinci Resolve)? **Nothing is closed
silently.** A notification asks: *Close and turn off* or *Wait*. Choose wait — the tile dims and says
"waiting: resolve", and once you finish and close the program, the GPU turns off by itself.

## Installation

You need: an ASUS laptop (ROG, TUF, Zephyrus, Strix, Flow…), Arch or a derivative, KDE Plasma 6 or GNOME.
To turn NVIDIA off — the `nvidia-open` (or `nvidia`) driver and MUX in hybrid mode (the default).

```bash
git clone https://github.com/ludera-vi/asus-helper
cd asus-helper
./install.sh
```

The installer does everything itself and explains every step in plain words:

- asks for the language (and the window appearance if you're on KDE);
- finds out your desktop and from then on talks only about it;
- offers to install missing packages and to remove programs that do the same job (`asusctl`,
  `power-profiles-daemon`…) — and remembers what it changed, so uninstalling brings it all back;
- offers a snapper snapshot if you have snapper set up;
- imports your `asusctl` settings if there were any (curves, lighting, profiles);
- shows at the end what it found on the laptop.

**After the first install, log out and back in once.** The desktop started before the install and holds
NVIDIA; after logging in again it runs on the integrated GPU, and Eco turns NVIDIA off instantly. The
installer offers to log out right away.

**On GNOME** the top bar needs a tray — the installer installs and enables the AppIndicator extension, plus
a small Asus-helper extension (profile and lighting pop-ups, the window opens under the tray). They start
working after that one new login.

An AUR package is ready (`packaging/aur/PKGBUILD`) and will be published once AUR registration reopens.

## Usage

- **Tray icon**: left click — window, right click — quick menu (profiles, Eco). The icon color is the
  profile (Quiet green, Balanced blue, Turbo red), a purple dot — NVIDIA is working.
- **The ROG key** above the keyboard opens the window. No such key? Assign any:
  KDE — *System Settings → Shortcuts → "Open Asus-helper"*,
  GNOME — *Settings → Keyboard → Custom Shortcuts → "Open Asus-helper"*.
- **Language** — the RU / EN switch at the bottom of the window. **Appearance** (KDE) — the button next to it.
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
- **"The NVIDIA driver hung, a reboot is needed"** — this occasionally happens with the NVIDIA driver if it
  is switched at an unlucky moment. Asus-helper notices it and doesn't hang along with it — just reboot.
- **The daemon doesn't start** — most likely `asusd` (from `asusctl`) is running: two daemons would fight
  over the fans. `sudo pacman -Rns asusctl`, or run `./install.sh` again — it offers to remove it itself.
- **Anything else** — open an [issue](https://github.com/ludera-vi/asus-helper/issues) and attach the output
  of `asus-helper-cli diag` and `journalctl -u asus-helperd -b`. Thank you — it helps a lot! 🙏

## How it works (for the curious)

```
asus-helperd (root, systemd)   — the only one writing to sysfs and HID; D-Bus org.asushelper.Daemon
  ├─ profiles, curves, limits, EPP, Turbo Boost, AC/battery automation, restore after sleep
  ├─ GPU: close programs on it (after asking) → remove from the PCI bus → dgpu_disable (like Eco in
  │   G-Helper) → unload the driver if possible; every kernel step has a time limit
  ├─ Aura and Slash over HID (protocols from G-Helper), charge limit, sensor history
  └─ answers the desktop in place of power-profiles-daemon (battery widget, Fn+F5)
asus-helper (Qt/QML, session)  — tray icon, window next to the tray, KDE / GNOME pop-ups, refresh rate
asus-helper-cli                — the same from a terminal
```

Permissions go through polkit: whoever sits at the laptop needs no password. Daemon log:
`journalctl -u asus-helperd -f`.

To turn NVIDIA off without logging out, the desktop runs on the integrated GPU: at boot the daemon decides
whether that is safe (NVIDIA present, MUX in hybrid mode) and only then writes a setting for KWin
(`/run/asus-helper/kwin.env`) or for GNOME and the GDM login screen (`/run/asus-helper/gnome.env` and a udev
rule). Without NVIDIA, with MUX in "NVIDIA only" mode or without the daemon nothing changes.

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
