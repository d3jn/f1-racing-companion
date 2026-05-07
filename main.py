import socket
import struct
import threading
import queue
import tkinter as tk
import json
import os
import sys
import time
import csv

# F1 25 default UDP port
UDP_IP = "0.0.0.0"

if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))
_settings_path = os.path.join(_base_dir, "settings.json")

try:
    with open(_settings_path, "r") as _f:
        _settings = json.load(_f)
    if not isinstance(_settings, dict):
        print("Warning: settings.json is not a JSON object; using built-in defaults",
              file=sys.stderr)
        _settings = {}
except FileNotFoundError:
    _settings = {}
except (json.JSONDecodeError, OSError) as _e:
    print(f"Warning: could not read settings.json ({_e}); using built-in defaults",
          file=sys.stderr)
    _settings = {}


def _parse_opacity(value):
    if isinstance(value, bool):
        return 1.0
    if isinstance(value, (int, float)) and 0 < value <= 1:
        return float(value)
    return 1.0


def _parse_positive_int(value, default):
    if isinstance(value, bool):
        return default
    if isinstance(value, int) and value > 0:
        return value
    return default


UDP_PORT = _parse_positive_int(_settings.get("udp_port"), 20777)
BORDERLESS = bool(_settings.get("borderless", False))
ALWAYS_ON_TOP = bool(_settings.get("always_on_top", False))
OPACITY = _parse_opacity(_settings.get("opacity", 1.0))
LOG_LAPS = bool(_settings.get("log_laps", False))
PAGE_INNER_WIDTH = _parse_positive_int(_settings.get("width"), 53)
PAGE_INNER_HEIGHT = _parse_positive_int(_settings.get("height"), 23)
FONT_SIZE = _parse_positive_int(_settings.get("font_size"), 9)
AUTO_SIZE = bool(_settings.get("auto_size", False))


def _normalize_race_number(num):
    s = str(num).strip().lstrip("0")
    return s if s else "0"


_driver_name_map = {}
for _d in _settings.get("drivers", []):
    _key = _normalize_race_number(_d["number"])
    if _key in _driver_name_map:
        print(f"Warning: duplicate driver number '{_key}' in settings.json", file=sys.stderr)
    _driver_name_map[_key] = _d["name"]

PACKET_SESSION_DATA = 1
PACKET_LAP_DATA = 2
PACKET_EVENT = 3
PACKET_PARTICIPANTS = 4
PACKET_CAR_STATUS = 7
PACKET_CAR_DAMAGE = 10

NUM_CARS = 22

WEATHER_TYPES = {
    0: "S",
    1: "S+C",
    2: "C",
    3: "LR",
    4: "MR",
    5: "HR",
}

SESSION_TYPES = {
    0: "Unknown",
    1: "P1",
    2: "P2",
    3: "P3",
    4: "Short P",
    5: "Q1",
    6: "Q2",
    7: "Q3",
    8: "Short Q",
    9: "OSQ",
    10: "SS1",
    11: "SS2",
    12: "SS3",
    13: "Short SS",
    14: "OSS",
    15: "Race",
    16: "Race 2",
    17: "Race 3",
    18: "Time Trial",
}

# Quali (5-9), Sprint Shootout (10-14), Race (15-17) — others show placeholder.
ACTIVE_SESSION_TYPES = {5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17}
RACE_SESSION_TYPES = {15, 16, 17}

TEMP_CHANGE = {0: "up", 1: "down", 2: "no change"}

TYRE_COMPOUNDS = {16: "SOF", 17: "MED", 18: "HAR", 7: "INT", 8: "WET"}

ERS_MODES = {0: "None", 1: "Medium", 2: "Hotlap", 3: "Overtake"}

TYRE_NAMES = ["RL", "RR", "FL", "FR"]

ERS_MAX_ENERGY = 4_000_000  # 4 MJ in Joules
STOP_GO_PENALTY_SECONDS = 10
DRIVE_THROUGH_PENALTY_SECONDS = 20

# result_status from F1 spec: 0 invalid, 1 inactive, 2 active, 3 finished,
# 4 DNF, 5 DSQ, 6 not classified, 7 retired
RESULT_STATUS_INACTIVE = 1
RESULT_STATUS_ACTIVE = 2
RESULT_STATUS_FINISHED = 3
ACTIVE_STATUS_SET = {RESULT_STATUS_INACTIVE, RESULT_STATUS_ACTIVE, RESULT_STATUS_FINISHED}
RETIRED_STATUS_SET = {4, 5, 6, 7}

TELEMETRY_STALE_S = 2.0
TELEMETRY_VERY_STALE_S = 10.0

# Race-start grid view: player on lap 1 within this distance of the line
RACE_START_LAP_DISTANCE_M = 800

# Tyre wear projection target — laps-left is computed against this threshold
WEAR_TARGET_PCT = 80

# Per-track pit-loss baselines (green / safety car), in seconds.
# Real-world estimates; tune per league as needed.
PITSTOP_TIMES = {
    -1: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Unknown track — generic
     0: {"pitstop_time": 19, "sc_pitstop_time": 13},  # Melbourne       - Australian GP
     1: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Paul Ricard     - French GP (legacy)
     2: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Shanghai        - Chinese GP
     3: {"pitstop_time": 22, "sc_pitstop_time": 15},  # Sakhir          - Bahrain GP
     4: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Catalunya       - Spanish GP
     5: {"pitstop_time": 17, "sc_pitstop_time": 12},  # Monaco          - Monaco GP
     6: {"pitstop_time": 17, "sc_pitstop_time": 12},  # Montreal        - Canadian GP
     7: {"pitstop_time": 22, "sc_pitstop_time": 15},  # Silverstone     - British GP
     8: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Hockenheim      - German GP (legacy)
     9: {"pitstop_time": 19, "sc_pitstop_time": 13},  # Hungaroring     - Hungarian GP
    10: {"pitstop_time": 20, "sc_pitstop_time": 14},  # Spa-Francorchamps - Belgian GP
    11: {"pitstop_time": 25, "sc_pitstop_time": 17},  # Monza           - Italian GP
    12: {"pitstop_time": 26, "sc_pitstop_time": 18},  # Marina Bay      - Singapore GP
    13: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Suzuka          - Japanese GP
    14: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Yas Marina      - Abu Dhabi GP
    15: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Austin (COTA)   - US GP
    16: {"pitstop_time": 20, "sc_pitstop_time": 14},  # Interlagos      - Brazilian GP
    17: {"pitstop_time": 19, "sc_pitstop_time": 13},  # Red Bull Ring   - Austrian GP
    18: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Sochi           - Russian GP (legacy)
    19: {"pitstop_time": 22, "sc_pitstop_time": 15},  # Mexico City     - Mexican GP
    20: {"pitstop_time": 19, "sc_pitstop_time": 13},  # Baku            - Azerbaijan GP
    21: {"pitstop_time": 18, "sc_pitstop_time": 12},  # Sakhir Short
    22: {"pitstop_time": 18, "sc_pitstop_time": 12},  # Silverstone Short
    23: {"pitstop_time": 18, "sc_pitstop_time": 12},  # Austin Short
    24: {"pitstop_time": 18, "sc_pitstop_time": 12},  # Suzuka Short
    25: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Hanoi           - Vietnamese GP (legacy)
    26: {"pitstop_time": 17, "sc_pitstop_time": 12},  # Zandvoort       - Dutch GP
    27: {"pitstop_time": 27, "sc_pitstop_time": 18},  # Imola           - Emilia Romagna GP
    28: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Portimao        - Portuguese GP
    29: {"pitstop_time": 17, "sc_pitstop_time": 12},  # Jeddah          - Saudi Arabian GP
    30: {"pitstop_time": 19, "sc_pitstop_time": 13},  # Miami           - Miami GP
    31: {"pitstop_time": 19, "sc_pitstop_time": 13},  # Las Vegas       - Las Vegas GP
    32: {"pitstop_time": 21, "sc_pitstop_time": 14},  # Losail          - Qatar GP
}

