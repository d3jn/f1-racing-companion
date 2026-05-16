"""
strategist.py — propose F1 race strategy from per-compound lap log CSVs.

Consumes the CSV format that main.py's LapLogger writes (one row per completed
lap). Reads one file per dry compound the user wants to consider, filters each
file to rows matching the flag's compound, and builds a wear-indexed pace /
wear / fuel sequence per compound. Then searches all legal 1-stop and 2-stop
strategies for the user-supplied race length and pit loss, and prints the
fastest of each.

The user is expected to hand-clean the input files (remove in-laps, out-laps,
traffic laps, lucky-tow laps, etc.) before running. No outlier filtering is
done here — every row in the file is treated as a representative racing lap.

Known limitations:
  - Fuel effect on pace (~0.03 s/kg) is silently baked into wear-indexed lap
    times. For race-strategy comparison this is acceptable; the fuel curve
    roughly cancels across plans of similar total length.
  - Backward and forward wear extrapolation are linear in sequence position.
    Real tires often degrade non-linearly near the cliff; feed the tool real
    long-stint data to keep extrapolation short.
"""

import argparse
import csv
import itertools
import math
import statistics
import sys

WEAR_CEILING = 80.0           # percent; running past this is prohibited
MERGE_THRESHOLD = 0.5         # gap < 0.5 × local wear/lap → merge as same-age laps
GAP_DETECTION_MULTIPLIER = 1.5  # gap > 1.5 × local wear/lap → real gap to fill
EXTRAPOLATION_WINDOW = 5      # head/tail laps used to fit extrapolation regressions
MAX_FUTURE_PITS = 2           # live mode: search up to this many additional pits
                              # beyond what's already in race history
PIT_WINDOW_TOLERANCE = 1.0    # seconds; pit window = range of laps that keep
                              # total race time within this of the optimum

COMPOUND_FLAGS = {"soft": "SOF", "medium": "MED", "hard": "HAR"}
COMPOUND_LABEL = {"SOF": "Soft", "MED": "Medium", "HAR": "Hard"}
COMPOUND_PLURAL = {"SOF": "softs", "MED": "mediums", "HAR": "hards"}
COMPOUND_PARSE = {
    "soft": "SOF", "sof": "SOF", "s": "SOF",
    "medium": "MED", "med": "MED", "m": "MED",
    "hard": "HAR", "har": "HAR", "h": "HAR",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Propose F1 race strategy from per-compound lap log CSVs."
    )
    parser.add_argument("--soft", type=str, default=None,
                        help="Path to CSV with SOF laps.")
    parser.add_argument("--medium", type=str, default=None,
                        help="Path to CSV with MED laps.")
    parser.add_argument("--hard", type=str, default=None,
                        help="Path to CSV with HAR laps.")
    parser.add_argument("--live-strategy", action="store_true",
                        help="Skip the 1-stop / 2-stop summary and go straight "
                             "into the interactive custom-pit prompt loop.")
    parser.add_argument("--chart", type=str, default=None,
                        help="Write an SVG line chart of lap_time vs lap "
                             "number for each supplied compound to the given "
                             "path. No PNG support — SVG keeps the tool "
                             "dependency-free.")
    return parser.parse_args()


def prompt_positive_int(prompt):
    while True:
        raw = input(prompt).strip()
        try:
            n = int(raw)
        except ValueError:
            print("  Please enter a positive integer.")
            continue
        if n <= 0:
            print("  Please enter a positive integer.")
            continue
        return n


def prompt_non_negative_int(prompt):
    while True:
        raw = input(prompt).strip()
        try:
            n = int(raw)
        except ValueError:
            print("  Please enter a non-negative integer.")
            continue
        if n < 0:
            print("  Please enter a non-negative integer.")
            continue
        return n


def prompt_compound(prompt, allowed):
    """Prompt for a compound name (soft / medium / hard, case-insensitive,
    short forms accepted). 'allowed' is a set of compound codes that the
    user is allowed to pick from."""
    while True:
        raw = input(prompt).strip().lower()
        if raw in COMPOUND_PARSE:
            code = COMPOUND_PARSE[raw]
            if code in allowed:
                return code
            print(f"  '{raw}' is not available in your inventory.")
            continue
        print("  Please enter soft, medium, or hard.")


def parse_pit_entry(raw, last_pit_lap, total_laps):
    """Parse a pit-entry string. Accepted forms (order-insensitive,
    comma- or space-separated):
        '22'                     → (22, None, None)    hypothetical pit
        '22 medium'              → (22, MED, 'fresh')  actual pit, fresh
        '22 medium used'         → (22, MED, 'used')   actual pit, used set
        '22 medium fresh'        → (22, MED, 'fresh')  actual pit, explicit
    The hypothetical form (lap alone) asks "if I pit on this lap, what
    should I fit and how should the rest of the race go?" without
    mutating state. The actual forms record a pit that just happened.
    Returns ((lap, compound, source), None) on success or
    (None, error_message) on failure."""
    parts = [p for p in raw.replace(",", " ").split() if p]
    if len(parts) == 1:
        try:
            lap = int(parts[0])
        except ValueError:
            return None, ("Format: '<lap>' (hypothetical) or "
                          "'<lap> <compound> [fresh|used]' (actual pit).")
        if lap <= last_pit_lap:
            return None, f"Pit lap must be greater than the previous pit lap ({last_pit_lap})."
        if lap >= total_laps:
            return None, f"Pit lap must be less than the race length ({total_laps})."
        return (lap, None, None), None
    if len(parts) not in (2, 3):
        return None, ("Format: '<lap>' (hypothetical) or "
                      "'<lap> <compound> [fresh|used]' (actual pit).")
    lap, compound, source = None, None, "fresh"
    for p in parts:
        pl = p.lower()
        if compound is None and pl in COMPOUND_PARSE:
            compound = COMPOUND_PARSE[pl]
        elif pl in ("fresh", "used"):
            source = pl
        elif lap is None:
            try:
                lap = int(p)
            except ValueError:
                pass
    if lap is None or compound is None:
        return None, "Couldn't parse lap or compound. Try '22 medium'."
    if lap <= last_pit_lap:
        return None, f"Pit lap must be greater than the previous pit lap ({last_pit_lap})."
    if lap >= total_laps:
        return None, f"Pit lap must be less than the race length ({total_laps})."
    return (lap, compound, source), None


