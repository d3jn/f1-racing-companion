<p align="center">
  <img src="assets/logo.png" alt="Project Logo" width="128">
</p>

# F1 Racing Companion

A real-time Formula 1 telemetry overlay that connects to the F1 25 game via UDP and displays live race information.

## Overview

This overlay listens to UDP telemetry packets from F1 25 game and displays real-time information such as weather conditions, tire wear and degradation, ERS levels/mode/harvest, standings with deltas relative to the player and other race data (when it's available). It also has a simple pit projection on its own page — the time lost in the pits is configurable per track in `settings.json` if you have your own measurements or want to add some buffer time to account for slower stops, damage repairs etc (default values are my rough estimates so trust them on your own risk). And there's a separate per-compound sector-times page meant for mixed conditions — it shows the fastest S1/S2/S3 across all cars' last 3 laps split by tire compound, so you can see at a glance when slicks have crossed over wets (or the other way around).

## Installation

If you are on Windows then download an existing release containing the exe file and create `settings.json` file next to it (you can use the one supplied with the repository as a good starting point). 

If you want to run/build from source then clone the repository and:
* run: `main.py` directly with Python;
* build: `pyinstaller --onefile --noconsole --icon=assets/icon.ico main.py` and take the resulting standalone executable from `/dist` directory.

## Configuration

All the settings are read from `settings.json` placed next to `main.py` (or next to the executable, if you built one). The file is required — the app won't start without it. Example:

```json
{
    "udp_port": 20777,
    "borderless": false,
    "always_on_top": false,
    "opacity": 1,
    "drivers": [
        {
            "name": "DRIVER_NAME",
            "number": "1"
        },
        {
            "name": "ANOTHER_DRIVER",
            "number": "2"
        }
    ],
    "pitstop_time_lost": {
        "monaco":            {"pitstop_time": 17, "sc_pitstop_time": 12},
        "spa_francorchamps": {"pitstop_time": 20, "sc_pitstop_time": 14},
        "monza":             {"pitstop_time": 25, "sc_pitstop_time": 17}
    }
}
```

### Settings Keys

- **`udp_port`** (integer): The UDP port on which the overlay listens for telemetry packets. The default F1 game UDP port is `20777`.

- **`borderless`** (boolean): When `true`, hides the OS title bar so the overlay looks cleaner. You can still drag the window by holding left-click anywhere on the content. Default is `false`.

- **`always_on_top`** (boolean): When `true`, keeps the overlay window above other windows even when it loses focus. Default is `false`. Leave it off if you're compositing through SteamVR — the host handles z-ordering for you.

- **`opacity`** (number, optional): Whole-window opacity from 0 to 1, applied only when `borderless` is `true`. Affects text as well as background. Default is `1` (fully opaque), `0.5` will be 50% and so on. Values outside `(0, 1]` or non-numeric are ignored and treated as `1`.

- **`drivers`** (array): A list of driver objects with custom names and numbers. This allows you to map custom display names to driver numbers for your league or session.
  - **`name`** (string): The display name for the driver
  - **`number`** (string): The driver number as used in the game

- **`pitstop_time_lost`** (object, optional): Per-track pit-loss times in seconds, used by pit projection. Keys are circuit slugs; values are objects with `pitstop_time` (green flag) and `sc_pitstop_time` (under safety car / VSC). Any track you don't list here falls back to the built-in defaults, so you only need to override the ones you've measured for your league. Available slugs: `melbourne`, `paul_ricard`, `shanghai`, `sakhir`, `catalunya`, `monaco`, `montreal`, `silverstone`, `hockenheim`, `hungaroring`, `spa_francorchamps`, `monza`, `marina_bay`, `suzuka`, `yas_marina`, `austin`, `interlagos`, `red_bull_ring`, `sochi`, `mexico_city`, `baku`, `sakhir_short`, `silverstone_short`, `austin_short`, `suzuka_short`, `hanoi`, `zandvoort`, `imola`, `portimao`, `jeddah`, `miami`, `las_vegas`, `losail`.

### Build Requirements

- Python 3.7+
- PyInstaller: `pip install pyinstaller`

## Usage

1. Start the overlay application.
2. Launch F1 25.
3. In the game settings turn on UDP telemetry and make sure its UDP port matches the one in `settings.json` (default `20777`).
4. Bind **UDP Action 1** and **UDP Action 2** in the game's controls — those are the buttons you'll use to flip between the overlay's pages. They aren't bound to anything by default.
5. The overlay will start filling in once the game pushes its first session and lap packets.

### What's on each page

- **Page 1** — gap, tyre, wear, battery and ERS mode for the cars directly ahead and behind you, your own tyre wear with a degradation rate and laps-left estimate (until 80% because past this value there is a chance of having a puncture), your ERS state with this-lap harvest/deploy net, and a standings list of ±5 cars around your position.
- **Page 2** — pit projection (where you'd come out, gap to who'd be ahead/behind you after the stop, expected pit loss, any pending penalties) and the weather forecast samples coming from the game.

### Window controls

- **Drag** — when `borderless` is on, hold left-click anywhere on the content and move the window around.
- **Right-click** — opens a small context menu with an `Exit` option.
- **In-game buttons** — UDP Action 1 / 2 cycle to the next / previous page.

## Files

- `main.py` — main application source code
- `settings.json` — configuration file (a working example is committed in the repo)
- `assets/icon.ico` — application icon used by the build command
- `assets/logo.png` — project logo
- `specs/` — F1 25 telemetry packet structure reference

## Credits

* Claude for vibing.
* Me for having free time to vibecode this app and tailor it to my needs.

## License

See LICENSE file for details.