# Slug → game track_id. Slugs are what users put in settings.json under
# `pitstop_time_lost`; track_id is what the F1 telemetry packet sends.
TRACK_SLUG_TO_ID = {
    "melbourne": 0,
    "paul_ricard": 1,
    "shanghai": 2,
    "sakhir": 3,
    "catalunya": 4,
    "monaco": 5,
    "montreal": 6,
    "silverstone": 7,
    "hockenheim": 8,
    "hungaroring": 9,
    "spa_francorchamps": 10,
    "monza": 11,
    "marina_bay": 12,
    "suzuka": 13,
    "yas_marina": 14,
    "austin": 15,
    "interlagos": 16,
    "red_bull_ring": 17,
    "sochi": 18,
    "mexico_city": 19,
    "baku": 20,
    "sakhir_short": 21,
    "silverstone_short": 22,
    "austin_short": 23,
    "suzuka_short": 24,
    "hanoi": 25,
    "zandvoort": 26,
    "imola": 27,
    "portimao": 28,
    "jeddah": 29,
    "miami": 30,
    "las_vegas": 31,
    "losail": 32,
}


def _build_effective_pit_times(user_dict):
    """Overlay `pitstop_time_lost` settings onto PITSTOP_TIMES, keyed by track_id."""
    effective = {tid: dict(values) for tid, values in PITSTOP_TIMES.items()}
    if not isinstance(user_dict, dict):
        if user_dict is not None:
            print("Warning: 'pitstop_time_lost' in settings.json must be an object",
                  file=sys.stderr)
        return effective
    for slug, values in user_dict.items():
        track_id = TRACK_SLUG_TO_ID.get(slug)
        if track_id is None:
            print(f"Warning: unknown track slug '{slug}' in pitstop_time_lost",
                  file=sys.stderr)
            continue
        if not isinstance(values, dict):
            print(f"Warning: pitstop_time_lost['{slug}'] must be an object",
                  file=sys.stderr)
            continue
        entry = effective.setdefault(track_id, dict(PITSTOP_TIMES[-1]))
        green = values.get("pitstop_time")
        sc = values.get("sc_pitstop_time")
        if isinstance(green, (int, float)):
            entry["pitstop_time"] = green
        if isinstance(sc, (int, float)):
            entry["sc_pitstop_time"] = sc
    return effective


_EFFECTIVE_PIT_TIMES = _build_effective_pit_times(_settings.get("pitstop_time_lost"))

# Reverse map: track_id -> slug, used by LapLogger for filenames.
TRACK_ID_TO_SLUG = {v: k for k, v in TRACK_SLUG_TO_ID.items()}


EVENT_CODE_BUTN = b"BUTN"
UDP_ACTION_1_MASK = 0x00100000
UDP_ACTION_2_MASK = 0x00200000

# PacketHeader: uint16 + uint8*5 + uint64 + float + uint32*2 + uint8*2
HEADER_FMT = "<HBBBBBQfIIBB"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 29

# Session fields before marshal zones:
# uint8 weather, int8 trackTemp, int8 airTemp, uint8 totalLaps, uint16 trackLength,
# uint8 sessionType, int8 trackId, uint8 formula, uint16 sessionTimeLeft,
# uint16 sessionDuration, uint8 pitSpeedLimit, uint8 gamePaused, uint8 isSpectating,
# uint8 spectatorCarIndex, uint8 sliProNativeSupport, uint8 numMarshalZones
PRE_MARSHAL_FMT = "<BbbBHBbBHHBBBBBB"
PRE_MARSHAL_SIZE = struct.calcsize(PRE_MARSHAL_FMT)

# MarshalZone: float zoneStart + int8 zoneFlag = 5 bytes
MARSHAL_ZONE_SIZE = struct.calcsize("<fb")  # 5

# After marshal zones: uint8 safetyCarStatus, uint8 networkGame, uint8 numWeatherForecastSamples
POST_MARSHAL_FMT = "<BBB"
POST_MARSHAL_SIZE = struct.calcsize(POST_MARSHAL_FMT)

# WeatherForecastSample: uint8 sessionType, uint8 timeOffset, uint8 weather,
#   int8 trackTemp, int8 trackTempChange, int8 airTemp, int8 airTempChange, uint8 rainPct
WEATHER_SAMPLE_FMT = "<BBBbbbbB"
WEATHER_SAMPLE_SIZE = struct.calcsize(WEATHER_SAMPLE_FMT)  # 8

# LapData per car
LAP_DATA_FMT = "<IIHBHBHBHBfffBBBBBBBBBBBBBBBHHBfB"
LAP_DATA_SIZE = struct.calcsize(LAP_DATA_FMT)  # 57

PARTICIPANT_DATA_SIZE = 57

# CarStatusData per car
CAR_STATUS_FMT = "<BBBBBfffHHBBHBBBbfffBfffB"
CAR_STATUS_SIZE = struct.calcsize(CAR_STATUS_FMT)  # 55

# CarDamageData per car: 4 tyre-wear floats + 30 uint8 damage values.
# Indices in the unpacked tuple (after the 4 floats):
#   4-7   tyresDamage[4]
#   8-11  brakesDamage[4]
#   12-15 tyresBlistered[4]
#   16    frontLeftWingDamage
#   17    frontRightWingDamage
#   18    rearWingDamage
CAR_DAMAGE_FMT = "<4f30B"
CAR_DAMAGE_SIZE = struct.calcsize(CAR_DAMAGE_FMT)  # 46


def parse_header(data):
    h = struct.unpack_from(HEADER_FMT, data, 0)
    return {"packet_id": h[5], "player_car_index": h[10]}


def parse_event_button_status(data):
    if len(data) < HEADER_SIZE + 8:
        return None
    event_code = data[HEADER_SIZE:HEADER_SIZE + 4]
    if event_code != EVENT_CODE_BUTN:
        return None
    return struct.unpack_from("<I", data, HEADER_SIZE + 4)[0]


def parse_session_packet(data):
    pre = struct.unpack_from(PRE_MARSHAL_FMT, data, HEADER_SIZE)
    track_length_m = pre[4]
    session_type = pre[5]
    track_id = pre[6]

    offset = HEADER_SIZE + PRE_MARSHAL_SIZE + MARSHAL_ZONE_SIZE * 21
    if offset + POST_MARSHAL_SIZE > len(data):
        return [], track_id, 0, track_length_m, session_type

    post = struct.unpack_from(POST_MARSHAL_FMT, data, offset)
    safety_car_status = post[0]
    num_samples = min(post[2], 64)
    offset += POST_MARSHAL_SIZE

    samples = []
    for _ in range(num_samples):
        if offset + WEATHER_SAMPLE_SIZE > len(data):
            break
        s = struct.unpack_from(WEATHER_SAMPLE_FMT, data, offset)
        samples.append({
            "session_type": s[0],
            "time_offset": s[1],
            "weather": s[2],
            "track_temp": s[3],
            "track_temp_change": s[4],
            "air_temp": s[5],
            "air_temp_change": s[6],
            "rain_pct": s[7],
        })
        offset += WEATHER_SAMPLE_SIZE

    return samples, track_id, safety_car_status, track_length_m, session_type


def parse_lap_positions(data):
    summary = {}
    offset = HEADER_SIZE
    for i in range(NUM_CARS):
        lap = struct.unpack_from(LAP_DATA_FMT, data, offset)
        delta_to_leader = lap[9] * 60.0 + (lap[8] / 1000.0)
        sector1_total_ms = lap[3] * 60_000 + lap[2]
        sector2_total_ms = lap[5] * 60_000 + lap[4]
        summary[i] = {
            "last_lap_time_ms": lap[0],
            "delta_to_leader": delta_to_leader,
            "sector1_total_ms": sector1_total_ms,
            "sector2_total_ms": sector2_total_ms,
            "lap_distance": lap[10],
            "total_distance": lap[11],
            "position": lap[13],
            "current_lap_num": lap[14],
            "pit_status": lap[15],
            "sector": lap[17],
            "penalties": lap[19],
            "unserved_dt": lap[22],
            "unserved_sg": lap[23],
            "result_status": lap[26],
            "pit_stop_should_serve_pen": lap[30],
        }
        offset += LAP_DATA_SIZE
    return summary