def stint_lengths_from_pit_laps(pit_laps, total_laps):
    """Given sorted pit laps, return the resulting stint lengths."""
    lengths = []
    prev = 0
    for pit in pit_laps:
        lengths.append(pit - prev)
        prev = pit
    lengths.append(total_laps - prev)
    return lengths


def _compound_with_source(compound, source):
    return f"{compound}(used)" if source == "used" else compound


def _format_tires_available(state, sequences):
    """One-liner showing fresh counts and used sets with their wear."""
    pieces = []
    for c in ("SOF", "MED", "HAR"):
        if c not in sequences:
            continue
        fresh = state["fresh_inventory"].get(c, 0)
        used = sorted([u["wear"] for u in state["used_pool"] if u["compound"] == c])
        if fresh == 0 and not used:
            continue
        bits = []
        if fresh > 0:
            bits.append(f"{fresh} fresh")
        if used:
            wear_strs = ", ".join(f"{w:.0f}%" for w in used)
            bits.append(f"{len(used)} used ({wear_strs})")
        pieces.append(f"{c}: {' + '.join(bits)}")
    return "; ".join(pieces)


def _apply_pit(state, lap, compound, source, sequences):
    """Mutate state to reflect an actual pit at `lap` switching to
    (compound, source). The just-removed set is pushed into the used
    pool with its end-of-stint wear; the new set is drawn from either
    fresh inventory or the used pool (least-worn of the requested
    compound). Returns an error string on failure, or None on success."""
    current = state["current_set"]
    cur_seq = sequences[current["compound"]]
    start_idx = wear_to_position(cur_seq, current["wear"])
    stint_len = lap - state["current_stint_start_lap"]
    if stint_len < 1:
        return "Pit lap must be after the start of the current stint."
    if start_idx + stint_len > cur_seq["max_laps"]:
        return (f"Current {current['compound']} set can't run a {stint_len}-lap stint "
                f"from {current['wear']:.1f}% wear without exceeding 80% wear.")
    end_wear = compute_end_wear(cur_seq, start_idx, stint_len)

    # Pick the new set from fresh inventory or the used pool.
    if source == "fresh":
        if state["fresh_inventory"].get(compound, 0) <= 0:
            return (f"No fresh {COMPOUND_PLURAL[compound]} available. "
                    f"Try '{lap} {COMPOUND_LABEL[compound].lower()} used' to re-fit a used set.")
        state["fresh_inventory"][compound] -= 1
        new_set = {"compound": compound, "wear": 0.0, "source": "fresh"}
    else:  # source == "used"
        candidates = [(i, u) for i, u in enumerate(state["used_pool"]) if u["compound"] == compound]
        if not candidates:
            return f"No used {COMPOUND_PLURAL[compound]} available to re-fit."
        lw_idx, lw_set = min(candidates, key=lambda x: x[1]["wear"])
        target_seq = sequences[compound]
        if wear_to_position(target_seq, lw_set["wear"]) >= target_seq["max_laps"]:
            return (f"Least-worn used {COMPOUND_LABEL[compound].lower()} set is at "
                    f"{lw_set['wear']:.1f}% — no usable laps left under 80%.")
        state["used_pool"].pop(lw_idx)
        new_set = {"compound": compound, "wear": lw_set["wear"], "source": "used"}

    # Record the just-completed stint and stash the removed set in the pool.
    state["completed_stints"].append({
        "compound": current["compound"],
        "length": stint_len,
        "source": current["source"],
        "start_wear": current["wear"],
        "pit_lap_after": lap,
    })
    state["used_pool"].append({"compound": current["compound"], "wear": end_wear})

    state["current_set"] = new_set
    state["current_stint_start_lap"] = lap
    return None


def format_live_plan(plan, state, total_laps, sequences, hypothetical_lap=None):
    """Render a live-mode plan with done / current / future phase tags,
    fresh-vs-used annotations per stint, projected race time, and the
    remaining tire pool. If `hypothetical_lap` is set the heading reads
    as a what-if instead of a state-derived plan."""
    if plan is None:
        if hypothetical_lap is not None:
            return f"No legal strategy if pitting at lap {hypothetical_lap}."
        return "No legal strategy from current state."
    if hypothetical_lap is not None:
        lines = [f"Hypothetical: if pitting at lap {hypothetical_lap}, optimal plan is:"]
    else:
        lines = ["Optimal plan from current state:"]
    windows = pit_windows(plan["stints"], plan["total"], sequences)
    cumulative = 0
    for i, s in enumerate(plan["stints"]):
        end_lap = cumulative + s["length"]
        cumulative = end_lap
        if s["phase"] == "done":
            note = "done"
        elif s["phase"] == "current":
            note = f"current; pit on lap {end_lap}" if end_lap < total_laps else "current; runs to end of race"
        else:
            note = f"pit on lap {end_lap}" if end_lap < total_laps else "to end of race"
        # In hypothetical mode the current stint's pit is forced by the
        # user — its window would be misleading, so skip it. Other pits
        # remain free variables and get windows.
        suppress = hypothetical_lap is not None and s["phase"] == "current"
        w = windows.get(i)
        if w is not None and not suppress:
            note = f"{note}, window {w[0]}-{w[1]}"
        label = _compound_with_source(s["compound"], s["source"])
        lines.append(f"  Stint {i+1}: {label}, {s['length']} laps ({note})")
    lines.append(f"  Estimated race time: {format_time(plan['total'])}")
    avail = _format_tires_available(state, sequences)
    if avail:
        lines.append(f"  Tires available: {avail}")
    return "\n".join(lines)


