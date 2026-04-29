import socket
import struct
import threading
import queue
import tkinter as tk
import json
import os
import sys
import time

# F1 25 default UDP port
UDP_IP = "0.0.0.0"

if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))
_settings_path = os.path.join(_base_dir, "settings.json")
_pit_calibration_path = os.path.join(_base_dir, "pit_calibration.json")

with open(_settings_path, "r") as _f:
    _settings = json.load(_f)
UDP_PORT = _settings["udp_port"]


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
    0: "☀️",
    1: "⛅",
    2: "☁️",
    3: "!🌧️",
    4: "!!🌧️",
    5: "!!!🌧️",
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

TEMP_CHANGE = {0: "up", 1: "down", 2: "no change"}

TYRE_COMPOUNDS = {16: "S", 17: "M", 18: "H", 7: "I", 8: "W"}

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
WEAR_HISTORY_LEN = 6
WEAR_RATE_NEGLIGIBLE = 0.05

# Pit calibration sanity bounds and rolling-window length
PIT_LOSS_MIN_S = 12
PIT_LOSS_MAX_S = 50
PIT_CALIBRATION_SAMPLES = 3
# Front-wing damage threshold above which we assume a wing was replaced when
# the post-stop value drops to ~0
FW_REPLACED_PRE_DAMAGE_THRESHOLD = 5
FW_REPLACED_POST_DAMAGE_THRESHOLD = 1

# Per-track pit-loss baselines (green / safety car), in seconds.
# Values are real-world estimates; PitCalibrator overrides per-track once it
# observes a clean stop (tires only, no front wing replacement, no penalty served).
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
    track_id = pre[6]
    formula = pre[7]

    offset = HEADER_SIZE + PRE_MARSHAL_SIZE + MARSHAL_ZONE_SIZE * 21
    if offset + POST_MARSHAL_SIZE > len(data):
        return [], track_id, formula, 0, track_length_m

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

    return samples, track_id, formula, safety_car_status, track_length_m