def parse_participants(data):
    names = {}
    race_numbers = {}
    offset = HEADER_SIZE + 1  # Skip m_numActiveCars
    for i in range(NUM_CARS):
        p = struct.unpack_from("<7B32s2BH2B12B", data, offset)
        raw_name = p[7]
        name = raw_name.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        names[i] = name if name else f"Car {i}"
        race_numbers[i] = _normalize_race_number(p[5])
        offset += PARTICIPANT_DATA_SIZE
    return names, race_numbers


def parse_car_status(data):
    statuses = {}
    offset = HEADER_SIZE
    for i in range(NUM_CARS):
        s = struct.unpack_from(CAR_STATUS_FMT, data, offset)
        statuses[i] = {
            "fuel_in_tank": s[5],
            "visual_tyre": s[14],
            "tyres_age_laps": s[15],
            "ers_store": s[19],
            "ers_mode": s[20],
            "ers_harvested_mguk": s[21],
            "ers_harvested_mguh": s[22],
            "ers_deployed": s[23],
        }
        offset += CAR_STATUS_SIZE
    return statuses


def parse_car_damage(data):
    damages = {}
    offset = HEADER_SIZE
    for i in range(NUM_CARS):
        d = struct.unpack_from(CAR_DAMAGE_FMT, data, offset)
        damages[i] = {
            "tyre_wear": [d[0], d[1], d[2], d[3]],
            "fw_left": d[16],
            "fw_right": d[17],
        }
        offset += CAR_DAMAGE_SIZE
    return damages


def format_signed_seconds(delta_seconds):
    if delta_seconds is None:
        return "-"
    return f"{delta_seconds:+.2f}s"


def _col(value, width, right=False):
    s = str(value)
    if len(s) > width:
        s = s[:width]
    return s.rjust(width) if right else s.ljust(width)


def _compose_page(lines):
    if AUTO_SIZE:
        # Wrap the box exactly around the rendered content. Empty content
        # still draws a minimal 1x1 box so the window doesn't collapse.
        if not lines:
            lines = [""]
        width = max((len(line) for line in lines), default=1)
        body = [line.ljust(width) for line in lines]
    else:
        # Fixed dimensions from settings: hard-crop wide lines and pad short
        # rosters to the configured height.
        body = [_col(line, PAGE_INNER_WIDTH) for line in lines[:PAGE_INNER_HEIGHT]]
        while len(body) < PAGE_INNER_HEIGHT:
            body.append(" " * PAGE_INNER_WIDTH)
        width = PAGE_INNER_WIDTH
    top = "┌" + "─" * width + "┐"
    bottom = "└" + "─" * width + "┘"
    middle = [f"│{line}│" for line in body]
    return "\n".join([top, *middle, bottom])


def lap_diff_between(other, player):
    """Integer lap difference of `other` vs `player` based on current_lap_num."""
    if not other or not player:
        return 0
    return other.get("current_lap_num", 0) - player.get("current_lap_num", 0)


def lap_diff_for_display(other, player, track_length_m):
    """
    Integer lap difference between two cars for display purposes.

    Uses cumulative `total_distance` divided by track length so that a `±1L`
    marker only appears when the cars are physically at least one full lap
    apart on track. This avoids flashing `±1L` during the brief SF-transition
    window where lap_nums differ purely due to one car having crossed the
    line first.

    Falls back to raw `lap_num` diff when `total_distance` or
    `track_length_m` aren't available (e.g. before the first session packet).
    """
    if not other or not player:
        return 0
    if track_length_m and track_length_m > 0:
        other_total = other.get("total_distance")
        player_total = player.get("total_distance")
        if other_total is not None and player_total is not None:
            return int((other_total - player_total) / track_length_m)
    return lap_diff_between(other, player)


def gap_text_between(other, player, track_length_m):
    """Render gap of `other` relative to `player` (signed seconds, or '+/-NL')."""
    if not other or not player:
        return "-"

    lap_diff = lap_diff_for_display(other, player, track_length_m)

    if lap_diff != 0:
        return f"{lap_diff:+d}L"

    other_d = other.get("delta_to_leader", 0.0)
    player_d = player.get("delta_to_leader", 0.0)
    return format_signed_seconds(other_d - player_d)


def get_compound_and_max_wear(car_idx, car_statuses, car_damages):
    status = car_statuses.get(car_idx)
    damage = car_damages.get(car_idx)

    tyre = "?"
    if status:
        tyre = TYRE_COMPOUNDS.get(status["visual_tyre"], "?")

    wear_text = "-"
    if damage:
        max_wear = max(damage["tyre_wear"])
        wear_text = f"{max_wear:.0f}%"

    return tyre, wear_text


def format_fw_text(damage):
    """Front-wing damage: single number when symmetric, L/R split when not."""
    if not damage:
        return ""
    fl = damage.get("fw_left", 0)
    fr = damage.get("fw_right", 0)
    if fl == 0 and fr == 0:
        return ""
    if abs(fl - fr) < 10:
        return f"{max(fl, fr):.0f}%"
    return f"L{fl:.0f}/R{fr:.0f}"


def get_car_info(car_idx, car_statuses, car_damages):
    status = car_statuses.get(car_idx)
    damage = car_damages.get(car_idx)
    if not status or not damage:
        return None

    tyre = TYRE_COMPOUNDS.get(status["visual_tyre"], "?")

    wear = damage["tyre_wear"]
    max_wear = max(wear)
    max_idx = wear.index(max_wear)
    wear_str = f"{max_wear:.0f}% ({TYRE_NAMES[max_idx]})"

    battery_pct = (status["ers_store"] / ERS_MAX_ENERGY) * 100
    battery_str = f"{battery_pct:.0f}%"

    ers_mode = ERS_MODES.get(status["ers_mode"], "?")

    return {"tyre": tyre, "wear": wear_str, "battery": battery_str, "ers_mode": ers_mode}


class WearTracker:
    """
    Tracks each car's most recent *clean full lap* of tyre-wear delta on the
    current compound. A clean full lap is one that ran from one SF crossing
    to the next without an intervening compound change and with the start
    snapshot taken at a true SF crossing (not at a mid-stream join or pit).

    Used to project laps-left on the player's current stint via
    `(target_pct - current_wear) / last_lap_wear_delta`.
    """

    def __init__(self, target_pct=WEAR_TARGET_PCT):
        self.target_pct = target_pct
        # car_idx -> {lap, compound, wear, clean_start}
        # clean_start: True if `wear` was sampled at an SF crossing.
        self._lap_start = {}
        # car_idx -> (compound, lap_wear_delta) from the most recent clean
        # full lap. Cleared on compound change, lap-num jump, fresh tyres,
        # and any non-clean rollover.
        self._last_lap_wear = {}
        self._last_age = {}

    def observe(self, car_idx, lap_num, max_wear, compound, tyres_age_laps):
        if lap_num <= 0 or compound is None:
            return

        # Fresh tyres detected (age went backwards) — wipe state.
        prev_age = self._last_age.get(car_idx)
        if prev_age is not None and tyres_age_laps < prev_age:
            self._lap_start.pop(car_idx, None)
            self._last_lap_wear.pop(car_idx, None)
        self._last_age[car_idx] = tyres_age_laps

        prev = self._lap_start.get(car_idx)

        if prev is None:
            # First observation: snapshot but mark not-clean — we don't know
            # whether we caught the lap right at SF or partway through.
            self._lap_start[car_idx] = {
                "lap": lap_num, "compound": compound,
                "wear": max_wear, "clean_start": False,
            }
            return

        if lap_num == prev["lap"]:
            # Mid-lap. Detect compound change → pit stop.
            if compound != prev["compound"]:
                self._lap_start[car_idx] = {
                    "lap": lap_num, "compound": compound,
                    "wear": max_wear, "clean_start": False,
                }
                self._last_lap_wear.pop(car_idx, None)
            return

        # Lap rolled over.
        if (lap_num == prev["lap"] + 1
                and compound == prev["compound"]
                and prev["clean_start"]):
            delta = max_wear - prev["wear"]
            if delta > 0:
                self._last_lap_wear[car_idx] = (compound, delta)
            else:
                self._last_lap_wear.pop(car_idx, None)
        else:
            # Couldn't measure a clean full lap — drop any stale estimate.
            self._last_lap_wear.pop(car_idx, None)

        # The current packet is the SF-crossing snapshot for the new lap.
        self._lap_start[car_idx] = {
            "lap": lap_num, "compound": compound,
            "wear": max_wear, "clean_start": True,
        }

    def last_lap_wear(self, car_idx):
        """(compound, lap_wear_delta) for the most recent clean full lap, or None."""
        return self._last_lap_wear.get(car_idx)