def read_compound_rows(path, target_compound):
    """Read CSV, keep only rows whose Tire compound matches target."""
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("Tire compound", "").strip() != target_compound:
                continue
            try:
                rows.append({
                    "lap_time": float(r["Lap time in seconds"]),
                    "wear_on_start": float(r["Tire wear on start"]),
                    "wear_delta": float(r["Tire wear delta"]),
                    "fuel_delta": float(r["Fuel consumption delta"]),
                })
            except (KeyError, ValueError):
                continue
    return rows


def linear_fit(xs, ys):
    """Ordinary least squares. Returns (slope, intercept). Degrades to
    flat-mean for n<2 or zero variance in xs."""
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    if n == 1:
        return 0.0, mean_y
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0, mean_y
    slope = num / den
    return slope, mean_y - slope * mean_x


def _cluster_median(cluster):
    """Median of each field across all members of a cluster."""
    return {
        "lap_time":      statistics.median(r["lap_time"]      for r in cluster),
        "wear_delta":    statistics.median(r["wear_delta"]    for r in cluster),
        "fuel_delta":    statistics.median(r["fuel_delta"]    for r in cluster),
        "wear_on_start": statistics.median(r["wear_on_start"] for r in cluster),
    }


def _safe_local_wpl(window_clusters, fallback):
    """Median wear_delta across a list of clusters, with a non-positive guard."""
    if not window_clusters:
        return fallback
    wpl = statistics.median(_cluster_median(c)["wear_delta"] for c in window_clusters)
    return wpl if wpl > 0 else fallback


def _isotonic_lap_times(values):
    """Pool Adjacent Violators Algorithm. Returns the L2-optimal
    non-decreasing fit of `values` — every adjacent decreasing pair is
    pooled into a single block carrying their weighted mean, and the
    pooling cascades backward until monotonicity is restored.

    Used to denoise lap_time: real tire degradation only slows the car
    over a stint, so any downtick is sampling noise. wear_delta and
    fuel_delta are not run through this — both legitimately fall as fuel
    burns off, the track rubbers in, etc.

    Result is piecewise-constant across noisy regions but preserves
    observations verbatim wherever they already trend up.
    """
    stack = []  # list of [sum, count]; block mean = sum / count
    for v in values:
        s, c = v, 1
        # Cross-multiplied comparison avoids per-step float division.
        # Safe: all lap times are positive.
        while stack and stack[-1][0] * c > s * stack[-1][1]:
            ps, pc = stack.pop()
            s += ps
            c += pc
        stack.append([s, c])
    out = []
    for s, c in stack:
        out.extend([s / c] * c)
    return out


def _merge_overlapping(sorted_rows, fallback_wpl):
    """Iteratively merge adjacent observations that came from different stints
    but sampled the same tire age.

    Two same-lap-number observations have wear_on_start values that differ by
    much less than one normal lap's wear progression; two *consecutive*
    observations differ by ~1 × wear-per-lap. So the criterion is on the raw
    wear_on_start gap (not the post-progression gap used for fill detection):
    if |prev_median.wear_on_start − curr_median.wear_on_start| < 0.5 × local
    wear/lap, the two clusters are the same tire age and get merged.

    Cluster values are the median of all member rows (so merging cascades
    naturally to 3+ near-identical laps).

    Returns a list of dicts (one per cluster), sorted by wear_on_start.
    """
    clusters = [[r] for r in sorted_rows]
    while True:
        merged_any = False
        out = [clusters[0]]
        for i in range(1, len(clusters)):
            prev = out[-1]
            curr = clusters[i]
            prev_med = _cluster_median(prev)
            curr_med = _cluster_median(curr)
            wear_diff = curr_med["wear_on_start"] - prev_med["wear_on_start"]
            window = out[max(0, len(out) - 3):] + clusters[i:i + 3]
            local_wpl = _safe_local_wpl(window, fallback_wpl)
            if wear_diff < MERGE_THRESHOLD * local_wpl:
                out[-1] = prev + curr
                merged_any = True
            else:
                out.append(curr)
        clusters = out
        if not merged_any:
            break
        # A merged cluster's median wear_on_start could in principle shift
        # past a neighbor's; re-sort defensively before the next pass.
        clusters.sort(key=lambda c: _cluster_median(c)["wear_on_start"])

    return [_cluster_median(c) for c in clusters]