def parse_lap_positions(data):
    summary = {}
    offset = HEADER_SIZE
    for i in range(NUM_CARS):
        lap = struct.unpack_from(LAP_DATA_FMT, data, offset)
        delta_to_leader = lap[9] * 60.0 + (lap[8] / 1000.0)
        summary[i] = {
            "last_lap_time_ms": lap[0],
            "delta_to_leader": delta_to_leader,
            "lap_distance": lap[10],
            "total_distance": lap[11],
            "position": lap[13],
            "current_lap_num": lap[14],
            "pit_status": lap[15],
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
    return f"{delta_seconds:+.3f}"


def lap_diff_between(other, player):
    """Integer lap difference of `other` vs `player` based on current_lap_num."""
    if not other or not player:
        return 0
    return other.get("current_lap_num", 0) - player.get("current_lap_num", 0)


def gap_text_between(other, player, track_length_m):
    """Render gap of `other` relative to `player` (signed seconds, or '+/-NL')."""
    if not other or not player:
        return "-"

    lap_diff = lap_diff_between(other, player)

    # SF-line tiebreak: lap nums match but cars are physically a lap apart
    if lap_diff == 0 and track_length_m and track_length_m > 0:
        dist_diff = other.get("total_distance", 0.0) - player.get("total_distance", 0.0)
        if abs(dist_diff) > track_length_m * 0.5:
            lap_diff = 1 if dist_diff > 0 else -1

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
    """Records per-car tyre wear samples and computes degradation rate."""

    def __init__(self, target_pct=WEAR_TARGET_PCT):
        self.target_pct = target_pct
        self._history = {}    # car_idx -> [(lap_num, max_wear), ...]
        self._last_age = {}   # car_idx -> last seen tyres_age_laps

    def observe(self, car_idx, lap_num, max_wear, tyres_age_laps):
        if lap_num <= 0:
            return
        prev_age = self._last_age.get(car_idx)
        if prev_age is not None and tyres_age_laps < prev_age:
            self._history[car_idx] = []  # Fresh tyres fitted
        self._last_age[car_idx] = tyres_age_laps

        history = self._history.setdefault(car_idx, [])
        if history and history[-1][0] == lap_num:
            history[-1] = (lap_num, max_wear)
        else:
            history.append((lap_num, max_wear))
            if len(history) > WEAR_HISTORY_LEN:
                history.pop(0)

    def degradation(self, car_idx):
        """Returns (rate_per_lap, laps_to_target) — either may be None."""
        history = self._history.get(car_idx, [])
        if len(history) < 2:
            return None, None
        first_lap, first_wear = history[0]
        last_lap, last_wear = history[-1]
        lap_span = last_lap - first_lap
        if lap_span <= 0:
            return None, None
        rate = (last_wear - first_wear) / lap_span
        if rate <= WEAR_RATE_NEGLIGIBLE:
            return rate, None
        if last_wear >= self.target_pct:
            return rate, 0.0
        laps_to_target = (self.target_pct - last_wear) / rate
        return rate, max(0.0, laps_to_target)


class PitCalibrator:
    """
    Tracks the player's pit stops and persists per-track pit-loss measurements.

    A stop only contributes a sample if all of these hold:
      - no penalty was served during the stop (unserved_dt/unserved_sg unchanged,
        and pit_stop_should_serve_pen was false at pit-in);
      - no front wing replacement (FL/FR damage didn't drop from significant
        pre-stop values to ~0 post-stop);
      - the resulting delta change is within sanity bounds.
    """

    def __init__(self, store_path):
        self._path = store_path
        self._data = self._load()
        self._state = "out"          # "out" | "in_pit" | "out_lap"
        self._pre = None
        self._exit_lap = None
        self._suppress = None        # reason this sample is discarded, if any

    def _load(self):
        try:
            with open(self._path, "r") as f:
                d = json.load(f)
                return d if isinstance(d, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    def _save(self):
        try:
            with open(self._path, "w") as f:
                json.dump(self._data, f, indent=2)
        except OSError:
            pass

    def observe(self, player_lap_info, fw_damage_max, track_id, formula, sc_status):
        if not player_lap_info:
            return
        pit_status = player_lap_info.get("pit_status", 0)
        lap_num = player_lap_info.get("current_lap_num", 0)
        delta = player_lap_info.get("delta_to_leader", 0.0)
        unserved_dt = player_lap_info.get("unserved_dt", 0)
        unserved_sg = player_lap_info.get("unserved_sg", 0)
        should_serve = player_lap_info.get("pit_stop_should_serve_pen", 0)
        result_status = player_lap_info.get("result_status", 0)

        if result_status in RETIRED_STATUS_SET:
            self._reset()
            return

        if self._state == "out":
            if pit_status in (1, 2):
                self._state = "in_pit"
                self._pre = {
                    "delta": delta,
                    "lap": lap_num,
                    "unserved_dt": unserved_dt,
                    "unserved_sg": unserved_sg,
                    "fw_damage": fw_damage_max,
                    "sc_status": sc_status,
                    "track_id": track_id,
                    "formula": formula,
                }
                self._suppress = "penalty_due" if should_serve else None

        elif self._state == "in_pit":
            if (unserved_dt < self._pre["unserved_dt"]
                    or unserved_sg < self._pre["unserved_sg"]):
                self._suppress = "penalty_served"

            if pit_status == 0:
                self._state = "out_lap"
                self._exit_lap = lap_num
                if (self._pre["fw_damage"] >= FW_REPLACED_PRE_DAMAGE_THRESHOLD
                        and fw_damage_max < FW_REPLACED_POST_DAMAGE_THRESHOLD):
                    self._suppress = "fw_replaced"

        elif self._state == "out_lap":
            if pit_status in (1, 2):
                self._reset()
                return
            if lap_num >= self._exit_lap + 2:
                if self._suppress is None:
                    pit_loss = delta - self._pre["delta"]
                    self._record(self._pre["track_id"], self._pre["formula"],
                                 self._pre["sc_status"], pit_loss)
                self._reset()

    def _record(self, track_id, formula, sc_status, pit_loss):
        if pit_loss < PIT_LOSS_MIN_S or pit_loss > PIT_LOSS_MAX_S:
            return
        key = f"{track_id}:{formula}"
        bucket = self._data.setdefault(key, {"green": [], "sc": []})
        sc_active = sc_status in (1, 2)
        target_list = bucket["sc"] if sc_active else bucket["green"]
        target_list.append(round(pit_loss, 2))
        while len(target_list) > PIT_CALIBRATION_SAMPLES:
            target_list.pop(0)
        self._save()

    def _reset(self):
        self._state = "out"
        self._pre = None
        self._exit_lap = None
        self._suppress = None

    def get_pit_loss(self, track_id, formula, sc_active):
        """Returns (loss_seconds, measured_bool)."""
        key = f"{track_id}:{formula}"
        bucket = self._data.get(key)
        if bucket:
            samples = bucket["sc"] if sc_active else bucket["green"]
            if samples:
                return sum(samples) / len(samples), True
        baseline = PITSTOP_TIMES.get(track_id, PITSTOP_TIMES[-1])
        value = baseline["sc_pitstop_time"] if sc_active else baseline["pitstop_time"]
        return float(value), False


class F1OverlayApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("F125 Race Engineer Overlay")
        self.root.configure(bg="black")

        self.lap_summary = {}
        self.car_statuses = {}
        self.car_damages = {}
        self.participant_names = {}
        self.participant_race_numbers = {}
        self.weather_samples = []
        self.track_id = -1
        self.track_length_m = 0
        self.formula = 0
        self.safety_car_status = 0
        self.player_car_index = 0
        self.active_page_index = 1
        self._prev_buttons_state = 0
        self._last_packet_ts = 0.0
        self._got_first_packet = False
        self._last_stale_state = None

        self._wear_tracker = WearTracker()
        self._pit_calibrator = PitCalibrator(_pit_calibration_path)

        # Cross-thread wake-up signal. The actual data lives in instance dicts;
        # the queue is just a coalesced "something changed, please render" flag.
        self._wakeup = queue.Queue(maxsize=1)

        self.page_renderers = {
            1: self._render_page_1,
            2: self._render_page_2,
        }

        self._build_ui()

        self._udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        self._udp_thread.start()

        self.root.after(100, self._poll)

    def _build_ui(self):
        font = ("Consolas", 9)

        self.cars_var = tk.StringVar()
        self.cars_label = tk.Label(
            self.root, textvariable=self.cars_var, font=font,
            fg="white", bg="black", justify="left", anchor="nw",
        )
        self.cars_label.pack(fill="x", padx=4, pady=0)

        self.weather_var = tk.StringVar()
        self.weather_label = tk.Label(
            self.root, textvariable=self.weather_var, font=font,
            fg="white", bg="black", justify="left", anchor="nw",
        )
        self.weather_label.pack(fill="x", padx=4, pady=0)

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
                    (self.weather_samples, self.track_id, self.formula,
                     self.safety_car_status, self.track_length_m) = parse_session_packet(data)
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
            if lap_info.get("result_status", 0) not in ACTIVE_STATUS_SET:
                continue
            damage = self.car_damages.get(car_idx)
            status = self.car_statuses.get(car_idx)
            if not damage or not status:
                continue
            max_wear = max(damage["tyre_wear"])
            self._wear_tracker.observe(
                car_idx,
                lap_info.get("current_lap_num", 0),
                max_wear,
                status.get("tyres_age_laps", 0),
            )

        player_lap = self.lap_summary.get(self.player_car_index)
        player_damage = self.car_damages.get(self.player_car_index)
        fw_max = 0
        if player_damage:
            fw_max = max(player_damage.get("fw_left", 0),
                         player_damage.get("fw_right", 0))
        self._pit_calibrator.observe(
            player_lap, fw_max, self.track_id, self.formula, self.safety_car_status,
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
        lines = []
        for i, s in enumerate(self.weather_samples, 1):
            weather = WEATHER_TYPES.get(s["weather"], f"?({s['weather']})")
            lines.append(
                f"{i:<3} {s['time_offset']:>3} min  "
                f"{weather}  {s['rain_pct']:>3}%"
            )
        if not lines:
            lines = ["No weather data yet"]
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
        lines = ["FORMATION / RACE START"]
        for pos, idx, _info in cars:
            is_player = idx == self.player_car_index
            name = "------" if is_player else self._car_display_name(idx)
            tyre, _wear = get_compound_and_max_wear(idx, self.car_statuses, self.car_damages)
            lines.append(f"{pos:<2} {name[:12]:<12} {tyre}")
        return lines

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
                f"{pos:<2} {name[:10]:<10} {gap_text:>8} {tyre} {wear:>5} {fw_text:>7} {pen_text}"
            )

        if player_list_idx is None:
            return all_rows[:11]

        start = max(0, player_list_idx - 5)
        end = min(len(all_rows), player_list_idx + 6)
        return all_rows[start:end]

    def _build_player_extras(self, player):
        lines = []

        rate, laps_left = self._wear_tracker.degradation(self.player_car_index)
        damage = self.car_damages.get(self.player_car_index)
        if damage:
            wear = damage["tyre_wear"]
            max_wear = max(wear)
            corner = TYRE_NAMES[wear.index(max_wear)]
            if rate is None:
                deg_text = "deg ?/lap"
            elif rate <= WEAR_RATE_NEGLIGIBLE:
                deg_text = "stable"
            else:
                left = f"~{laps_left:.0f}L left" if laps_left is not None else "-"
                deg_text = f"+{rate:.1f}/lap {left}"
            lines.append(f"Tyre: {max_wear:.0f}% ({corner}) {deg_text}")

        status = self.car_statuses.get(self.player_car_index)
        if status:
            net = (status.get("ers_harvested_mguk", 0)
                   + status.get("ers_harvested_mguh", 0)
                   - status.get("ers_deployed", 0))
            net_pct = (net / ERS_MAX_ENERGY) * 100
            store_pct = (status.get("ers_store", 0) / ERS_MAX_ENERGY) * 100
            ers_mode = ERS_MODES.get(status.get("ers_mode", 0), "?")
            lines.append(f"ERS: {store_pct:.0f}% ({net_pct:+.1f}% lap) {ers_mode}")

        return lines

    def _render_page_1(self):
        if self._is_player_retired():
            return [self._retirement_banner()], self._build_weather_lines()
        if self._is_race_start():
            return [], self._build_grid_rows()

        player = self.lap_summary.get(self.player_car_index)
        if not player:
            return ["Waiting for telemetry..."], []

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

        ahead_info = get_car_info(ahead_idx, self.car_statuses, self.car_damages) if ahead_idx is not None else None
        behind_info = get_car_info(behind_idx, self.car_statuses, self.car_damages) if behind_idx is not None else None

        cars_lines = []
        for label, info in [("⬆", ahead_info), ("⬇", behind_info)]:
            if info:
                cars_lines.append(f"{label}  {info['tyre']:<4} {info['wear']:<14} {info['battery']:<8} {info['ers_mode']}")
            else:
                cars_lines.append(f"{label}  {'-':<4} {'-':<14} {'-':<8} {'-'}")

        cars_lines.extend(self._build_player_extras(player))

        return cars_lines, self._build_standings_rows()

    def _render_page_2(self):
        if self._is_player_retired():
            return [self._retirement_banner()], self._build_weather_lines()
        if self._is_race_start():
            return ["Pit projection unavailable on lap 1"], self._build_weather_lines()

        player = self.lap_summary.get(self.player_car_index)
        if not player or player.get("position", 0) <= 0:
            return [f"{'Pit?':<5} {'-':<10} {'-':>8} {'-':>8}"], ["No lap data yet"]

        player_pos = player["position"]
        player_delta_to_leader = player["delta_to_leader"]

        sc_active = self.safety_car_status in (1, 2)
        pit_loss, measured = self._pit_calibrator.get_pit_loss(
            self.track_id, self.formula, sc_active,
        )

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
        ahead_text = self._format_proj_gap(ahead_gap, "+", player, ahead_info) if ahead_info else "-"
        behind_text = self._format_proj_gap(behind_gap, "-", player, behind_info) if behind_info else "-"

        loss_marker = "m" if measured else "~"
        loss_text = f"loss{loss_marker}{pit_loss:.0f}s"

        top_lines = [
            f"{'Pit?':<5} {projected_position_text:<10} {ahead_text:>8} {behind_text:>8}  {loss_text}"
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
            top_lines.append(f"Pen owed: {' '.join(parts)} = +{owed_total}s")

        return top_lines, self._build_weather_lines()

    def _format_proj_gap(self, gap_seconds, sign, player_info, other_info):
        if gap_seconds is None:
            return "-"
        lap_diff = lap_diff_between(other_info, player_info)
        if lap_diff != 0:
            return f"{sign}{abs(lap_diff)}L"
        signed = gap_seconds if sign == "+" else -gap_seconds
        return format_signed_seconds(signed)

    def _refresh_ui(self, stale_state):
        if stale_state == "no_data":
            self.cars_var.set(f"Waiting for telemetry on UDP {UDP_PORT}...")
            self.weather_var.set("")
            return

        render_fn = self.page_renderers.get(self.active_page_index, self.page_renderers[1])
        cars_lines, weather_lines = render_fn()

        if stale_state == "stale":
            cars_lines = ["[STALE]"] + list(cars_lines)
        elif stale_state == "very_stale":
            cars_lines = ["[NO SIGNAL]"] + list(cars_lines)
            weather_lines = []

        self.cars_var.set("\n".join(cars_lines))
        self.weather_var.set("\n".join(weather_lines))

    def run(self):
        self.root.mainloop()


def main():
    app = F1OverlayApp()
    app.run()


if __name__ == "__main__":
    main()
