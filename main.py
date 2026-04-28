import socket
import struct
import threading
import tkinter as tk
import json
import os
import sys

# F1 25 default UDP port
UDP_IP = "0.0.0.0"

if getattr(sys, 'frozen', False):
    _base_dir = os.path.dirname(sys.executable)
else:
    _base_dir = os.path.dirname(os.path.abspath(__file__))
_settings_path = os.path.join(_base_dir, "settings.json")
with open(_settings_path, "r") as _f:
    _settings = json.load(_f)
UDP_PORT = _settings["udp_port"]
_driver_name_map = {d["number"]: d["name"] for d in _settings.get("drivers", [])}

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

PITSTOP_TIMES = {
    -1: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Unknown track
     0: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Melbourne       - Australian GP
     1: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Paul Ricard     - French GP (legacy)
     2: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Shanghai        - Chinese GP
     3: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Sakhir          - Bahrain GP
     4: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Catalunya       - Spanish GP
     5: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Monaco          - Monaco GP
     6: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Montreal        - Canadian GP
     7: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Silverstone     - British GP
     8: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Hockenheim      - German GP (legacy)
     9: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Hungaroring     - Hungarian GP
    10: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Spa-Francorchamps - Belgian GP
    11: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Monza           - Italian GP
    12: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Marina Bay      - Singapore GP
    13: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Suzuka          - Japanese GP
    14: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Yas Marina      - Abu Dhabi GP
    15: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Austin (COTA)   - US GP
    16: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Interlagos      - Brazilian GP
    17: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Red Bull Ring   - Austrian GP
    18: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Sochi           - Russian GP (legacy)
    19: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Mexico City     - Mexican GP
    20: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Baku            - Azerbaijan GP
    21: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Sakhir Short
    22: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Silverstone Short
    23: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Austin Short
    24: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Suzuka Short
    25: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Hanoi           - Vietnamese GP (legacy)
    26: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Zandvoort       - Dutch GP
    27: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Imola           - Emilia Romagna GP
    28: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Portimao        - Portuguese GP
    29: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Jeddah          - Saudi Arabian GP
    30: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Miami           - Miami GP
    31: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Las Vegas       - Las Vegas GP
    32: {"pitstop_time": 21, "sc_pitstop_time": 15},  # Losail          - Qatar GP
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

# CarDamageData per car
CAR_DAMAGE_FMT = "<4f30B"
CAR_DAMAGE_SIZE = struct.calcsize(CAR_DAMAGE_FMT)  # 46


def parse_header(data):
    h = struct.unpack_from(HEADER_FMT, data, 0)
    return {"packet_id": h[5], "player_car_index": h[10]}


def parse_event_button_status(data):
    event_code = data[HEADER_SIZE:HEADER_SIZE + 4]
    if event_code != EVENT_CODE_BUTN:
        return None
    return struct.unpack_from("<I", data, HEADER_SIZE + 4)[0]


def parse_weather_forecast(data):
    pre = struct.unpack_from(PRE_MARSHAL_FMT, data, HEADER_SIZE)
    track_length_m = pre[4]  # uint16 trackLength
    track_id = pre[6]  # int8 trackId

    offset = HEADER_SIZE
    offset += PRE_MARSHAL_SIZE          # skip session fields before marshal zones
    offset += MARSHAL_ZONE_SIZE * 21    # skip 21 marshal zones

    post = struct.unpack_from(POST_MARSHAL_FMT, data, offset)
    safety_car_status = post[0]
    num_samples = post[2]
    offset += POST_MARSHAL_SIZE

    samples = []
    for _ in range(num_samples):
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

    return samples, track_id, safety_car_status, track_length_m


def parse_lap_positions(data):
    summary = {}
    offset = HEADER_SIZE
    for i in range(NUM_CARS):
        lap = struct.unpack_from(LAP_DATA_FMT, data, offset)
        delta_to_leader = lap[9] * 60.0 + (lap[8] / 1000.0)
        summary[i] = {
            "last_lap_time_ms": lap[0],
            "position": lap[13],
            "current_lap_num": lap[14],
            "pit_status": lap[15],
            "delta_to_leader": delta_to_leader,
            "lap_distance": lap[10],
            "total_distance": lap[11],
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
        race_numbers[i] = str(p[5])  # m_raceNumber
        offset += PARTICIPANT_DATA_SIZE
    return names, race_numbers


def parse_car_status(data):
    statuses = {}
    offset = HEADER_SIZE
    for i in range(NUM_CARS):
        s = struct.unpack_from(CAR_STATUS_FMT, data, offset)
        statuses[i] = {
            "visual_tyre": s[14],
            "ers_store": s[19],
            "ers_mode": s[20],
        }
        offset += CAR_STATUS_SIZE
    return statuses


def parse_car_damage(data):
    damages = {}
    offset = HEADER_SIZE
    for i in range(NUM_CARS):
        d = struct.unpack_from(CAR_DAMAGE_FMT, data, offset)
        front_wing_damage = max(d[16], d[17])
        damages[i] = {
            "tyre_wear": [d[0], d[1], d[2], d[3]],
            "front_wing_damage": front_wing_damage,
        }
        offset += CAR_DAMAGE_SIZE
    return damages


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


def format_relative_delta(delta_seconds):
    if delta_seconds is None:
        return "-"
    if abs(delta_seconds) < 0.001:
        return "0.000"
    return f"{delta_seconds:+.3f}"


def format_projected_gap(gap_seconds, sign, player_info, other_info, track_len):
    if gap_seconds is None:
        return "-"

    lap_num_diff = other_info.get("current_lap_num", 0) - player_info.get("current_lap_num", 0)
    if lap_num_diff != 0:
        return f"{sign}{abs(lap_num_diff)}L"

    if track_len > 0:
        distance_diff = other_info.get("total_distance", 0.0) - player_info.get("total_distance", 0.0)
        lap_count = int(abs(distance_diff) // track_len)
        if lap_count > 0:
            return f"{sign}{lap_count}L"

    signed_gap = gap_seconds if sign == "+" else -gap_seconds
    return format_relative_delta(signed_gap)


class F1OverlayApp:

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("F125 Race Engineer Overlay")
        self.root.configure(bg="black")

        self.lap_positions = {}
        self.lap_summary = {}
        self.car_statuses = {}
        self.car_damages = {}
        self.participant_names = {}
        self.participant_race_numbers = {}
        self.weather_samples = []
        self.track_id = -1
        self.track_length_m = 0
        self.safety_car_status = 0
        self.player_car_index = 0
        self._pending_update = threading.Event()
        self.active_page_index = 1
        self._prev_buttons_state = 0

        self.page_renderers = {
            1: self._render_page_1,
            2: self._render_page_2,
        }

        self._build_ui()

        self._udp_thread = threading.Thread(target=self._udp_loop, daemon=True)
        self._udp_thread.start()

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
            header = parse_header(data)
            pid = header["packet_id"]
            self.player_car_index = header["player_car_index"]

            if pid == PACKET_LAP_DATA:
                self.lap_summary = parse_lap_positions(data)
                self.lap_positions = {
                    idx: info["position"] for idx, info in self.lap_summary.items()
                }
            elif pid == PACKET_PARTICIPANTS:
                self.participant_names, self.participant_race_numbers = parse_participants(data)
            elif pid == PACKET_CAR_STATUS:
                self.car_statuses = parse_car_status(data)
            elif pid == PACKET_CAR_DAMAGE:
                self.car_damages = parse_car_damage(data)
            elif pid == PACKET_EVENT:
                self._handle_event_packet(data)
                continue
            elif pid == PACKET_SESSION_DATA:
                self.weather_samples, self.track_id, self.safety_car_status, self.track_length_m = parse_weather_forecast(data)
            else:
                continue

            if not self._pending_update.is_set():
                self._pending_update.set()
                self.root.after_idle(self._refresh_ui)

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

    def _build_weather_lines(self):
        weather_lines = []
        for i, s in enumerate(self.weather_samples, 1):
            weather = WEATHER_TYPES.get(s["weather"], f"?({s['weather']})")
            weather_lines.append(
                f"{i:<3} {s['time_offset']:>3} min  "
                f"{weather}  {s['rain_pct']:>3}%"
            )
        if not weather_lines:
            weather_lines = ["No weather data yet"]
        return weather_lines

    def _build_standings_rows(self):
        player = self.lap_summary.get(self.player_car_index)
        if not player or player["position"] <= 0:
            return ["No lap data yet"]

        player_pos = player["position"]
        player_delta = player["delta_to_leader"]
        track_len = float(self.track_length_m) if self.track_length_m > 0 else 0.0

        active_cars = []
        for idx, info in self.lap_summary.items():
            pos = info.get("position", 0)
            if pos <= 0 or info.get("result_status", 0) != 2:
                continue
            active_cars.append((pos, idx, info))
        active_cars.sort()

        all_rows = []
        player_list_idx = 0
        for list_idx, (pos, idx, info) in enumerate(active_cars):
            is_player = idx == self.player_car_index
            if is_player:
                player_list_idx = list_idx

            telemetry_name = self.participant_names.get(idx, f"Car {idx}")
            race_num = self.participant_race_numbers.get(idx)
            name = "------" if is_player else (_driver_name_map.get(race_num, telemetry_name) if race_num else telemetry_name)

            if is_player:
                gap_text = ""
            else:
                if track_len > 0:
                    dist_diff = info.get("total_distance", 0.0) - player.get("total_distance", 0.0)
                    lap_diff = int(dist_diff / track_len)
                else:
                    lap_diff = 0

                if abs(lap_diff) >= 1:
                    gap_text = f"{lap_diff:+d}L"
                else:
                    gap = info.get("delta_to_leader", 0.0) - player_delta
                    gap_text = f"{gap:+.3f}"

            tyre, wear = get_compound_and_max_wear(idx, self.car_statuses, self.car_damages)

            damage = self.car_damages.get(idx, {})
            fw = damage.get("front_wing_damage", 0)
            fw_text = f"{fw:.0f}%" if fw > 0 else ""

            pen_parts = []
            p = info.get("penalties", 0)
            if p:
                pen_parts.append(f"+{p}s")
            if info.get("unserved_dt", 0):
                pen_parts.append("DT")
            pen_text = " ".join(pen_parts)

            all_rows.append(f"{pos:<2} {name[:10]:<10} {gap_text:>8} {tyre} {wear:>5} {fw_text:>5} {pen_text}")

        start = max(0, player_list_idx - 5)
        end = min(len(all_rows), player_list_idx + 6)
        return all_rows[start:end]

    def _render_page_1(self):
        player_pos = self.lap_positions.get(self.player_car_index, 0)

        ahead_idx = None
        behind_idx = None
        for idx, pos in self.lap_positions.items():
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

        return cars_lines, self._build_standings_rows()

    def _render_page_2(self):
        player = self.lap_summary.get(self.player_car_index)
        if not player or player["position"] <= 0:
            top_lines = [f"{'Pit now?':<9} {'-':<6} {'-':>8} {'-':>8}"]
            return top_lines, ["No lap data yet"]

        player_pos = player["position"]
        player_delta_to_leader = player["delta_to_leader"]

        pit_times = PITSTOP_TIMES.get(self.track_id, PITSTOP_TIMES[-1])
        pit_loss = pit_times["sc_pitstop_time"] if self.safety_car_status in (1, 2) else pit_times["pitstop_time"]
        extra_penalty_time = 0
        if player.get("pit_stop_should_serve_pen"):
            extra_penalty_time += player.get("unserved_sg", 0) * STOP_GO_PENALTY_SECONDS

        projected_delta_to_leader = player_delta_to_leader + pit_loss + extra_penalty_time

        standings_cars = []
        projection_cars = []
        for idx, info in self.lap_summary.items():
            if idx == self.player_car_index:
                continue
            if info.get("position", 0) <= 0 or info.get("result_status", 0) != 2:
                continue
            standings_cars.append((idx, info))
            if info.get("pit_status", 0) not in (1, 2):
                projection_cars.append((idx, info))

        standings_cars.sort(key=lambda item: item[1].get("position", 0))
        projection_cars.sort(key=lambda item: item[1].get("position", 0))

        raw_projected_insert_idx = 0
        while (
            raw_projected_insert_idx < len(projection_cars)
            and projected_delta_to_leader > projection_cars[raw_projected_insert_idx][1].get("delta_to_leader", 0.0)
        ):
            raw_projected_insert_idx += 1

        raw_projected_position = raw_projected_insert_idx + 1
        projected_position = max(player_pos, raw_projected_position)
        positions_lost = projected_position - player_pos

        # Car just ahead after pitting: largest delta still below projected_delta
        ahead_idx_proj = raw_projected_insert_idx - 1
        ahead_info = projection_cars[ahead_idx_proj][1] if ahead_idx_proj >= 0 else None
        ahead_gap = (projected_delta_to_leader - ahead_info.get("delta_to_leader", 0.0)) if ahead_info is not None else None

        # Car just behind after pitting: smallest delta above projected_delta
        behind_idx_proj = raw_projected_insert_idx
        behind_info = projection_cars[behind_idx_proj][1] if behind_idx_proj < len(projection_cars) else None
        behind_gap = (behind_info.get("delta_to_leader", 0.0) - projected_delta_to_leader) if behind_info is not None else None

        projected_position_text = f"P{projected_position} ({positions_lost:+d})"
        ahead_gap_text = format_projected_gap(ahead_gap, "+", player, ahead_info, self.track_length_m) if ahead_info else "-"
        behind_gap_text = format_projected_gap(behind_gap, "-", player, behind_info, self.track_length_m) if behind_info else "-"

        top_lines = [
            f"{'Pit now?':<9} {projected_position_text:<10} {ahead_gap_text:>8} {behind_gap_text:>8}"
        ]

        weather_lines = self._build_weather_lines()
        return top_lines, weather_lines

    def _refresh_ui(self):
        self._pending_update.clear()
        render_fn = self.page_renderers.get(self.active_page_index, self.page_renderers[1])
        cars_lines, weather_lines = render_fn()
        self.cars_var.set("\n".join(cars_lines))
        self.weather_var.set("\n".join(weather_lines))

    def run(self):
        self.root.mainloop()


def main():
    app = F1OverlayApp()
    app.run()


if __name__ == "__main__":
    main()