def build_sequence(rows):
    """Build the wear-indexed lap sequence for one compound.

    Steps:
      1) Sort observations by Tire wear on start.
      2) Merge near-duplicate observations (different stints sampling the
         same tire-age range) into median-valued clusters.
      3) Walk consecutive (merged) pairs; where the wear gap exceeds 1.5 ×
         the local wear/lap, insert linearly-interpolated synthetic laps.
      4) Back-extrapolate to 0 % wear using a regression over the first 5
         entries (lap_time, wear_delta, fuel_delta each vs sequence pos).
      5) Forward-extrapolate to 80 % wear with the same kind of regression
         over the last 5 entries.
      6) Enforce monotonic non-decreasing lap_time via PAVA (isotonic
         regression). wear_delta and fuel_delta are left alone — both can
         legitimately fall as fuel burns off and the track rubbers in.

    Returns a dict with:
      - "laps": list of per-lap dicts (lap_time, wear_delta, fuel_delta,
                wear_on_start), indexed chronologically from 0 % wear.
      - "cum_time" / "cum_fuel": cumulative-sum arrays (length len+1, with
                cum[0] = 0) so stint_time / stint_fuel are O(1).
      - "max_laps": len of the laps list (number of laps before hitting the
                80 % wear cap).
    """
    if not rows:
        return []

    sorted_rows = sorted(rows, key=lambda r: r["wear_on_start"])
    global_median_wear = statistics.median(r["wear_delta"] for r in sorted_rows)
    if global_median_wear <= 0:
        global_median_wear = 1.0  # safety: keep arithmetic well-defined

    merged = _merge_overlapping(sorted_rows, global_median_wear)

    sequence = [dict(merged[0])]
    for i in range(len(merged) - 1):
        a = merged[i]
        b = merged[i + 1]
        gap = b["wear_on_start"] - (a["wear_on_start"] + a["wear_delta"])
        window = merged[max(0, i - 2):i + 1] + merged[i + 1:i + 4]
        if window:
            local_wpl = statistics.median(r["wear_delta"] for r in window)
        else:
            local_wpl = global_median_wear
        if local_wpl <= 0:
            local_wpl = global_median_wear

        if gap > GAP_DETECTION_MULTIPLIER * local_wpl:
            m = max(1, round(gap / local_wpl))
            for j in range(1, m + 1):
                t = j / (m + 1)
                sequence.append({
                    "lap_time":      a["lap_time"]      + (b["lap_time"]      - a["lap_time"])      * t,
                    "wear_delta":    a["wear_delta"]    + (b["wear_delta"]    - a["wear_delta"])    * t,
                    "fuel_delta":    a["fuel_delta"]    + (b["fuel_delta"]    - a["fuel_delta"])    * t,
                    "wear_on_start": a["wear_on_start"] + (b["wear_on_start"] - a["wear_on_start"]) * t,
                })
        sequence.append(dict(b))

    # Backward extrapolation to 0 % wear.
    head = sequence[:min(EXTRAPOLATION_WINDOW, len(sequence))]
    head_positions = list(range(len(head)))
    lt_slope, lt_int = linear_fit(head_positions, [r["lap_time"]   for r in head])
    wd_slope, wd_int = linear_fit(head_positions, [r["wear_delta"] for r in head])
    fd_slope, fd_int = linear_fit(head_positions, [r["fuel_delta"] for r in head])

    current_start = sequence[0]["wear_on_start"]
    backward = []
    pos = -1
    while True:
        wd = wd_int + wd_slope * pos
        if wd <= 0:
            break
        new_start = current_start - wd
        if new_start <= 0:
            break
        backward.append({
            "lap_time":      lt_int + lt_slope * pos,
            "wear_delta":    wd,
            "fuel_delta":    fd_int + fd_slope * pos,
            "wear_on_start": new_start,
        })
        current_start = new_start
        pos -= 1
    backward.reverse()
    sequence = backward + sequence

    # Forward extrapolation to 80 % wear.
    tail_size = min(EXTRAPOLATION_WINDOW, len(sequence))
    tail = sequence[-tail_size:]
    tail_positions = list(range(len(sequence) - tail_size, len(sequence)))
    lt_slope, lt_int = linear_fit(tail_positions, [r["lap_time"]   for r in tail])
    wd_slope, wd_int = linear_fit(tail_positions, [r["wear_delta"] for r in tail])
    fd_slope, fd_int = linear_fit(tail_positions, [r["fuel_delta"] for r in tail])

    cumulative_end = sequence[-1]["wear_on_start"] + sequence[-1]["wear_delta"]
    pos = len(sequence)
    while cumulative_end < WEAR_CEILING:
        wd = wd_int + wd_slope * pos
        if wd <= 0:
            break
        sequence.append({
            "lap_time":      lt_int + lt_slope * pos,
            "wear_delta":    wd,
            "fuel_delta":    fd_int + fd_slope * pos,
            "wear_on_start": cumulative_end,
        })
        cumulative_end += wd
        pos += 1

    smoothed = _isotonic_lap_times([r["lap_time"] for r in sequence])
    for r, lt in zip(sequence, smoothed):
        r["lap_time"] = lt

    cum_time = [0.0]
    cum_fuel = [0.0]
    for entry in sequence:
        cum_time.append(cum_time[-1] + entry["lap_time"])
        cum_fuel.append(cum_fuel[-1] + entry["fuel_delta"])
    return {
        "laps": sequence,
        "cum_time": cum_time,
        "cum_fuel": cum_fuel,
        "max_laps": len(sequence),
    }


def stint_time(seq, length, start_idx=0):
    """Time for a stint of `length` laps starting from sequence position
    `start_idx`. start_idx > 0 represents a used tire being re-fitted at
    some accumulated wear; start_idx = 0 is a fresh tire."""
    return seq["cum_time"][start_idx + length] - seq["cum_time"][start_idx]


