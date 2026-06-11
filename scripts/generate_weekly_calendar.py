#!/usr/bin/env python3
"""Generate weekly calendar-view PNGs from daycare_log.csv.

Each week of data (Monday-Sunday) becomes one image named after the
Monday of that week, e.g. "June 8th.png". Every event in the log is drawn
as a "meeting" block on the day it occurred:

  - Events with a real duration (naps) span their actual start-end time.
  - Events with no end time (or end == start) are drawn as 10-minute blocks.

The vertical axis covers the hours between the earliest drop-off and the
latest pick-up seen that week. Each Action gets its own color. Overlapping
events on the same day are laid out side by side, calendar-app style.
"""

import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Patch

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "daycare_log.csv"
OUTPUT_DIR = REPO_ROOT / "weekly_views"

DEFAULT_DURATION = timedelta(minutes=10)

# One color per action; anything new in the log falls back to the extras.
ACTION_COLORS = {
    "Check In": "#4CAF50",
    "Check Out": "#F44336",
    "Nap": "#7E57C2",
    "Meal": "#FF9800",
    "Bottle": "#29B6F6",
    "Diaper": "#8D6E63",
    "Incident": "#EC407A",
    "Activity": "#26A69A",
    "Medication": "#FFD54F",
}
EXTRA_COLORS = ["#5C6BC0", "#9CCC65", "#FF7043", "#78909C", "#AB47BC"]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


def ordinal(n: int) -> str:
    if 11 <= n % 100 <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def parse_time(value: str):
    value = value.strip().lower()
    if not value:
        return None
    for fmt in ("%I:%M%p", "%I:%M %p", "%H:%M"):
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    return None


def time_to_hours(t) -> float:
    return t.hour + t.minute / 60 + t.second / 3600


def load_events(csv_path: Path):
    """Return events grouped by the Monday of their week, then by date."""
    weeks = defaultdict(lambda: defaultdict(list))
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                day = datetime.strptime(row["Date"].strip(), "%Y-%m-%d").date()
            except (ValueError, KeyError):
                continue
            start = parse_time(row.get("Start_Time", ""))
            if start is None:
                continue
            end = parse_time(row.get("End_Time", ""))
            start_h = time_to_hours(start)
            if end is None or end <= start:
                end_h = start_h + DEFAULT_DURATION.total_seconds() / 3600
            else:
                end_h = time_to_hours(end)
            monday = day - timedelta(days=day.weekday())
            weeks[monday][day].append({
                "action": row.get("Action", "").strip() or "Event",
                "type": row.get("Type", "").strip(),
                "start": start_h,
                "end": end_h,
                "instant": end is None or end <= start,
            })
    return weeks


def assign_columns(events):
    """Calendar-style overlap layout: give concurrent events side-by-side
    columns and tell each event how many columns its cluster uses."""
    events = sorted(events, key=lambda e: (e["start"], e["end"]))
    cluster, cluster_end = [], None
    clusters = []
    for ev in events:
        if cluster and ev["start"] >= cluster_end:
            clusters.append(cluster)
            cluster, cluster_end = [], None
        cluster.append(ev)
        cluster_end = ev["end"] if cluster_end is None else max(cluster_end, ev["end"])
    if cluster:
        clusters.append(cluster)

    for cluster in clusters:
        col_ends = []  # last end time per column
        for ev in cluster:
            for i, col_end in enumerate(col_ends):
                if ev["start"] >= col_end:
                    ev["col"] = i
                    col_ends[i] = ev["end"]
                    break
            else:
                ev["col"] = len(col_ends)
                col_ends.append(ev["end"])
        for ev in cluster:
            ev["ncols"] = len(col_ends)
    return events


def hour_label(h: int) -> str:
    if h == 0 or h == 24:
        return "12 AM"
    if h == 12:
        return "12 PM"
    return f"{h % 12} {'AM' if h < 12 else 'PM'}"


def fmt_clock(hours: float) -> str:
    h = int(hours) % 24
    m = int(round((hours - int(hours)) * 60))
    if m == 60:
        h, m = (h + 1) % 24, 0
    suffix = "am" if h < 12 else "pm"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d}{suffix}"


def color_for(action: str, palette: dict) -> str:
    if action not in palette:
        palette[action] = EXTRA_COLORS[len(palette) % len(EXTRA_COLORS)]
    return palette[action]


