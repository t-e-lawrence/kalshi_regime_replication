"""Analyze engine vs paper-Kalshi distributions; classify by regime;
emit per-meeting and per-regime summary tables.

Inputs:
  data/engine_distributions.csv  — engine-implied probabilities per
      (probe_event_id, observation_date, outcome_id, target_mid_pct).
      Two probability columns: prob_eod (last snapshot of day) and
      prob_daily_avg (averaged across snapshots in the day).

  data/paper_distributions.csv  — Diercks/Katz/Wright (2026)
      Kalshi-derived per-strike daily probabilities. `strike` is the
      lower edge of a 25bp-wide bucket; `target_mid_pct = strike + 0.125`.
      `probability_pct` is in 0-100 scale.

Outputs:
  output/per_meeting.csv       — one row per probe_event_id with regime
                                  classification + summary statistics
  output/regime_summary.json   — sign-match rates by regime
  output/per_day.csv           — per (meeting, day) gaps for plotting

Methodology mirrors Diercks/Katz/Wright §5 (mode over-concentration,
narrower distribution, tail under-allocation) but with two refinements:

  1. Engine snapshot = last-of-day rather than daily average. The
     daily-average construction blurs mode-gap signals because the
     futures market's morning snapshot hasn't yet incorporated late-day
     information that the (faster) Kalshi market HAS by close.

  2. Per-meeting regime classification by paper Kalshi's *minimum*
     mode probability across the 14-day pre-meeting window:
       quiet     : min mode_prob ≥ 0.85  (always confident)
       mixed     : 0.60 ≤ min mode_prob < 0.85
       contested : min mode_prob < 0.60  (genuine uncertainty)
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

REGIME_QUIET_FLOOR = 0.85
REGIME_CONTESTED_CEILING = 0.60

# Diercks-comparable sample window for like-for-like replication of their
# Table 3 Panel B. Their paper says "since 2022" with ~27 meetings. This
# slice (Sept 2022 through Dec 2025) yields exactly 27 meetings and is
# our primary sample for both the replication and the regime extension.
# Set SAMPLE_WINDOW = None to use the full available data (37 meetings,
# July 2021 through March 2026); used in the robustness check.
SAMPLE_WINDOW: tuple[str, str] | None = ("2022-09-21", "2025-12-10")


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _meeting_iso_to_paper_preambles(meeting_iso: str) -> tuple[str, str]:
    """The paper uses FED-{YYMMM} for legacy meetings, KXFED-{YYMMM}
    for those tracked after Kalshi's late-2025 ticker rebrand. We try
    both and use whichever has data."""
    d = _parse_date(meeting_iso)
    yy = d.year % 100
    mmm = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][d.month - 1]
    return f"FED-{yy:02d}{mmm}", f"KXFED-{yy:02d}{mmm}"


def _entropy(probs: list[float]) -> float:
    h = 0.0
    for p in probs:
        if p > 0:
            h -= p * math.log(p)
    return h


def _classify_regime(min_mode_prob: float) -> str:
    if min_mode_prob >= REGIME_QUIET_FLOOR:
        return "quiet"
    if min_mode_prob >= REGIME_CONTESTED_CEILING:
        return "mixed"
    return "contested"


def load_engine_distributions() -> dict[str, dict[date, dict[float, float]]]:
    """Returns {probe_event_id: {date: {target_mid: prob_eod}}}."""
    out: dict[str, dict[date, dict[float, float]]] = defaultdict(lambda: defaultdict(dict))
    path = DATA_DIR / "engine_distributions.csv"
    with path.open() as f:
        for row in csv.DictReader(f):
            ev = row["probe_event_id"]
            d = _parse_date(row["observation_date"])
            tm_raw = row.get("target_mid_pct", "").strip()
            if not tm_raw:
                continue
            tm = round(float(tm_raw), 4)
            prob_raw = row.get("prob_eod", "").strip()
            if not prob_raw:
                continue
            out[ev][d][tm] = float(prob_raw)
    return {ev: dict(days) for ev, days in out.items()}


def load_paper_distributions() -> dict[str, dict[date, dict[float, float]]]:
    """Returns {contract_preamble: {date: {target_mid: prob_0_to_1}}}."""
    out: dict[str, dict[date, dict[float, float]]] = defaultdict(lambda: defaultdict(dict))
    path = DATA_DIR / "paper_distributions.csv"
    with path.open() as f:
        for row in csv.DictReader(f):
            preamble = row["contract_preamble"]
            d = _parse_date(row["observation_date"])
            strike_raw = row.get("strike", "").strip()
            if not strike_raw:
                continue
            strike = float(strike_raw)
            target_mid = round(strike + 0.125, 4)
            if target_mid < 0:
                continue
            prob_raw = row.get("probability_pct", "").strip()
            if not prob_raw:
                continue
            prob = float(prob_raw) / 100.0
            if prob <= 0:
                continue
            out[preamble][d][target_mid] = prob
    return {p: dict(days) for p, days in out.items()}


def gather_one(engine_dist: dict[float, float], paper_dist: dict[float, float]) -> dict[str, Any] | None:
    """Compute mode/spread/tail metrics for one (meeting, day)."""
    if not engine_dist or not paper_dist:
        return None
    e_mode_tm, e_mode_p = max(engine_dist.items(), key=lambda kv: kv[1])
    p_mode_tm, p_mode_p = max(paper_dist.items(), key=lambda kv: kv[1])
    paper_at_engine_mode = paper_dist.get(e_mode_tm, 0.0)
    mode_gap = e_mode_p - paper_at_engine_mode
    e_tail = sum(v for k, v in engine_dist.items() if k != e_mode_tm)
    p_tail = sum(v for k, v in paper_dist.items() if k != e_mode_tm)
    tail_gap = e_tail - p_tail

    common = set(engine_dist.keys()) & set(paper_dist.keys())
    if common:
        e_vec = [engine_dist[k] for k in common]
        p_vec = [paper_dist[k] for k in common]
        e_total, p_total = sum(e_vec), sum(p_vec)
        if e_total > 0 and p_total > 0:
            e_vec = [v / e_total for v in e_vec]
            p_vec = [v / p_total for v in p_vec]
            spread_gap = _entropy(e_vec) - _entropy(p_vec)
        else:
            spread_gap = 0.0
    else:
        spread_gap = 0.0

    return {
        "e_mode_tm": e_mode_tm,
        "e_mode_p": e_mode_p,
        "p_mode_tm": p_mode_tm,
        "p_mode_p": p_mode_p,
        "modes_align": e_mode_tm == p_mode_tm,
        "mode_gap": mode_gap,
        "spread_gap": spread_gap,
        "tail_gap": tail_gap,
    }


def meeting_iso_from_probe_event(probe_event_id: str) -> str:
    return probe_event_id.removeprefix("fed_")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    engine = load_engine_distributions()
    paper = load_paper_distributions()
    per_meeting_rows: list[dict[str, Any]] = []
    per_day_rows: list[dict[str, Any]] = []

    for probe_event_id in sorted(engine.keys()):
        meeting_iso = meeting_iso_from_probe_event(probe_event_id)
        if SAMPLE_WINDOW is not None and not (
            SAMPLE_WINDOW[0] <= meeting_iso <= SAMPLE_WINDOW[1]
        ):
            continue
        legacy, modern = _meeting_iso_to_paper_preambles(meeting_iso)
        paper_dist = paper.get(legacy) or paper.get(modern)
        if paper_dist is None:
            continue
        engine_days = engine[probe_event_id]
        common_days = sorted(set(engine_days.keys()) & set(paper_dist.keys()))
        if not common_days:
            continue

        daily: list[dict[str, Any]] = []
        paper_mode_probs: list[float] = []
        for d in common_days:
            r = gather_one(engine_days[d], paper_dist[d])
            if r is None:
                continue
            r["d"] = d
            daily.append(r)
            paper_mode_probs.append(r["p_mode_p"])
            per_day_rows.append({
                "probe_event_id": probe_event_id,
                "observation_date": d.isoformat(),
                **{k: v for k, v in r.items() if k != "d"},
            })

        if not daily:
            continue
        regime = _classify_regime(min(paper_mode_probs))
        mode_gaps = [r["mode_gap"] for r in daily]
        spread_gaps = [r["spread_gap"] for r in daily]
        tail_gaps = [r["tail_gap"] for r in daily]

        per_meeting_rows.append({
            "probe_event_id": probe_event_id,
            "meeting_date": meeting_iso,
            "regime": regime,
            "n_days": len(daily),
            "paper_min_mode_prob": min(paper_mode_probs),
            "modes_aligned_share": sum(1 for r in daily if r["modes_align"]) / len(daily),
            "mean_mode_gap": statistics.mean(mode_gaps),
            "mean_spread_gap": statistics.mean(spread_gaps),
            "mean_tail_gap": statistics.mean(tail_gaps),
            "last_day_mode_gap": daily[-1]["mode_gap"],
            "last_day_e_mode_p": daily[-1]["e_mode_p"],
            "last_day_p_mode_p": daily[-1]["p_mode_p"],
        })

    # Write per-meeting CSV.
    with (OUTPUT_DIR / "per_meeting.csv").open("w", newline="") as f:
        cols = list(per_meeting_rows[0].keys()) if per_meeting_rows else []
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in per_meeting_rows:
            w.writerow(row)

    # Write per-day CSV.
    with (OUTPUT_DIR / "per_day.csv").open("w", newline="") as f:
        cols = list(per_day_rows[0].keys()) if per_day_rows else []
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in per_day_rows:
            w.writerow(row)

    # Aggregate per regime.
    summary: dict[str, Any] = {"thresholds": {
        "quiet_floor": REGIME_QUIET_FLOOR,
        "contested_ceiling": REGIME_CONTESTED_CEILING,
    }}
    for regime in ("quiet", "mixed", "contested", "all"):
        subset = (
            per_meeting_rows
            if regime == "all"
            else [m for m in per_meeting_rows if m["regime"] == regime]
        )
        if not subset:
            summary[regime] = {"n": 0}
            continue
        n = len(subset)
        mode_pos = sum(1 for m in subset if m["mean_mode_gap"] > 0)
        spread_neg = sum(1 for m in subset if m["mean_spread_gap"] < 0)
        tail_neg = sum(1 for m in subset if m["mean_tail_gap"] < 0)
        last_mode_pos = sum(1 for m in subset if m["last_day_mode_gap"] > 0)
        summary[regime] = {
            "n": n,
            "mode_gap_positive_share": mode_pos / n,
            "spread_gap_negative_share": spread_neg / n,
            "tail_gap_negative_share": tail_neg / n,
            "last_day_mode_gap_positive_share": last_mode_pos / n,
            "median_mode_gap": statistics.median(m["mean_mode_gap"] for m in subset),
            "median_mode_gap_when_positive": (
                statistics.median(
                    m["mean_mode_gap"] for m in subset if m["mean_mode_gap"] > 0
                )
                if any(m["mean_mode_gap"] > 0 for m in subset) else None
            ),
        }

    with (OUTPUT_DIR / "regime_summary.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)

    # Pretty print.
    print(f"\n=== Regime summary ===\n")
    print(f"meetings analyzed: {len(per_meeting_rows)}\n")
    for regime in ("quiet", "mixed", "contested", "all"):
        s = summary[regime]
        if s["n"] == 0:
            continue
        print(
            f"  {regime:<10} n={s['n']:>2}  "
            f"mode_gap>0: {s['mode_gap_positive_share']*100:>3.0f}%  "
            f"spread<0: {s['spread_gap_negative_share']*100:>3.0f}%  "
            f"tail<0: {s['tail_gap_negative_share']*100:>3.0f}%  "
            f"last-day mode>0: {s['last_day_mode_gap_positive_share']*100:>3.0f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
