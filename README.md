# F1 Racing Companion

A real-time Formula 1 telemetry overlay that connects to the F1 25 game via UDP and displays live race information.

## Overview

This overlay listens to UDP telemetry packets from F1 25 game and displays real-time information such as weather conditions, tire wear, ERS levels/mode, standings with deltas relative to the player and other race data (when it's available). It even has a very simple pit projection, but you need to test and adjust time lost in the pits first.

**Note:** This overlay was created for VR use and thus is not displayed in the borderless stay-on-top window itself.

## Installation

1. Clone the repository
2. Create a `settings.json` file in the root directory (see Configuration section)
3. Run `main.py` directly with Python or build it as an executable

## Configuration

Create a `settings.json` file in the project root with the following structure:

```json
{
    "udp_port": 20777,
    "borderless": false,
    "always_on_top": false,
    "smart_pit_projection": false,
    "drivers": [
        {
            "name": "DRIVER_NAME",
            "number": "1"
        },
        {
            "name": "ANOTHER_DRIVER",
            "number": "2"
        }
    ]
}
```

### Settings Keys

- **`udp_port`** (integer): The UDP port on which the overlay listens for telemetry packets. The default F1 game UDP port is `20777`.

- **`borderless`** (boolean): When `true`, hides the OS title bar so the overlay looks cleaner. You can still drag the window by holding left-click anywhere on the content. Default is `false`.

- **`always_on_top`** (boolean): When `true`, keeps the overlay window above other windows even when it loses focus. Default is `false`. Leave it off if you're compositing through SteamVR — the host handles z-ordering for you.

- **`smart_pit_projection`** (boolean): When `true`, the app records your pit stop times during the race and uses those measured values to refine the pit projection on page 2. When `false`, only the hardcoded baseline values are used. Default is `false`. This setting is experimental and requires a lot of clean stops to calibrate per track before it pays off, so leave it off unless you're willing to tune it across many sessions.

- **`drivers`** (array): A list of driver objects with custom names and numbers. This allows you to map custom display names to driver numbers for your league or session.
  - **`name`** (string): The display name for the driver
  - **`number`** (string): The driver number as used in the game

## Building

To create a standalone executable using PyInstaller:

```bash
pyinstaller --onefile --noconsole --icon=icon.ico main.py
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