class ErsTracker:
    """
    Tracks the player's ERS battery level at SF crossings to expose two
    page-1 deltas:
      prev: change across the last completed lap (history[-1] - history[-2])
      now:  change since the most recent SF crossing (current - history[-1])

    On lap 1 (no SF crossings observed yet) the `now` baseline is 100% per
    F1 race-start convention. Lap-num jumps > 1 (packet loss / restart)
    wipe the history so a stale `prev` can't span a missing lap.
    """

    HISTORY = 3

    def __init__(self):
        self._history = []
        self._last_lap_num = None

    def observe(self, lap_num, ers_pct):
        if not lap_num or lap_num <= 0:
            return
        if self._last_lap_num is None:
            self._last_lap_num = lap_num
            return
        if lap_num == self._last_lap_num:
            return
        if lap_num == self._last_lap_num + 1:
            # Clean rollover — current ers_pct is the value at SF crossing,
            # which equals end-of-just-completed-lap.
            self._history.append(ers_pct)
            while len(self._history) > self.HISTORY:
                self._history.pop(0)
        else:
            # Non-monotonic / multi-lap jump → discard stale history.
            self._history = []
        self._last_lap_num = lap_num

    def deltas(self, current_ers_pct):
        """(prev_delta, now_delta) — either may be None when not measurable."""
        if self._history:
            now_delta = current_ers_pct - self._history[-1]
        elif self._last_lap_num == 1:
            # Race-start baseline: full battery.
            now_delta = current_ers_pct - 100.0
        else:
            # Mid-stream join with no SF crossing observed yet — no baseline.
            return (None, None)

        prev_delta = (self._history[-1] - self._history[-2]
                      if len(self._history) >= 2 else None)
        return (prev_delta, now_delta)


class SectorTracker:
    """
    Tracks per-car sector times across each car's last 3 lap_nums and tags
    each sector with the compound the car was on when that sector finalized.

    A sector is recorded when its corresponding LAP_DATA field is populated
    (S1 once `sector` reaches 1, S2 once it reaches 2, S3 at lap rollover via
    `lastLapTime − S1 − S2`). A sector is *tainted* and skipped if pit_status
    was nonzero at any observation during it — that catches both in-laps
    (S3 in pit lane) and out-laps (S1 starting in pit lane).
    """

    HISTORY_LAPS = 3

    def __init__(self):
        # car_idx -> {lap_num -> entry}
        # entry: {s1, s2, s3 (seconds | None), c1, c2, c3 (compound | None),
        #         pit_s1, pit_s2, pit_s3 (bool)}
        self._car_laps = {}
        # car_idx -> {"last_lap": int | None}
        self._car_state = {}

    def _new_entry(self):
        return {
            # Raw sector times in ms — always populated when the sector
            # finalizes, used for S3 math even when a sector is pit-tainted.
            "s1_raw_ms": None, "s2_raw_ms": None,
            # Table-eligible times: stay None when the sector overlapped pit lane.
            "s1": None, "s2": None, "s3": None,
            "c1": None, "c2": None, "c3": None,
            "pit_s1": False, "pit_s2": False, "pit_s3": False,
        }

    def observe(self, car_idx, lap_info, status):
        if not lap_info:
            return
        result_status = lap_info.get("result_status", 0)
        if result_status not in ACTIVE_STATUS_SET:
            # Drop a car's history once it's no longer active so stale data
            # from a retired car can't sit forever in the table.
            self._car_laps.pop(car_idx, None)
            self._car_state.pop(car_idx, None)
            return

        lap_num = lap_info.get("current_lap_num", 0)
        if lap_num <= 0:
            return

        sector = lap_info.get("sector", 0)
        pit_status = lap_info.get("pit_status", 0)
        last_lap_ms = lap_info.get("last_lap_time_ms", 0)
        s1_total_ms = lap_info.get("sector1_total_ms", 0)
        s2_total_ms = lap_info.get("sector2_total_ms", 0)
        compound = TYRE_COMPOUNDS.get(status.get("visual_tyre")) if status else None

        state = self._car_state.setdefault(car_idx, {"last_lap": None})
        laps = self._car_laps.setdefault(car_idx, {})

        # Lap rollover: finalize S3 of the just-completed lap. We use the
        # raw S1/S2 (regardless of pit taint) since lastLapTime is the actual
        # total sector time sum, and pit_s3 alone gates whether to record.
        if state["last_lap"] is not None and lap_num != state["last_lap"]:
            prev = laps.get(state["last_lap"])
            if (prev is not None
                    and prev["s1_raw_ms"] is not None and prev["s2_raw_ms"] is not None
                    and last_lap_ms > 0 and not prev["pit_s3"]):
                s3_ms = last_lap_ms - prev["s1_raw_ms"] - prev["s2_raw_ms"]
                if s3_ms > 0:
                    prev["s3"] = s3_ms / 1000.0
                    prev["c3"] = compound

        entry = laps.setdefault(lap_num, self._new_entry())

        if pit_status != 0:
            if sector == 0:
                entry["pit_s1"] = True
            elif sector == 1:
                entry["pit_s2"] = True
            elif sector == 2:
                entry["pit_s3"] = True

        # Capture raw S1/S2 once available (used for S3 math) and additionally
        # store the table-eligible values + compound when the sector wasn't
        # pit-tainted.
        if sector >= 1 and entry["s1_raw_ms"] is None and s1_total_ms > 0:
            entry["s1_raw_ms"] = s1_total_ms
            if not entry["pit_s1"]:
                entry["s1"] = s1_total_ms / 1000.0
                entry["c1"] = compound
        if sector >= 2 and entry["s2_raw_ms"] is None and s2_total_ms > 0:
            entry["s2_raw_ms"] = s2_total_ms
            if not entry["pit_s2"]:
                entry["s2"] = s2_total_ms / 1000.0
                entry["c2"] = compound

        state["last_lap"] = lap_num

        # Keep only the last HISTORY_LAPS lap_nums per car.
        cutoff = lap_num - (self.HISTORY_LAPS - 1)
        for stale in [ln for ln in laps if ln < cutoff]:
            del laps[stale]

    def best_per_compound_sector(self):
        """
        (compound, sector_idx) -> (best_time_seconds, is_hot).

        `is_hot` is True when the time was set on the holder's most-recent
        instance of that sector. A new sector completion by the holder flips
        it off (slower/equal new time keeps the cell value but drops `[!]`;
        faster new time updates the cell to the new value and keeps `[!]`).
        """
        # Step 1: find the (time, car, lap) that owns the best per bucket.
        owners = {}  # (compound, sector_idx) -> (time, car_idx, lap_num)
        for car_idx, laps in self._car_laps.items():
            for ln, entry in laps.items():
                for sector_idx, t_key, c_key in (
                    (0, "s1", "c1"), (1, "s2", "c2"), (2, "s3", "c3"),
                ):
                    t = entry[t_key]
                    c = entry[c_key]
                    if t is None or c is None:
                        continue
                    key = (c, sector_idx)
                    if key not in owners or t < owners[key][0]:
                        owners[key] = (t, car_idx, ln)

        # Step 2: compute hot flag per holder.
        result = {}
        for key, (t, car_idx, ln) in owners.items():
            hot = self._is_holders_most_recent(car_idx, key[1], ln)
            result[key] = (t, hot)
        return result

    def _is_holders_most_recent(self, car_idx, sector_idx, lap_num):
        """True if `lap_num` is the holder's last finalized instance of `sector_idx`."""
        laps = self._car_laps.get(car_idx, {})
        if sector_idx == 0:
            candidates = [ln for ln, e in laps.items() if e["s1_raw_ms"] is not None]
            return bool(candidates) and max(candidates) == lap_num
        if sector_idx == 1:
            candidates = [ln for ln, e in laps.items() if e["s2_raw_ms"] is not None]
            return bool(candidates) and max(candidates) == lap_num
        if sector_idx == 2:
            # S3 finalizes at lap rollover; the most-recent finalized S3 is
            # the lap before the car's currently-running one.
            state = self._car_state.get(car_idx, {})
            last_lap = state.get("last_lap")
            if last_lap is None or last_lap < 2:
                return False
            return last_lap - 1 == lap_num
        return False


