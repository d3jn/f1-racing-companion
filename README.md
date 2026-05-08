<p align="center">
  <img src="assets/logo.png" alt="Project Logo" width="128">
</p>

# F1 Racing Companion

F1 25 telemetry overlay that shows you all the info you will ever need. The goal of the project was to give driver real-time data in a compact and uniformed manner.

I race in VR and I don't like having all those extra overlays or even in-game ones. This one tiny black-box should replace them all and serve you as a silent and trusty race engineer.

## Overview

The overlay listens to UDP telemetry packets from F1 25 and displays real-time race information:

- **Live race data** — weather, your tire wear with a laps-left projection, ERS level/mode with per-lap battery deltas, and standings with deltas relative to your car. Standings also include front-wing damage, penalties, tire compound and wear, so that you know exactly what is going on around you.
- **Pit projection** — where you come out after a stop and how much of clean air there will be (and how close the next car will be to you) based on the expected pit loss and unserved SG penalties. Per-track pit losses are configurable in `settings.json` if you have your own measurements for your league or want to add a buffer for slower stops, damage repairs and so on (default values are rough estimates so trust them at your own risk).
- **Sectors & stint pace** — fastest S1/S2/S3 across all cars' last 3 laps split by tire compound (handy in mixed conditions to spot when slicks have crossed over wets, or the other way around), plus a pace-and-wear comparison table for the leader, the car ahead of you, you, and the car behind you.

## Installation

If you are on Windows then download an existing release containing the exe file and create `settings.json` file next to it (you can use the one supplied with the repository as a good starting point). 

If you want to run/build from source then clone the repository and:
* run: `main.py` directly with Python;
* build: `pyinstaller --onefile --noconsole --icon=assets/icon.ico main.py` and take the resulting standalone executable from `/dist` directory.

## Configuration