def stint_fuel(seq, length, start_idx=0):
    return seq["cum_fuel"][start_idx + length] - seq["cum_fuel"][start_idx]


def wear_to_position(seq, target_wear):
    """Position in the wear-sorted sequence whose `wear_on_start` first
    reaches `target_wear`. Returns max_laps if target is past the 80 %
    ceiling (i.e. the tire is effectively dead)."""
    laps = seq["laps"]
    for i in range(len(laps)):
        if laps[i]["wear_on_start"] >= target_wear:
            return i
    return seq["max_laps"]


def compute_end_wear(seq, start_idx, length):
    """Wear at the END of a stint that ran `length` laps starting at
    sequence position `start_idx`."""
    if length <= 0:
        return seq["laps"][start_idx]["wear_on_start"]
    end = seq["laps"][start_idx + length - 1]
    return end["wear_on_start"] + end["wear_delta"]


def search_one_stop(sequences, total_laps, pit_loss):
    """≥2 distinct supplied compounds required (F1 rule). Returns the
    fastest legal 1-stop plan or None if no compound pair keeps both
    stints under 80 % wear."""
    best = None
    compounds = list(sequences.keys())
    for a in compounds:
        for b in compounds:
            if a == b:
                continue
            seq_a, seq_b = sequences[a], sequences[b]
            max_a, max_b = seq_a["max_laps"], seq_b["max_laps"]
            for k in range(1, total_laps):
                if k > max_a:
                    break
                rest = total_laps - k
                if rest < 1 or rest > max_b:
                    continue
                total = stint_time(seq_a, k) + stint_time(seq_b, rest) + pit_loss
                if best is None or total < best["total"]:
                    best = {
                        "stints": [(a, k), (b, rest)],
                        "total": total,
                        "fuel": stint_fuel(seq_a, k) + stint_fuel(seq_b, rest),
                    }
    return best


def search_two_stop(sequences, total_laps, pit_loss):
    """≥2 distinct compounds across the three stints. Returns the fastest
    legal 2-stop plan or None."""
    best = None
    compounds = list(sequences.keys())
    for a in compounds:
        for b in compounds:
            for c in compounds:
                if a == b == c:
                    continue
                seq_a, seq_b, seq_c = sequences[a], sequences[b], sequences[c]
                max_a, max_b, max_c = seq_a["max_laps"], seq_b["max_laps"], seq_c["max_laps"]
                for k1 in range(1, total_laps - 1):
                    if k1 > max_a:
                        break
                    for k2 in range(1, total_laps - k1):
                        if k2 > max_b:
                            break
                        k3 = total_laps - k1 - k2
                        if k3 < 1 or k3 > max_c:
                            continue
                        total = (stint_time(seq_a, k1)
                                 + stint_time(seq_b, k2)
                                 + stint_time(seq_c, k3)
                                 + 2 * pit_loss)
                        if best is None or total < best["total"]:
                            best = {
                                "stints": [(a, k1), (b, k2), (c, k3)],
                                "total": total,
                                "fuel": (stint_fuel(seq_a, k1)
                                         + stint_fuel(seq_b, k2)
                                         + stint_fuel(seq_c, k3)),
                            }
    return best


def _historical_summary(state, sequences, pit_loss):
    """Compute aggregate (time, fuel) and an annotated stint list for the
    portion of the race that has already happened."""
    stints = []
    total_time = 0.0
    total_fuel = 0.0
    for cs in state["completed_stints"]:
        seq = sequences[cs["compound"]]
        start_idx = wear_to_position(seq, cs["start_wear"])
        total_time += stint_time(seq, cs["length"], start_idx)
        total_fuel += stint_fuel(seq, cs["length"], start_idx)
        stints.append({
            "compound": cs["compound"],
            "length": cs["length"],
            "source": cs["source"],
            "start_wear": cs["start_wear"],
            "phase": "done",
        })
    total_time += len(state["completed_stints"]) * pit_loss
    return stints, total_time, total_fuel


def _stint_entry(current_set, length, phase):
    return {
        "compound": current_set["compound"],
        "length": length,
        "source": current_set["source"],
        "start_wear": current_set["wear"],
        "phase": phase,
    }


