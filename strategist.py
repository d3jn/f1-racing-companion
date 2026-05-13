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
import statistics
import sys

WEAR_CEILING = 80.0           # percent; running past this is prohibited
GAP_DETECTION_MULTIPLIER = 1.5  # gap > 1.5 × local wear/lap → real gap
EXTRAPOLATION_WINDOW = 5      # head/tail laps used to fit extrapolation regressions

COMPOUND_FLAGS = {"soft": "SOF", "medium": "MED", "hard": "HAR"}


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


def build_sequence(rows):
    """Build the wear-indexed lap sequence for one compound.

    Steps:
      1) Sort observations by Tire wear on start.
      2) Walk consecutive pairs; where the wear gap exceeds 1.5 × the local
         wear/lap, insert linearly-interpolated synthetic laps.
      3) Back-extrapolate to 0 % wear using a regression over the first 5
         entries (the regression covers lap_time, wear_delta, fuel_delta).
      4) Forward-extrapolate to 80 % wear with the same kind of regression
         over the last 5 entries.

    Returns a list of dicts (one per lap, indexed chronologically from 0%
    wear) with keys: lap_time, wear_delta, fuel_delta, wear_on_start.
    """
    if not rows:
        return []

    sorted_rows = sorted(rows, key=lambda r: r["wear_on_start"])
    global_median_wear = statistics.median(r["wear_delta"] for r in sorted_rows)
    if global_median_wear <= 0:
        global_median_wear = 1.0  # safety: keep arithmetic well-defined

    sequence = [dict(sorted_rows[0])]
    for i in range(len(sorted_rows) - 1):
        a = sorted_rows[i]
        b = sorted_rows[i + 1]
        gap = b["wear_on_start"] - (a["wear_on_start"] + a["wear_delta"])
        local_window = sorted_rows[max(0, i - 2):i + 1] + sorted_rows[i + 1:i + 4]
        if local_window:
            local_wpl = statistics.median(r["wear_delta"] for r in local_window)
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

    return sequence


def stint_time(seq, laps):
    return sum(r["lap_time"] for r in seq[:laps])


def stint_fuel(seq, laps):
    return sum(r["fuel_delta"] for r in seq[:laps])


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
            max_a, max_b = len(seq_a), len(seq_b)
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
                max_a, max_b, max_c = len(seq_a), len(seq_b), len(seq_c)
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


def format_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:06.3f}"


def format_plan(label, plan):
    if plan is None:
        return f"{label}: not possible (would exceed 80% tire wear)"
    lines = [f"{label}:"]
    for i, (compound, laps) in enumerate(plan["stints"], 1):
        lines.append(f"  Stint {i}: {compound}, {laps} laps")
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

    total_laps = prompt_positive_int("Race duration (laps): ")
    pit_loss = prompt_positive_int("Pit-stop time lost (seconds): ")
    print()

    one_stop = search_one_stop(sequences, total_laps, pit_loss)
    two_stop = search_two_stop(sequences, total_laps, pit_loss)

    print(format_plan("1-stop strategy", one_stop))
    print()
    print(format_plan("2-stop strategy", two_stop))
    return 0


if __name__ == "__main__":
    sys.exit(main())