All the settings are read from `settings.json` placed next to `main.py` (or next to the executable, if you built one). The file is optional — if it's missing the app starts with built-in defaults; if it exists but isn't valid JSON (or isn't an object), defaults are used too and a warning is printed to stderr. Example:

```json
{
    "udp_port": 20777,
    "borderless": false,
    "always_on_top": false,
    "opacity": 1,
    "log_laps": false,
    "width": 53,
    "height": 18,
    "auto_size": false,
    "font_size": 9,
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

- **`log_laps`** (boolean, optional): When `true`, every completed player lap (in/out laps included, incomplete ones skipped) is appended to a CSV under `laps/`. Filenames are `YYYY_MM_DD_<trackslug>_<session>_NNNN.csv` where session is one of `practice`, `qualifying`, `sprint_shootout`, `race`, `time_trial` and `NNNN` is the smallest unused 4-digit number for that key. A new file is created each time telemetry starts (and again if it stalls for more than ~10s, or if the session/track changes mid-stream). Columns are: lap time `MM:SS.mmm`, lap time in seconds, tire compound (`SOF`/`MED`/`HAR`/`INT`/`WET`), fuel on lap start (kg), tire wear on lap start (%, worst corner), tire wear delta over the lap, fuel consumption delta over the lap (positive = burned), and ERS used (% of full pack deployed during the lap). Default is `false`.

- **`width`** / **`height`** (integers, optional): Inner content area of the overlay's bordered box, in characters and rows. Defaults are `53` and `18` — sized to fit the busiest page (page 1: persistent header + player tire/ERS + 11-car standings) without truncation. The bordered frame adds 2 to each (so the actual window is `width+2` × `height+2`). Lines from a renderer that exceed `width` are hard-cropped at the right edge; rendering fewer lines than `height` pads the rest with blanks. Going below the natural content widths will chop columns — page-1 standings rows are 53 chars, the page-3 pace table is ~49, the page-3 sector table and page-2 weather forecast both ~45. If your sessions tend to have long weather forecasts (20+ samples) you can bump `height` so page 2 doesn't truncate the trailing rows. Ignored when `auto_size` is `true`.

- **`auto_size`** (boolean, optional): When `true`, the box wraps exactly around whatever the current page rendered — no padding to a fixed grid, so the window resizes itself as you flip between pages. `width`/`height` are ignored in this mode. Default is `false` (use the fixed `width`×`height` grid).

- **`font_size`** (integer, optional): Tk point size for the Consolas font used by the overlay. Default is `9`. Larger values make the whole window bigger because the box is sized in characters/rows; pair with adjusted `width`/`height` if you need both to scale.

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

### Persistent header (all pages)

Two rows showing **gap, tire, wear, battery, and ERS mode** for the cars directly ahead of and behind you sit above the active page's content on every page, followed by a blank separator. They stay put as you flip between pages so you never lose sight of who you're racing. The header is hidden when the data isn't applicable: non-race sessions, the very start of a race (formation/lap-1 grid view), and after the player retires.

In non-race sessions (practice, qualifying, time trial) the overlay is intentionally trimmed: page 1 shows just the standings, page 2 shows just the weather forecast, and page 3 is empty. The persistent header, the player tire/ERS row, the pit projection, and the per-compound sector and pace tables all rely on race-only signals (gap-to-leader, lap counter, racing position dynamics) that don't behave the same way in those sessions, so they stay hidden until you're actually in a race.

### What's on each page

#### Page 1 — Live race data

- **Player tire row** — your current worst-corner wear with a laps-left projection. The projection extrapolates from the wear delta of your last clean full lap on the current compound, targeting 80% (past this value there is a chance of a puncture), and is shown alongside the laps remaining in the race so you can compare the two at a glance — e.g. `~15/20L left` means the tires should last another ~15 laps and the race has 20 to go (plenty of margin), `~5/20L left` means you'll need a stop. The race-laps figure subtracts your lap deficit to the leader, so a 2-lap-down driver sees a slightly smaller number — a deliberately conservative estimate that biases tire planning toward pitting earlier. The tire-laps half is hidden until a clean full lap on the current compound exists (e.g. lap 1 of the race or right after a pit); the race-laps half is hidden in time-based sessions where the game doesn't define a fixed lap count.
- **Player ERS row** — current battery state with two deltas:
  - `prev` — the battery change across the last completed lap.
  - `now` — the change since the most recent SF crossing. On lap 1 the baseline is the 100% race-start full battery; `prev` only appears once two SF-crossing samples are in the books.
- **Standings** — ±5 cars around your position with gap deltas relative to you, lap-down detection, and front-wing damage indicators.

#### Page 2 — Pit projection & weather

- **Pit projection** — where you'd come out after a stop, gap to who'd be ahead of and behind you afterwards, expected pit loss (green flag vs. SC/VSC depending on session state), and any pending penalties (drive-through, stop-go, time penalties, grid drops).
- **Weather forecast** — the upcoming weather samples from the game (rain probability, weather type, time offset), shown two slots per row to keep the table compact.

#### Page 3 — Sectors & stint pace (race sessions only)

- **Best sectors per compound** — fastest S1/S2/S3 across all cars' last 3 laps broken down by tire compound (SOF, MED, HAR, INT, WET).
  - Cells show an absolute time (e.g. `21.240`) when this compound is the fastest in that sector, otherwise a `+delta` to the column's best (e.g. `+0.250`), or `-` if no clean lap is registered on that compound for that sector.
  - Pit-lane segments are excluded — an in-lap doesn't count toward its S3 and an out-lap doesn't count toward its S1, so a slow trundle through pit lane can't sneak in as a sector time.
  - **`[!]` after a cell value** means that time was set on its holder's most recent instance of that sector — i.e., it's still hot. The instant the holder completes that sector again the indicator drops; if the new attempt is faster the cell value updates to it and `[!]` stays on.
  - **`*` after a compound label** marks each sector that compound is currently winning. `SOF***` means softs are fastest everywhere, `INT**` + `MED*` means inters own two sectors and meds the third — so a row gradually growing more stars as the track changes is your crossover signal.
- **Pace & wear** — a four-row comparison table for the leader, the car ahead of you, you, and the car behind you (rows are de-duplicated when you're on the boundary, e.g. when leading or running last). Each row shows:
  - **Pos** — current race position.
  - **Driver** — driver name (your own row is rendered as `------`).
  - **Cmp** — current tire compound.
  - **Wear** — current worst-corner wear, plus the average per-lap wear delta from this stint's last 3 clean laps in parens (e.g. `54%(+2.3%)`). The parenthesized delta only appears once at least one clean lap is recorded on the current tire set.
  - **AvgLap** — mean lap time across the last 3 clean laps of the current physical tire set, shown as `MM:SS.mmm`.
  - **ΔLap** — how much the recent pace has dropped off the stint's "optimal pace" baseline, so you can spot tire falloff and pit-window pressure. The baseline is locked in after the first 5 clean laps of the stint as the **double-trimmed mean** of those lap times (drop the fastest as a likely anomaly — perfect ERS deploy + clear air + DRS — and drop the slowest as a likely mistake/traffic, then average the remaining 3). It never updates after that, so as the stint progresses the delta naturally grows. The recent side compares the average of all post-baseline laps (up to the last 3 of them), so the column starts displaying from the 6th clean lap of the stint with a 1-sample reading, becomes 2-sample at lap 7, and reaches the full 3-sample average from lap 8 onwards. Rendered as `-` until at least one post-baseline lap is in.
  - In/out laps are excluded so pit traffic doesn't distort the averages. The history wipes whenever the tire age decreases (a fresh set has been fitted), the compound changes, or the lap counter jumps unexpectedly (e.g. session reset).

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