def search_live(state, total_laps, pit_loss, sequences, forced_next_pit_lap=None):
    """Recursive search for the fastest legal continuation of the race.

    Historical (completed) stints are locked. The currently-mounted set's
    compound is locked but its remaining length is a search variable.
    Up to MAX_FUTURE_PITS more pits may be added; at each, the next set
    is either a fresh inventory unit or the least-worn used set of a
    compound (the "least-worn" convention matches the UI rule for how
    the user enters "<lap> <compound> used").

    Sets returning to the used pool keep their accumulated wear, so the
    same physical set can be re-fitted later as long as its starting
    wear leaves it room under 80 % for the next stint.

    If `forced_next_pit_lap` is set, the first future pit must happen at
    exactly that lap — used by the hypothetical-pit prompt to answer
    "if I pit here, which tire and what's optimal after?". The
    no-more-pits ("run to end of race") option is disabled for the
    first decision in that case, since the user is asking *given* a
    pit at that lap."""
    historical_stints, historical_time, historical_fuel = _historical_summary(
        state, sequences, pit_loss)
    best = [None]

    def explore(future_stints, current_set, fresh_inv, used_pool, current_lap,
                accum_time, accum_fuel, pits_done):
        seq = sequences[current_set["compound"]]
        start_idx = wear_to_position(seq, current_set["wear"])
        remaining = total_laps - current_lap
        max_remaining = seq["max_laps"] - start_idx
        is_forced_first = forced_next_pit_lap is not None and pits_done == 0

        # Option A: keep current set on for the rest of the race.
        # Skip when the user forced a first pit (they're asking *given* a pit).
        if not is_forced_first and 1 <= remaining <= max_remaining:
            stint_t = stint_time(seq, remaining, start_idx)
            stint_f = stint_fuel(seq, remaining, start_idx)
            full = (historical_stints + future_stints
                    + [_stint_entry(current_set, remaining,
                                    "current" if pits_done == 0 else "future")])
            if len({s["compound"] for s in full}) >= 2:
                total = accum_time + stint_t
                if best[0] is None or total < best[0]["total"]:
                    best[0] = {
                        "stints": full,
                        "total": total,
                        "fuel": accum_fuel + stint_f,
                    }

        # Option B: pit at some lap, then pick a tire and continue
        if pits_done >= MAX_FUTURE_PITS:
            return

        if is_forced_first:
            forced_len = forced_next_pit_lap - current_lap
            if forced_len < 1 or forced_len > max_remaining:
                return
            stint_lens = [forced_len]
        else:
            stint_lens = range(1, min(remaining, max_remaining) + 1)

        for stint_len in stint_lens:
            pit_lap = current_lap + stint_len
            if pit_lap >= total_laps:
                break
            stint_t = stint_time(seq, stint_len, start_idx)
            stint_f = stint_fuel(seq, stint_len, start_idx)
            end_wear = compute_end_wear(seq, start_idx, stint_len)

            stint_entry = _stint_entry(current_set, stint_len,
                                       "current" if pits_done == 0 else "future")
            next_future = future_stints + [stint_entry]
            next_used = used_pool + [{"compound": current_set["compound"],
                                      "wear": end_wear}]
            next_time = accum_time + stint_t + pit_loss
            next_fuel = accum_fuel + stint_f

            # Fresh tire choices
            for c in fresh_inv:
                if fresh_inv[c] <= 0:
                    continue
                new_fresh = dict(fresh_inv)
                new_fresh[c] -= 1
                explore(
                    next_future,
                    {"compound": c, "wear": 0.0, "source": "fresh"},
                    new_fresh, next_used, pit_lap,
                    next_time, next_fuel, pits_done + 1,
                )

            # Re-fit choices (least-worn used set per compound)
            for c in sequences:
                of_c = [(i, u) for i, u in enumerate(next_used)
                        if u["compound"] == c]
                if not of_c:
                    continue
                lw_idx, lw_set = min(of_c, key=lambda x: x[1]["wear"])
                if wear_to_position(sequences[c], lw_set["wear"]) >= sequences[c]["max_laps"]:
                    continue
                new_used = next_used[:lw_idx] + next_used[lw_idx + 1:]
                explore(
                    next_future,
                    {"compound": c, "wear": lw_set["wear"], "source": "used"},
                    fresh_inv, new_used, pit_lap,
                    next_time, next_fuel, pits_done + 1,
                )

    explore([], state["current_set"], state["fresh_inventory"],
            list(state["used_pool"]), state["current_stint_start_lap"],
            historical_time, historical_fuel, 0)
    return best[0]


def pit_windows(plan_stints, optimal_total, sequences,
                tolerance=PIT_WINDOW_TOLERANCE):
    """For each non-done pit in `plan_stints`, return (earliest_lap,
    latest_lap) — the inclusive range of pit laps that keep total race
    time within `tolerance` seconds of `optimal_total`, holding every
    other pit at its optimal lap.

    The neighbouring stint's length is adjusted to compensate so that
    pit p+1 stays put: if pit p moves earlier by k laps, stint p+1
    starts k laps earlier and ends at the same lap. This matches the
    spec "other pitstops are optimal".

    Accepts both default-mode (`(compound, length)` tuple) and live-mode
    (dict with `compound`, `length`, `start_wear`, `phase` keys) stint
    formats. Returns dict keyed by stint index (the stint whose end is
    the pit). Done-phase stints are skipped; the final stint has no
    trailing pit.
    """
    norm = []
    for s in plan_stints:
        if isinstance(s, tuple):
            compound, length = s
            start_idx = 0
            phase = "future"
        else:
            compound = s["compound"]
            length = s["length"]
            phase = s["phase"]
            start_idx = (0 if phase == "done"
                         else wear_to_position(sequences[compound], s["start_wear"]))
        norm.append({
            "length": length,
            "start_idx": start_idx,
            "phase": phase,
            "sequence": sequences[compound],
        })

    if len(norm) < 2:
        return {}

    windows = {}
    for p in range(len(norm) - 1):
        if norm[p]["phase"] == "done":
            continue
        s_a, s_b = norm[p], norm[p + 1]
        original_a, original_b = s_a["length"], s_b["length"]
        combined = original_a + original_b
        max_a = s_a["sequence"]["max_laps"] - s_a["start_idx"]
        max_b = s_b["sequence"]["max_laps"] - s_b["start_idx"]

        t_a = stint_time(s_a["sequence"], original_a, s_a["start_idx"])
        t_b = stint_time(s_b["sequence"], original_b, s_b["start_idx"])
        other_time = optimal_total - t_a - t_b  # all other stints + pit losses

        start_of_stint_p = sum(norm[i]["length"] for i in range(p))

        earliest = None
        latest = None
        for alt_a in range(1, combined):
            alt_b = combined - alt_a
            if alt_a > max_a or alt_b > max_b:
                continue
            alt_total = (other_time
                         + stint_time(s_a["sequence"], alt_a, s_a["start_idx"])
                         + stint_time(s_b["sequence"], alt_b, s_b["start_idx"]))
            if alt_total <= optimal_total + tolerance:
                pit_lap = start_of_stint_p + alt_a
                if earliest is None or pit_lap < earliest:
                    earliest = pit_lap
                if latest is None or pit_lap > latest:
                    latest = pit_lap

        if earliest is not None:
            windows[p] = (earliest, latest)
    return windows


