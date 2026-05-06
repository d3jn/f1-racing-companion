<p align="center">
  <img src="assets/logo.png" alt="Project Logo" width="128">
</p>

# F1 Racing Companion

A real-time Formula 1 telemetry overlay that connects to the F1 25 game via UDP and displays live race information.

## Overview

This overlay listens to UDP telemetry packets from F1 25 game and displays real-time information such as weather conditions, tire wear, ERS levels/mode, standings with deltas relative to the player and other race data (when it's available). It even has a very simple pit projection, but you need to test and adjust time lost in the pits first.

## Installation

Download an existing release containing the exe file and create `settings.json` file next to it (you can use the one supplied with the repository as a good starting point). 

If you want to run/build from source:

1. Clone the repository
2. Run `main.py` directly with Python or build it as an executable

## Configuration

All the settings are read from `settings.json` file if it exists. Example:

```json
{
    "udp_port": 20777,
    "borderless": false,
    "always_on_top": false,
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

- **`drivers`** (array): A list of driver objects with custom names and numbers. This allows you to map custom display names to driver numbers for your league or session.
  - **`name`** (string): The display name for the driver
  - **`number`** (string): The driver number as used in the game

- **`pitstop_time_lost`** (object, optional): Per-track pit-loss times in seconds, used by pit projection. Keys are circuit slugs; values are objects with `pitstop_time` (green flag) and `sc_pitstop_time` (under safety car / VSC). Any track you don't list here falls back to the built-in defaults, so you only need to override the ones you've measured for your league. Available slugs: `melbourne`, `paul_ricard`, `shanghai`, `sakhir`, `catalunya`, `monaco`, `montreal`, `silverstone`, `hockenheim`, `hungaroring`, `spa_francorchamps`, `monza`, `marina_bay`, `suzuka`, `yas_marina`, `austin`, `interlagos`, `red_bull_ring`, `sochi`, `mexico_city`, `baku`, `sakhir_short`, `silverstone_short`, `austin_short`, `suzuka_short`, `hanoi`, `zandvoort`, `imola`, `portimao`, `jeddah`, `miami`, `las_vegas`, `losail`.

## Building

To create a standalone executable using PyInstaller:

```bash
pyinstaller --onefile --noconsole --icon=assets/icon.ico main.py
```

This will generate an executable in the `dist/` directory that can be run without requiring Python to be installed.

### Build Requirements

- Python 3.7+
- PyInstaller: `pip install pyinstaller`

## Usage

1. Start the overlay application
2. Launch your F1 game
3. Enable UDP telemetry in game settings
4. The overlay will display real-time telemetry information
5. You can switch between pages using in-game UDP Action 1 and UDP Action 2

## Files

- `main.py` - Main application source code
- `settings.json` - Configuration file (excluded from version control)
- `icon.ico` - Application icon for the executable

## License

See LICENSE file for details.