class LapLogger:
    """
    Writes one CSV row per completed player lap into laps/<...>.csv.

    A new file is opened the first time telemetry produces a usable lap, and
    again whenever telemetry stalls long enough to be considered "no signal"
    or the session key (date + track + session group) changes. Files are
    never appended to from a previous run — the next observation always
    creates a new file with the smallest unused 4-digit number for that key.

    Pit-stop semantics: the lap-start snapshot is re-taken whenever the
    visual tyre compound changes mid-lap (pit stop). That keeps the wear
    delta on out-laps positive (reflecting accumulation on the new tyre)
    instead of showing a huge negative number from old → new tyre swap.

    All file I/O is wrapped in a lock so the UDP-thread `observe()` can't
    race with the main-thread `tick()` (stall close) or `close()` (exit).
    OSErrors are caught — a logging failure can never bring the overlay
    down; it just disables the logger for the rest of the run.
    """

    SESSION_GROUP = {
        1: "practice", 2: "practice", 3: "practice", 4: "practice",
        5: "qualifying", 6: "qualifying", 7: "qualifying",
        8: "qualifying", 9: "qualifying",
        10: "sprint_shootout", 11: "sprint_shootout", 12: "sprint_shootout",
        13: "sprint_shootout", 14: "sprint_shootout",
        15: "race", 16: "race", 17: "race",
        18: "time_trial",
    }
    HEADER = [
        "Lap time", "Lap time in seconds", "Tire compound",
        "Fuel on start", "Tire wear on start", "Tire wear delta",
        "Fuel consumption delta", "ERS used",
    ]
    MAX_FILE_NUMBER = 9999
    LATE_JOIN_DISTANCE_M = 500  # if first packet shows further into the lap, skip it

    def __init__(self, base_dir, enabled, stall_threshold_s):
        self._dir = os.path.join(base_dir, "laps")
        self._enabled = enabled
        self._stall_threshold = stall_threshold_s
        self._lock = threading.Lock()
        self._file = None
        self._writer = None
        self._session_key = None
        self._lap_start = None
        self._last_seen = None
        self._last_lap_num = None
        self._last_observed_ts = 0.0
        self._broken = False

    def observe(self, lap_info, status, damage, session_type, track_id, now_ts):
        if not self._enabled or self._broken:
            return
        if not lap_info or not status or not damage:
            return
        if session_type not in self.SESSION_GROUP:
            return
        if lap_info.get("result_status", 0) not in ACTIVE_STATUS_SET:
            return

        with self._lock:
            # Stall detection: close current file if the gap since the last
            # observation exceeds the stall threshold.
            if (self._file is not None
                    and self._last_observed_ts
                    and (now_ts - self._last_observed_ts) > self._stall_threshold):
                self._close_locked()
            self._last_observed_ts = now_ts

            try:
                max_wear = max(damage["tyre_wear"])
                fuel = float(status.get("fuel_in_tank", 0.0))
                compound = TYRE_COMPOUNDS.get(status.get("visual_tyre"), "?")
                ers_deployed = float(status.get("ers_deployed", 0))
            except (TypeError, ValueError, KeyError):
                return

            lap_num = lap_info.get("current_lap_num", 0)
            last_lap_ms = lap_info.get("last_lap_time_ms", 0)
            lap_distance = lap_info.get("lap_distance", 0.0)

            track_slug = TRACK_ID_TO_SLUG.get(track_id, "unknown")
            session_name = self.SESSION_GROUP.get(session_type, "unknown")
            date_str = time.strftime("%Y_%m_%d")
            new_key = (date_str, track_slug, session_name)

            # If the session key changes mid-stream (e.g. quali → race), close
            # the old file so the next write creates a fresh one for the new key.
            if self._file is not None and new_key != self._session_key:
                self._close_locked()

            new_snapshot = {"compound": compound, "fuel": fuel, "wear": max_wear}

            if self._last_lap_num is None:
                # First observation: only trust the snapshot if we caught the
                # lap near its start. Otherwise leave _lap_start as None and
                # skip writing until the next true rollover.
                if lap_distance < self.LATE_JOIN_DISTANCE_M:
                    self._lap_start = new_snapshot
            elif lap_num != self._last_lap_num:
                # Lap rollover. Write the just-completed lap if we have a
                # valid start snapshot and the rollover is monotonic forward.
                if (lap_num == self._last_lap_num + 1
                        and self._lap_start is not None
                        and last_lap_ms > 0
                        and self._last_seen is not None):
                    self._write_lap_locked(
                        last_lap_ms, self._lap_start, self._last_seen, new_key,
                    )
                # Always re-snapshot at rollover so the next lap has clean
                # start values, even if we skipped writing this one.
                self._lap_start = new_snapshot
            else:
                # Same lap. If the visual compound changed, the player just
                # pitted — re-snap start so the out-lap delta makes sense.
                if (self._lap_start is not None
                        and self._lap_start["compound"] != compound):
                    self._lap_start = new_snapshot

            self._last_seen = {
                "fuel": fuel, "wear": max_wear, "ers_deployed": ers_deployed,
            }
            self._last_lap_num = lap_num

    def _write_lap_locked(self, last_lap_ms, lap_start, last_seen, key):
        if self._file is None:
            self._open_locked(key)
            if self._file is None:
                return  # _open_locked failed and set _broken

        seconds_total = last_lap_ms / 1000.0
        minutes = int(seconds_total // 60)
        seconds = seconds_total - minutes * 60
        lap_time_str = f"{minutes:02d}:{seconds:06.3f}"

        wear_delta = last_seen["wear"] - lap_start["wear"]
        fuel_delta = lap_start["fuel"] - last_seen["fuel"]
        ers_used_pct = (last_seen["ers_deployed"] / ERS_MAX_ENERGY) * 100

        try:
            self._writer.writerow([
                lap_time_str,
                f"{seconds_total:.3f}",
                lap_start["compound"],
                f"{lap_start['fuel']:.3f}",
                f"{lap_start['wear']:.2f}",
                f"{wear_delta:.2f}",
                f"{fuel_delta:.3f}",
                f"{ers_used_pct:.2f}",
            ])
            self._file.flush()
        except OSError as e:
            print(f"Warning: lap log write failed: {e}", file=sys.stderr)
            self._close_locked()
            self._broken = True

    def _open_locked(self, key):
        try:
            os.makedirs(self._dir, exist_ok=True)
        except OSError as e:
            print(f"Warning: could not create laps directory: {e}",
                  file=sys.stderr)
            self._broken = True
            return

        date, slug, sess = key
        n = 1
        while n <= self.MAX_FILE_NUMBER:
            path = os.path.join(self._dir, f"{date}_{slug}_{sess}_{n:04d}.csv")
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                self._file = os.fdopen(fd, "w", newline="")
                self._writer = csv.writer(self._file)
                self._writer.writerow(self.HEADER)
                self._file.flush()
                self._session_key = key
                return
            except FileExistsError:
                n += 1
            except OSError as e:
                print(f"Warning: could not open lap log: {e}",
                      file=sys.stderr)
                self._broken = True
                return
        print(
            f"Warning: too many lap-log files ({self.MAX_FILE_NUMBER}) for "
            f"{date}_{slug}_{sess}; skipping",
            file=sys.stderr,
        )

    def _close_locked(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError:
                pass
        self._file = None
        self._writer = None
        self._session_key = None
        self._lap_start = None
        self._last_seen = None
        self._last_lap_num = None

    def tick(self, now_ts):
        """Called from main thread to close the file when telemetry stalls."""
        if not self._enabled or self._broken:
            return
        with self._lock:
            if (self._file is not None
                    and self._last_observed_ts
                    and (now_ts - self._last_observed_ts) > self._stall_threshold):
                self._close_locked()

    def close(self):
        """Called on app exit to flush and release the file handle."""
        with self._lock:
            self._close_locked()


class F1OverlayApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("F1 Racing Companion")
        self.root.configure(bg="black")
        if BORDERLESS:
            self.root.overrideredirect(True)
            if OPACITY < 1.0:
                self.root.wm_attributes("-alpha", OPACITY)
        if ALWAYS_ON_TOP:
            self.root.wm_attributes("-topmost", True)
        # Catch the X button (when not borderless) so we still flush logs.
        self.root.protocol("WM_DELETE_WINDOW", self._on_exit)

        self.lap_summary = {}
        self.car_statuses = {}
        self.car_damages = {}
        self.participant_names = {}
        self.participant_race_numbers = {}
        self.weather_samples = []
        self.track_id = -1
        self.track_length_m = 0
        self.safety_car_status = 0
        self.session_type = 0
        self.player_car_index = 0
        self.active_page_index = 1
        self._prev_buttons_state = 0
        self._last_packet_ts = 0.0
        self._got_first_packet = False
        self._last_stale_state = None

        self._wear_tracker = WearTracker()
        self._sector_tracker = SectorTracker()
        self._ers_tracker = ErsTracker()
        self._lap_logger = LapLogger(_base_dir, LOG_LAPS, TELEMETRY_VERY_STALE_S)

        # Cross-thread wake-up signal. The actual data lives in instance dicts;
        # the queue is just a coalesced "something changed, please render" flag.
        self._wakeup = queue.Queue(maxsize=1)

        self.page_renderers = {
            1: self._render_page_1,
            2: self._render_page_2,
            3: self._render_page_3,
        }

        self._build_ui()

        self._udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        self._udp_thread.start()

        self.root.after(100, self._poll)

    def _build_ui(self):
        font = ("Consolas", FONT_SIZE)

        self.page_var = tk.StringVar()
        self.page_label = tk.Label(
            self.root, textvariable=self.page_var, font=font,
            fg="white", bg="black", justify="left", anchor="nw",
        )
        self.page_label.pack(padx=4, pady=2)
        self.page_label.bind("<Button-1>", self._start_move)
        self.page_label.bind("<B1-Motion>", self._do_move)

        self._context_menu = tk.Menu(self.root, tearoff=0)
        self._context_menu.add_command(label="Exit", command=self._on_exit)
        self.page_label.bind("<Button-3>", self._show_context_menu)

    def _start_move(self, event):
        self._drag_offset_x = event.x_root - self.root.winfo_x()
        self._drag_offset_y = event.y_root - self.root.winfo_y()

    def _do_move(self, event):
        new_x = event.x_root - self._drag_offset_x
        new_y = event.y_root - self._drag_offset_y
        self.root.geometry(f"+{new_x}+{new_y}")

    def _show_context_menu(self, event):
        try:
            self._context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._context_menu.grab_release()

    def _on_exit(self):
        self._lap_logger.close()
        self.root.destroy()

    def _udp_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((UDP_IP, UDP_PORT))

        while True:
            data, _ = sock.recvfrom(2048)
            try:
                header = parse_header(data)
            except struct.error:
                continue
            pid = header["packet_id"]
            self.player_car_index = header["player_car_index"]

            try:
                if pid == PACKET_LAP_DATA:
                    self.lap_summary = parse_lap_positions(data)
                elif pid == PACKET_PARTICIPANTS:
                    self.participant_names, self.participant_race_numbers = parse_participants(data)
                elif pid == PACKET_CAR_STATUS:
                    self.car_statuses = parse_car_status(data)
                elif pid == PACKET_CAR_DAMAGE:
                    self.car_damages = parse_car_damage(data)
                elif pid == PACKET_EVENT:
                    self._handle_event_packet(data)
                    self._signal()
                    continue
                elif pid == PACKET_SESSION_DATA:
                    (self.weather_samples, self.track_id,
                     self.safety_car_status, self.track_length_m,
                     self.session_type) = parse_session_packet(data)
                else:
                    continue
            except struct.error:
                continue

            self._last_packet_ts = time.monotonic()
            self._got_first_packet = True
            self._update_trackers()
            self._signal()

    def _signal(self):
        try:
            self._wakeup.put_nowait(True)
        except queue.Full:
            pass

    def _update_trackers(self):
        for car_idx, lap_info in self.lap_summary.items():
            status = self.car_statuses.get(car_idx)

            # Sector tracker only needs lap data + compound from status.
            # It handles its own active-status gating and missing-status case.
            self._sector_tracker.observe(car_idx, lap_info, status)

            if lap_info.get("result_status", 0) not in ACTIVE_STATUS_SET:
                continue
            damage = self.car_damages.get(car_idx)
            if not damage or not status:
                continue
            max_wear = max(damage["tyre_wear"])
            self._wear_tracker.observe(
                car_idx,
                lap_info.get("current_lap_num", 0),
                max_wear,
                TYRE_COMPOUNDS.get(status.get("visual_tyre")),
                status.get("tyres_age_laps", 0),
            )

        # ERS tracker — player only.
        player_lap = self.lap_summary.get(self.player_car_index)
        player_status = self.car_statuses.get(self.player_car_index)
        if player_lap and player_status:
            ers_pct = (player_status.get("ers_store", 0) / ERS_MAX_ENERGY) * 100
            self._ers_tracker.observe(
                player_lap.get("current_lap_num", 0), ers_pct,
            )

        # Lap logger only cares about the player car.
        self._lap_logger.observe(
            self.lap_summary.get(self.player_car_index),
            self.car_statuses.get(self.player_car_index),
            self.car_damages.get(self.player_car_index),
            self.session_type,
            self.track_id,
            time.monotonic(),
        )

    def _handle_event_packet(self, data):
        button_state = parse_event_button_status(data)
        if button_state is None:
            return

        action_1_now = (button_state & UDP_ACTION_1_MASK) != 0
        action_1_prev = (self._prev_buttons_state & UDP_ACTION_1_MASK) != 0
        action_2_now = (button_state & UDP_ACTION_2_MASK) != 0
        action_2_prev = (self._prev_buttons_state & UDP_ACTION_2_MASK) != 0

        if action_1_now and not action_1_prev:
            self._next_page()
        if action_2_now and not action_2_prev:
            self._prev_page()

        self._prev_buttons_state = button_state

    def _next_page(self):
        next_idx = self.active_page_index + 1
        self.active_page_index = next_idx if next_idx in self.page_renderers else 1

    def _prev_page(self):
        prev_idx = self.active_page_index - 1
        if prev_idx in self.page_renderers:
            self.active_page_index = prev_idx
            return
        self.active_page_index = max(self.page_renderers)

    def _poll(self):
        had_data = False
        try:
            while True:
                self._wakeup.get_nowait()
                had_data = True
        except queue.Empty:
            pass

        stale_state = self._compute_stale_state()
        if had_data or stale_state != self._last_stale_state:
            self._last_stale_state = stale_state
            self._refresh_ui(stale_state)

        self._lap_logger.tick(time.monotonic())

        self.root.after(100, self._poll)

    def _compute_stale_state(self):
        if not self._got_first_packet:
            return "no_data"
        elapsed = time.monotonic() - self._last_packet_ts
        if elapsed > TELEMETRY_VERY_STALE_S:
            return "very_stale"
        if elapsed > TELEMETRY_STALE_S:
            return "stale"
        return "fresh"

    def _is_player_retired(self):
        player = self.lap_summary.get(self.player_car_index)
        return bool(player) and player.get("result_status", 0) in RETIRED_STATUS_SET

    def _is_race_start(self):
        if self.session_type not in RACE_SESSION_TYPES:
            return False
        player = self.lap_summary.get(self.player_car_index)
        if not player:
            return False
        if player.get("current_lap_num", 0) > 1:
            return False
        return player.get("lap_distance", 0.0) < RACE_START_LAP_DISTANCE_M

    def _retirement_banner(self):
        player = self.lap_summary.get(self.player_car_index, {})
        status = player.get("result_status", 0)
        labels = {4: "DNF", 5: "DSQ", 6: "NC", 7: "RETIRED"}
        return f"=== {labels.get(status, 'OUT')} ==="

    def _car_display_name(self, car_idx):
        race_num = self.participant_race_numbers.get(car_idx)
        custom = _driver_name_map.get(race_num) if race_num else None
        if custom:
            return custom
        return self.participant_names.get(car_idx, f"Car {car_idx}")

    def _build_weather_lines(self):
        if not self.weather_samples:
            return ["No weather data yet"]
        slots = []
        for i, s in enumerate(self.weather_samples, 1):
            weather = WEATHER_TYPES.get(s["weather"], f"?({s['weather']})")
            slots.append(
                f"{_col(i, 2)} {_col(s['time_offset'], 3, right=True)} min  "
                f"{_col(weather, 3)}  {_col(s['rain_pct'], 3, right=True)}%"
            )
        lines = []
        for i in range(0, len(slots), 2):
            if i + 1 < len(slots):
                lines.append(f"{slots[i]} | {slots[i + 1]}")
            else:
                lines.append(slots[i])
        return lines

    def _build_grid_rows(self):
        cars = []
        for idx, info in self.lap_summary.items():
            pos = info.get("position", 0)
            if pos <= 0 or info.get("result_status", 0) not in ACTIVE_STATUS_SET:
                continue
            cars.append((pos, idx, info))
        cars.sort()
        if not cars:
            return ["Awaiting grid data"]

        rows = []
        player_list_idx = None
        for list_idx, (pos, idx, _info) in enumerate(cars):
            is_player = idx == self.player_car_index
            if is_player:
                player_list_idx = list_idx
            name = "------" if is_player else self._car_display_name(idx)
            tyre, _wear = get_compound_and_max_wear(idx, self.car_statuses, self.car_damages)
            rows.append(f"{_col(pos, 2)} {_col(name, 12)} {_col(tyre, 3)}")

        if player_list_idx is None:
            window = rows[:11]
        else:
            start = max(0, player_list_idx - 5)
            end = min(len(rows), player_list_idx + 6)
            window = rows[start:end]

        return ["FORMATION / RACE START", *window]

    def _build_standings_rows(self):
        player = self.lap_summary.get(self.player_car_index)
        if not player or player.get("position", 0) <= 0:
            return ["No lap data yet"]

        active_cars = []
        for idx, info in self.lap_summary.items():
            pos = info.get("position", 0)
            if pos <= 0 or info.get("result_status", 0) not in ACTIVE_STATUS_SET:
                continue
            active_cars.append((pos, idx, info))
        active_cars.sort()

        if not active_cars:
            return ["No lap data yet"]

        all_rows = []
        player_list_idx = None
        for list_idx, (pos, idx, info) in enumerate(active_cars):
            is_player = idx == self.player_car_index
            if is_player:
                player_list_idx = list_idx

            name = "------" if is_player else self._car_display_name(idx)

            if is_player:
                gap_text = ""
            else:
                gap_text = gap_text_between(info, player, self.track_length_m)

            tyre, wear = get_compound_and_max_wear(idx, self.car_statuses, self.car_damages)
            fw_text = format_fw_text(self.car_damages.get(idx))

            pen_parts = []
            penalties = info.get("penalties", 0)
            if penalties:
                pen_parts.append(f"+{penalties}s")
            if info.get("unserved_dt", 0):
                pen_parts.append("DT")
            if info.get("unserved_sg", 0):
                pen_parts.append("SG")
            pen_text = " ".join(pen_parts)

            all_rows.append(
                f"{_col(pos, 2)} {_col(name, 10)} {_col(gap_text, 8, right=True)} "
                f"{_col(tyre, 3)} {_col(wear, 4, right=True)} "
                f"{_col(fw_text, 9, right=True)} {_col(pen_text, 11)}"
            )

        if player_list_idx is None:
            return all_rows[:11]

        start = max(0, player_list_idx - 5)
        end = min(len(all_rows), player_list_idx + 6)
        return all_rows[start:end]

    def _build_player_extras(self, player):
        lines = []

        damage = self.car_damages.get(self.player_car_index)
        status = self.car_statuses.get(self.player_car_index)
        current_compound = (TYRE_COMPOUNDS.get(status.get("visual_tyre"))
                            if status else None)

        if damage:
            wear = damage["tyre_wear"]
            max_wear = max(wear)
            corner = TYRE_NAMES[wear.index(max_wear)]
            last = self._wear_tracker.last_lap_wear(self.player_car_index)

            if (last is not None and current_compound is not None
                    and last[0] == current_compound and last[1] > 0):
                last_delta = last[1]
                if max_wear >= WEAR_TARGET_PCT:
                    deg_text = f"+{last_delta:.1f}/lap ~0L left"
                else:
                    laps_left = (WEAR_TARGET_PCT - max_wear) / last_delta
                    deg_text = f"+{last_delta:.1f}/lap ~{laps_left:.0f}L left"
                lines.append(f"Tyre: {max_wear:.0f}% ({corner}) {deg_text}")
            else:
                lines.append(f"Tyre: {max_wear:.0f}% ({corner})")

        if status:
            store_pct = (status.get("ers_store", 0) / ERS_MAX_ENERGY) * 100
            ers_mode = ERS_MODES.get(status.get("ers_mode", 0), "?")
            prev_delta, now_delta = self._ers_tracker.deltas(store_pct)
            if prev_delta is not None and now_delta is not None:
                deltas_text = f"prev {prev_delta:+.1f}%, now {now_delta:+.1f}%"
                lines.append(f"ERS: {store_pct:.0f}% ({deltas_text}) {ers_mode}")
            elif now_delta is not None:
                lines.append(f"ERS: {store_pct:.0f}% (now {now_delta:+.1f}%) {ers_mode}")
            else:
                lines.append(f"ERS: {store_pct:.0f}% {ers_mode}")

        return lines

    def _render_page_1(self):
        if self._is_player_retired():
            return [self._retirement_banner()], self._build_weather_lines()
        if self._is_race_start():
            return [], self._build_grid_rows()

        player = self.lap_summary.get(self.player_car_index)
        if not player:
            return ["Waiting for telemetry..."], []

        cars_lines = []
        if self.session_type in RACE_SESSION_TYPES:
            player_pos = player.get("position", 0)
            ahead_idx = None
            behind_idx = None
            for idx, info in self.lap_summary.items():
                if info.get("result_status", 0) not in ACTIVE_STATUS_SET:
                    continue
                pos = info.get("position", 0)
                if pos == player_pos - 1:
                    ahead_idx = idx
                if pos == player_pos + 1:
                    behind_idx = idx

            ahead_lap = self.lap_summary.get(ahead_idx) if ahead_idx is not None else None
            behind_lap = self.lap_summary.get(behind_idx) if behind_idx is not None else None
            ahead_info = get_car_info(ahead_idx, self.car_statuses, self.car_damages) if ahead_idx is not None else None
            behind_info = get_car_info(behind_idx, self.car_statuses, self.car_damages) if behind_idx is not None else None

            for other_lap, info in [(ahead_lap, ahead_info), (behind_lap, behind_info)]:
                if info and other_lap:
                    gap_text = gap_text_between(other_lap, player, self.track_length_m)
                    cars_lines.append(
                        f"{_col(gap_text, 8, right=True)} {_col(info['tyre'], 3)} "
                        f"{_col(info['wear'], 9)} {_col(info['battery'], 4)} "
                        f"{_col(info['ers_mode'], 8)}"
                    )
                else:
                    cars_lines.append(
                        f"{_col('-', 8, right=True)} {_col('-', 3)} {_col('-', 9)} "
                        f"{_col('-', 4)} {_col('-', 8)}"
                    )

        cars_lines.extend(self._build_player_extras(player))

        return cars_lines, self._build_standings_rows()

    def _render_page_2(self):
        if self._is_player_retired():
            return [self._retirement_banner()], self._build_weather_lines()
        if self.session_type not in RACE_SESSION_TYPES:
            return [], self._build_weather_lines()
        if self._is_race_start():
            return ["Pit projection unavailable on lap 1"], self._build_weather_lines()

        player = self.lap_summary.get(self.player_car_index)
        if not player or player.get("position", 0) <= 0:
            return [
                f"{'Pit?':<5} {_col('-', 9)} "
                f"{_col('-', 8, right=True)} {_col('-', 8, right=True)}"
            ], ["No lap data yet"]

        player_pos = player["position"]
        player_delta_to_leader = player["delta_to_leader"]

        sc_active = self.safety_car_status in (1, 2)
        baseline = _EFFECTIVE_PIT_TIMES.get(self.track_id, _EFFECTIVE_PIT_TIMES[-1])
        pit_loss = float(baseline["sc_pitstop_time"] if sc_active else baseline["pitstop_time"])

        # Penalty served *during* the pit stop only counts when the game flag
        # says so. DT is served on its own pass — surfaced separately below.
        extra_penalty_time = 0
        if player.get("pit_stop_should_serve_pen"):
            extra_penalty_time += player.get("unserved_sg", 0) * STOP_GO_PENALTY_SECONDS

        projected_delta_to_leader = player_delta_to_leader + pit_loss + extra_penalty_time

        projection_cars = []
        for idx, info in self.lap_summary.items():
            if idx == self.player_car_index:
                continue
            pos = info.get("position", 0)
            if pos <= 0 or info.get("result_status", 0) not in ACTIVE_STATUS_SET:
                continue
            if info.get("pit_status", 0) in (1, 2):
                continue
            projection_cars.append((idx, info))

        projection_cars.sort(key=lambda item: item[1].get("delta_to_leader", 0.0))

        raw_projected_insert_idx = 0
        while (
            raw_projected_insert_idx < len(projection_cars)
            and projected_delta_to_leader > projection_cars[raw_projected_insert_idx][1].get("delta_to_leader", 0.0)
        ):
            raw_projected_insert_idx += 1

        raw_projected_position = raw_projected_insert_idx + 1
        projected_position = max(player_pos, raw_projected_position)
        positions_lost = projected_position - player_pos

        ahead_idx_proj = raw_projected_insert_idx - 1
        ahead_info = projection_cars[ahead_idx_proj][1] if ahead_idx_proj >= 0 else None
        ahead_gap = (projected_delta_to_leader - ahead_info.get("delta_to_leader", 0.0)) if ahead_info is not None else None

        behind_idx_proj = raw_projected_insert_idx
        behind_info = projection_cars[behind_idx_proj][1] if behind_idx_proj < len(projection_cars) else None
        behind_gap = (behind_info.get("delta_to_leader", 0.0) - projected_delta_to_leader) if behind_info is not None else None

        projected_position_text = f"P{projected_position} ({positions_lost:+d})"
        ahead_text = self._format_proj_gap(ahead_gap, True, player, ahead_info) if ahead_info else "-"
        behind_text = self._format_proj_gap(behind_gap, False, player, behind_info) if behind_info else "-"

        loss_text = f"loss {pit_loss:.0f}s"

        top_lines = [
            f"{'Pit?':<5} {_col(projected_position_text, 9)} "
            f"{_col(ahead_text, 8, right=True)} {_col(behind_text, 8, right=True)}  "
            f"{_col(loss_text, 8)}"
        ]

        # Penalties yet to be served — shown separately so the projection above
        # remains an apples-to-apples "what if I pit now" number.
        unserved_dt = player.get("unserved_dt", 0)
        unserved_sg = player.get("unserved_sg", 0)
        if unserved_dt or unserved_sg:
            owed_dt = unserved_dt * DRIVE_THROUGH_PENALTY_SECONDS
            owed_sg = unserved_sg * STOP_GO_PENALTY_SECONDS
            owed_total = owed_dt + owed_sg
            parts = []
            if unserved_dt:
                parts.append(f"{unserved_dt}xDT(+{owed_dt}s)")
            if unserved_sg:
                parts.append(f"{unserved_sg}xSG(+{owed_sg}s)")
            top_lines.append(f"Pen owed: {_col(' '.join(parts), 30)} = +{owed_total}s")

        return top_lines, self._build_weather_lines()

    def _render_page_3(self):
        if self._is_player_retired():
            return [self._retirement_banner()], []
        if self.session_type not in RACE_SESSION_TYPES:
            return [], []

        best = self._sector_tracker.best_per_compound_sector()

        # Per-column overall fastest across all compounds, used both for the
        # "is this row the fastest" check and for delta computation.
        column_best = {}  # sector_idx -> (compound, time)
        for (compound, sector_idx), (t, _hot) in best.items():
            existing = column_best.get(sector_idx)
            if existing is None or t < existing[1]:
                column_best[sector_idx] = (compound, t)

        lines = ["Best sectors per compound (last 3 laps, all cars)"]
        lines.append(
            f"{_col('', 6)} {_col('S1', 12, right=True)} "
            f"{_col('S2', 12, right=True)} {_col('S3', 12, right=True)}"
        )

        for compound in ("SOF", "MED", "HAR", "INT", "WET"):
            cells = []
            for sector_idx in (0, 1, 2):
                entry = best.get((compound, sector_idx))
                col = column_best.get(sector_idx)
                if entry is None:
                    cells.append("-")
                else:
                    t, hot = entry
                    if col is not None and col[0] == compound:
                        text = f"{t:.3f}"
                    else:
                        delta = t - col[1]
                        text = f"{delta:+.3f}"
                    if hot:
                        text = f"{text} [!]"
                    cells.append(text)
            stars = sum(
                1 for sector_idx in (0, 1, 2)
                if column_best.get(sector_idx, (None,))[0] == compound
            )
            label = compound + ("*" * stars)
            lines.append(
                f"{_col(label, 6)} {_col(cells[0], 12, right=True)} "
                f"{_col(cells[1], 12, right=True)} {_col(cells[2], 12, right=True)}"
            )

        return lines, []

    def _format_proj_gap(self, gap_seconds, is_ahead, player_info, other_info):
        """Format a pit-projection gap using page-1's sign convention:
        ahead car = negative seconds, behind car = positive seconds; lap-down
        uses the raw lap_diff sign (`+NL` ahead, `-NL` behind)."""
        if gap_seconds is None:
            return "-"
        lap_diff = lap_diff_for_display(other_info, player_info, self.track_length_m)
        if lap_diff != 0:
            return f"{lap_diff:+d}L"
        signed = -gap_seconds if is_ahead else gap_seconds
        return format_signed_seconds(signed)

    def _refresh_ui(self, stale_state):
        if stale_state == "no_data" or self.session_type not in ACTIVE_SESSION_TYPES:
            self.page_var.set(_compose_page([f"Waiting for telemetry on UDP {UDP_PORT}..."]))
            return

        render_fn = self.page_renderers.get(self.active_page_index, self.page_renderers[1])
        cars_lines, weather_lines = render_fn()

        if stale_state == "stale":
            cars_lines = ["[STALE]"] + list(cars_lines)
        elif stale_state == "very_stale":
            cars_lines = ["[NO SIGNAL]"] + list(cars_lines)
            weather_lines = []

        self.page_var.set(_compose_page([*cars_lines, *weather_lines]))

    def run(self):
        self.root.mainloop()


def main():
    app = F1OverlayApp()
    app.run()


if __name__ == "__main__":
    main()