CHART_COLORS = {"SOF": "#d62728", "MED": "#ff8c00", "HAR": "#808080"}


def write_chart(path, sequences):
    """Write a hand-rolled SVG line chart of lap_time vs lap number for
    each supplied compound. X-axis spans 1 .. max_laps across all
    compounds; Y-axis spans from the fastest to the slowest lap observed
    (with ~5% padding so lines don't sit on the frame). Stdlib only —
    deliberately avoids matplotlib / Pillow to keep strategist.py
    dependency-free.
    """
    W, H = 900, 540
    pad_l, pad_r, pad_t, pad_b = 80, 140, 30, 60
    plot_w = W - pad_l - pad_r
    plot_h = H - pad_t - pad_b

    max_laps = max(seq["max_laps"] for seq in sequences.values())
    all_times = [r["lap_time"] for seq in sequences.values() for r in seq["laps"]]
    y_max, y_min = max(all_times), min(all_times)
    y_pad = (y_max - y_min) * 0.05 if y_max > y_min else 1.0
    y_lo, y_hi = y_min - y_pad, y_max + y_pad
    x_divisor = max_laps - 1 if max_laps > 1 else 1

    def x_coord(lap):  # lap is 1-indexed
        return pad_l + (lap - 1) / x_divisor * plot_w

    def y_coord(t):
        return pad_t + (1 - (t - y_lo) / (y_hi - y_lo)) * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" stroke="black"/>',
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" '
        f'y2="{pad_t + plot_h}" stroke="black"/>',
    ]

    x_step = 5
    x_tick_laps = list(range(x_step, max_laps + 1, x_step))

    # Y ticks: anchor labels at the actual min and max lap times, then
    # add whole-number ticks in between — but skip any whole number whose
    # pixel position is too close to the min/max label to render cleanly.
    min_label_y = y_coord(y_min)
    max_label_y = y_coord(y_max)
    MIN_LABEL_GAP_PX = 15
    y_ticks = [(y_min, f"{y_min:.2f}")]
    for w in range(math.ceil(y_min), math.floor(y_max) + 1):
        yp = y_coord(w)
        if abs(yp - min_label_y) < MIN_LABEL_GAP_PX:
            continue
        if abs(yp - max_label_y) < MIN_LABEL_GAP_PX:
            continue
        y_ticks.append((w, str(w)))
    y_ticks.append((y_max, f"{y_max:.2f}"))

    # Light gridlines first so axes / ticks / data overlay them cleanly.
    for lap in x_tick_laps:
        x = x_coord(lap)
        parts.append(f'<line x1="{x:.1f}" y1="{pad_t}" '
                     f'x2="{x:.1f}" y2="{pad_t + plot_h}" '
                     f'stroke="#eeeeee" stroke-width="1"/>')
    for value, _ in y_ticks:
        y = y_coord(value)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" '
                     f'x2="{pad_l + plot_w}" y2="{y:.1f}" '
                     f'stroke="#dddddd" stroke-width="1"/>')

    for lap in x_tick_laps:
        x = x_coord(lap)
        parts.append(f'<line x1="{x:.1f}" y1="{pad_t + plot_h}" '
                     f'x2="{x:.1f}" y2="{pad_t + plot_h + 5}" stroke="black"/>')
        parts.append(f'<text x="{x:.1f}" y="{pad_t + plot_h + 18}" '
                     f'font-family="sans-serif" font-size="11" '
                     f'text-anchor="middle">{lap}</text>')
    parts.append(f'<text x="{pad_l + plot_w / 2}" y="{H - 15}" '
                 f'font-family="sans-serif" font-size="13" '
                 f'text-anchor="middle">Lap</text>')

    for value, label in y_ticks:
        y = y_coord(value)
        parts.append(f'<line x1="{pad_l - 5}" y1="{y:.1f}" '
                     f'x2="{pad_l}" y2="{y:.1f}" stroke="black"/>')
        parts.append(f'<text x="{pad_l - 8}" y="{y + 4:.1f}" '
                     f'font-family="sans-serif" font-size="11" '
                     f'text-anchor="end">{label}</text>')
    parts.append(f'<text x="20" y="{pad_t + plot_h / 2}" '
                 f'font-family="sans-serif" font-size="13" '
                 f'text-anchor="middle" '
                 f'transform="rotate(-90 20,{pad_t + plot_h / 2})">'
                 f'Lap time (s)</text>')

    for compound in ("SOF", "MED", "HAR"):
        if compound not in sequences:
            continue
        laps = sequences[compound]["laps"]
        pts = " ".join(f"{x_coord(i + 1):.1f},{y_coord(r['lap_time']):.1f}"
                       for i, r in enumerate(laps))
        parts.append(f'<polyline points="{pts}" fill="none" '
                     f'stroke="{CHART_COLORS[compound]}" stroke-width="2"/>')

    legend_x = pad_l + plot_w + 20
    legend_y = pad_t + 10
    line_i = 0
    for compound in ("SOF", "MED", "HAR"):
        if compound not in sequences:
            continue
        y = legend_y + line_i * 22
        parts.append(f'<line x1="{legend_x}" y1="{y}" '
                     f'x2="{legend_x + 24}" y2="{y}" '
                     f'stroke="{CHART_COLORS[compound]}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x + 30}" y="{y + 4}" '
                     f'font-family="sans-serif" font-size="12">'
                     f'{COMPOUND_LABEL[compound]}</text>')
        line_i += 1

    parts.append('</svg>')
    with open(path, "w") as f:
        f.write("\n".join(parts))


