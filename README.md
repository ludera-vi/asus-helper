# Asus-helper

**English · [Русский](README.ru.md)**

**ASUS ROG / TUF laptop control on Linux — like G-Helper, made for KDE Plasma.**
Performance profiles, fan curves, power limits, turning NVIDIA off (Eco) without a reboot, Aura keyboard
lighting and the Slash lid light bar, battery — in one window next to the tray. English and Russian UI.

Replaces `asusd` / `asusctl`, `rog-control-center`, `supergfxctl` and `power-profiles-daemon`.

## Features

| | |
|---|---|
| **Profile** | Quiet / Balanced / Turbo, Fn+F5, by power source (Balanced on AC, Quiet on battery — changeable); KDE sees the profile (battery widget, OSD on change) |
| **Fans and power** | custom CPU/GPU fan curve per profile (drag the points), BIOS factory curves of every profile; on the *Power and CPU* page — PL1/PL2, NVIDIA Dynamic Boost and temperature limit, EPP, Turbo Boost |
| **GPU** | **Eco** — NVIDIA turned off in BIOS without a reboot; **Standard** — hybrid; **Auto** — on with AC, off on battery (but not while a game or DaVinci uses it — it waits) |
| **Display** | Auto (60 Hz on battery, max on AC) / 60 / 240 Hz, panel Overdrive |
| **Keyboard** | brightness (KDE OSD for the keys too), Aura effects, color, speed, turns off when idle, when to light up |
| **Lid (Slash)** | brightness, 15 animations, static, battery level, light up on battery and with the lid closed |
| **Battery** | charge limit, charts of temperature, fans and drain, charge over 24 h, health by day |
| **Appearance** | *System* — KDE colors and style; *Original* — own dark theme in the spirit of G-Helper (also used automatically where the KDE style is missing) |
| **Other** | the ROG key opens the window, boot sound, tray icon: color — profile, dot — NVIDIA is active |

There are no model lists: everything the laptop has is detected from the kernel and HID devices, and the
window shows only that. Tested on **ROG Zephyrus G16 GU605MZ** (Core Ultra 9 + RTX 4080). What was found on
yours: `asus-helper-cli diag` — please attach its output to an issue if something does not work.

## Requirements

- ASUS laptop (ROG, TUF, Zephyrus, Strix, Flow…), kernel with `asus-wmi` (6.15+ with `asus-armoury` is best)
- KDE Plasma 6 on Wayland; Arch Linux or derivatives (CachyOS, EndeavourOS, Manjaro)
- For Eco: NVIDIA with the `nvidia` / `nvidia-open` driver, MUX in hybrid mode
- **Without** `asusctl`, `power-profiles-daemon`, `supergfxctl`, `envycontrol` — they do the same job

## Installation

```bash
git clone https://github.com/ludera-vi/asus-helper
cd asus-helper
./install.sh                  # checks the system, offers a snapper snapshot, installs into /usr/local
./install.sh --update         # update after git pull
./uninstall.sh                # remove everything, restore factory settings and reboot (--keep-config keeps settings)
```
The installer asks for the language (English / Русский) and the appearance (system or original). Settings
from `/etc/asusd` (curves, lighting, profiles) are imported on the first install.

**Log out once after the first install.** The desktop started before the install and runs on NVIDIA, so
Eco cannot turn it off yet; after logging out and back in KDE runs on the integrated GPU. The installer
offers to log out right away (the window shows a *Log out* button too).

An AUR package is ready (`packaging/aur/PKGBUILD`) and will be published once AUR registration reopens.

## Usage

- **Tray icon**: left click — window, right click — quick menu (profiles, Eco). Icon color — profile
  (Quiet green, Balanced blue, Turbo red), purple dot — NVIDIA is active.
- **ROG key** above the keyboard opens the window. Laptops without it: assign any key to *Open Asus-helper*
  in System Settings → Shortcuts.
- **Terminal**: `asus-helper-cli` — status; `asus-helper-cli --help` — all commands.
- **Language**: the RU / EN switch at the bottom of the window or `asus-helper-cli language ru`.
- **Appearance**: the button next to RU / EN — system or original; the window restarts.
- **Games on NVIDIA**: in Standard programs use NVIDIA by themselves; for old OpenGL games —
  `prime-run program` (in Steam: launch options `prime-run %command%`).

## How it works

```
asus-helperd (root, systemd)   — the only one writing to sysfs and HID; D-Bus org.asushelper.Daemon
  ├─ profiles, curves, limits, EPP, Turbo Boost, AC/battery automation, restore after sleep
  ├─ GPU: unload driver → remove from the PCI bus → dgpu_disable (like Eco in G-Helper)
  ├─ Aura and Slash over HID (protocols from G-Helper), charge limit, sensor history
  └─ answers KDE in place of power-profiles-daemon (battery widget, Fn+F5)
asus-helper (Qt/QML, session)  — tray icon, popup window (layer-shell), KDE OSD, display refresh rate
asus-helper-cli                — the same from a terminal
```

Permissions go through polkit: the user at the laptop needs no password. Log: `journalctl -u asus-helperd -f`.

To turn NVIDIA off without logging out, the KDE desktop runs on the integrated GPU: at boot the daemon
writes `/run/asus-helper/kwin.env` if NVIDIA is present and MUX is in hybrid mode; the KWin service reads it at
login. Without NVIDIA, with MUX in "NVIDIA only" mode or without the daemon nothing changes.

## Development

```bash
make test                          # tests on a fake sysfs, hardware is not touched
sudo ./dev-run.sh                  # daemon from the source tree in a terminal
python3 -m asushelper.app --show   # window from the source tree
python3 -m tests.hw_check --gpu    # full check of every feature on a real laptop
```
Translations: `asushelper/i18n/en.json` (Russian string → English).

## Credits and license

The Aura lighting and Slash protocols and the profile logic come from
[G-Helper](https://github.com/seerge/g-helper) (seerge, GPL-3.0) — thank you!
Asus-helper is licensed under [GPL-3.0-or-later](LICENSE).