def render_week(monday: date, days: dict, output_dir: Path):
    all_events = [ev for evs in days.values() for ev in evs]
    if not all_events:
        return None

    # Show Sat/Sun only if something actually happened on a weekend.
    n_days = 7 if any(d.weekday() >= 5 for d in days) else 5

    hour_min = int(min(ev["start"] for ev in all_events))
    hour_max = int(max(ev["end"] for ev in all_events)) + 1
    hour_max = min(hour_max, 24)

    palette = dict(ACTION_COLORS)
    fig, ax = plt.subplots(figsize=(2.6 * n_days + 1.2, 1.0 * (hour_max - hour_min) + 2.2))
    fig.patch.set_facecolor("white")

    ax.set_xlim(0, n_days)
    ax.set_ylim(hour_max, hour_min)  # earlier hours at the top
    ax.set_xticks([])
    ax.set_yticks(range(hour_min, hour_max + 1))
    ax.set_yticklabels([hour_label(h) for h in range(hour_min, hour_max + 1)],
                       fontsize=9, color="#666666")
    for spine in ax.spines.values():
        spine.set_visible(False)

    for h in range(hour_min, hour_max + 1):
        ax.axhline(h, color="#E0E0E0", linewidth=0.8, zorder=1)
        ax.axhline(h + 0.5, color="#F0F0F0", linewidth=0.5, zorder=1)
    for i in range(n_days + 1):
        ax.axvline(i, color="#D6D6D6", linewidth=0.8, zorder=1)

    used_actions = {}
    for offset in range(n_days):
        day = monday + timedelta(days=offset)
        ax.text(offset + 0.5, hour_min - 0.35,
                f"{DAY_NAMES[offset][:3]} {day.month}/{day.day}",
                ha="center", va="bottom", fontsize=11, fontweight="bold",
                color="#1A73E8" if day == date.today() else "#444444")

        for ev in assign_columns(days.get(day, [])):
            pad = 0.03
            width = (1 - 2 * pad) / ev["ncols"]
            x = offset + pad + ev["col"] * width
            color = color_for(ev["action"], palette)
            used_actions[ev["action"]] = color
            ax.add_patch(FancyBboxPatch(
                (x + 0.01, ev["start"]), width - 0.02, ev["end"] - ev["start"],
                boxstyle="round,pad=0,rounding_size=0.02",
                facecolor=color, edgecolor="white", linewidth=0.8,
                alpha=0.9, zorder=3, mutation_aspect=1 / 2.6))
            # Drop the subtype on narrow (overlapping) boxes so text fits.
            if ev["type"] and ev["ncols"] == 1:
                label = f"{ev['action']}: {ev['type']}"
            else:
                label = ev["action"]
            duration = ev["end"] - ev["start"]
            if duration >= 0.4:
                text = f"{label}\n{fmt_clock(ev['start'])}–{fmt_clock(ev['end'])}"
                fontsize = 7.5
            else:
                text = f"{label} {fmt_clock(ev['start'])}"
                fontsize = 6.5 if ev["ncols"] == 1 else 5.5
            ax.text(x + width / 2, ev["start"] + duration / 2, text,
                    ha="center", va="center", fontsize=fontsize, color="white",
                    fontweight="bold", zorder=4, clip_on=True)

    title_day = f"{monday.strftime('%B')} {ordinal(monday.day)}"
    ax.set_title(f"Jack's Week — {title_day}, {monday.year}",
                 fontsize=15, fontweight="bold", pad=42, color="#333333")

    handles = [Patch(facecolor=c, label=a) for a, c in sorted(used_actions.items())]
    ax.legend(handles=handles, loc="upper center",
              bbox_to_anchor=(0.5, -0.015), ncol=min(len(handles), 6),
              frameon=False, fontsize=9)

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{title_day}.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main():
    if not CSV_PATH.exists():
        sys.exit(f"CSV not found: {CSV_PATH}")
    weeks = load_events(CSV_PATH)
    if not weeks:
        sys.exit("No events found in the log.")
    last_out = None
    for monday in sorted(weeks):
        out = render_week(monday, weeks[monday], OUTPUT_DIR)
        if out:
            print(f"Wrote {out.relative_to(REPO_ROOT)}")
            last_out = out
    if last_out:
        # Stable filename for the most recent week, so it can be embedded.
        latest = OUTPUT_DIR / "latest.png"
        latest.write_bytes(last_out.read_bytes())
        print(f"Wrote {latest.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