def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:06.3f}"


def format_plan(label, plan, sequences):
    if plan is None:
        return f"{label}: not possible (would exceed 80% tire wear)"
    windows = pit_windows(plan["stints"], plan["total"], sequences)
    lines = [f"{label}:"]
    for i, (compound, laps) in enumerate(plan["stints"]):
        w = windows.get(i)
        suffix = f" ({w[0]}-{w[1]})" if w else ""
        lines.append(f"  Stint {i+1}: {compound}, {laps} laps{suffix}")
    lines.append(f"  Starting fuel: {plan['fuel']:.3f} kg")
    lines.append(f"  Estimated race time: {format_time(plan['total'])}")
    return "\n".join(lines)


def main():
    args = parse_args()
    flag_to_path = {
        "SOF": args.soft,
        "MED": args.medium,
        "HAR": args.hard,
    }
    supplied = {c: p for c, p in flag_to_path.items() if p is not None}
    if len(supplied) < 2:
        print("Error: at least two compound files must be supplied "
              "(--soft, --medium, --hard).", file=sys.stderr)
        return 2

    print("strategist.py - wear-sorted pace model.")
    print("Every row in the input files is treated as a representative racing lap.")
    print("Delete in-laps, out-laps, traffic laps, etc. from your CSVs before running.")
    print()

    sequences = {}
    for compound, path in supplied.items():
        try:
            rows = read_compound_rows(path, compound)
        except OSError as e:
            print(f"Error reading {path}: {e}", file=sys.stderr)
            return 1
        except csv.Error as e:
            print(f"Error parsing {path}: {e}", file=sys.stderr)
            return 1
        if not rows:
            print(f"Error: no rows matching compound {compound} in {path}.",
                  file=sys.stderr)
            return 1
        sequences[compound] = build_sequence(rows)

    if args.chart:
        try:
            write_chart(args.chart, sequences)
        except OSError as e:
            print(f"Error writing chart to {args.chart}: {e}", file=sys.stderr)
            return 1
        print(f"Wrote chart to {args.chart}")
        print()

    total_laps = prompt_positive_int("Race duration (laps): ")
    pit_loss = prompt_positive_int("Pit-stop time lost (seconds): ")
    print()

    if not args.live_strategy:
        one_stop = search_one_stop(sequences, total_laps, pit_loss)
        two_stop = search_two_stop(sequences, total_laps, pit_loss)
        print(format_plan("1-stop strategy", one_stop, sequences))
        print()
        print(format_plan("2-stop strategy", two_stop, sequences))
        return 0

    # --live-strategy: track an in-progress race. Ask for the tire
    # inventory and starting compound, then enter a prompt loop that
    # consumes actual pit events as they happen and re-plans the rest of
    # the race after each one. Per-set wear is tracked so that re-fitting
    # a used set is a possible option whenever it would be faster.
    fresh_inventory = {}
    for code in ("SOF", "MED", "HAR"):
        if code in sequences:
            fresh_inventory[code] = prompt_non_negative_int(
                f"How many {COMPOUND_PLURAL[code]} do you have for the race? ")
        else:
            fresh_inventory[code] = 0

    available_for_start = {c for c in sequences if fresh_inventory[c] > 0}
    if not available_for_start:
        print("Error: no tires available for any provided compound — "
              "nothing to start the race on.", file=sys.stderr)
        return 1

    starting = prompt_compound("What compound are we starting on? ", available_for_start)
    fresh_inventory[starting] -= 1

    state = {
        "starting_compound": starting,
        "fresh_inventory": fresh_inventory,
        "used_pool": [],
        "current_set": {"compound": starting, "wear": 0.0, "source": "fresh"},
        "completed_stints": [],
        "current_stint_start_lap": 0,
    }

    print()
    plan = search_live(state, total_laps, pit_loss, sequences)
    print(format_live_plan(plan, state, total_laps, sequences))
    print()

    while True:
        try:
            raw = input("Enter pit ('22' hypothetical, '22 medium' actual, "
                        "'22 medium used' refit), blank line / Ctrl-D to exit: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw:
            print()
            return 0
        parsed, err = parse_pit_entry(raw, state["current_stint_start_lap"], total_laps)
        if err:
            print("  " + err)
            continue
        lap, compound, source = parsed

        print()
        if compound is None:
            # Hypothetical: ask "what's optimal IF I pit here?" without
            # mutating state.
            plan = search_live(state, total_laps, pit_loss, sequences,
                               forced_next_pit_lap=lap)
            print(format_live_plan(plan, state, total_laps, sequences,
                                   hypothetical_lap=lap))
        else:
            err = _apply_pit(state, lap, compound, source, sequences)
            if err:
                print("  " + err)
                print()
                continue
            plan = search_live(state, total_laps, pit_loss, sequences)
            print(format_live_plan(plan, state, total_laps, sequences))
        print()


if __name__ == "__main__":
    sys.exit(main())
