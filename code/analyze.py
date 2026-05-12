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
narrower distribution, tail under-allocation) but with three refinements:

  1. Engine snapshot = last-of-day rather than daily average. The
     daily-average construction blurs mode-gap signals because the
     futures market's morning snapshot hasn't yet incorporated late-day
     information that the (faster) Kalshi market HAS by close.

  2. Per-meeting regime classification by paper Kalshi's *minimum*
     mode probability across the 14-day pre-meeting window
     (exclusive of the meeting day itself):
       quiet     : min mode_prob ≥ 0.85  (always confident)
       mixed     : 0.60 ≤ min mode_prob < 0.85
       contested : min mode_prob < 0.60  (genuine uncertainty)

  3. Operationalized metric definitions:
       mode_gap   = e_mode_p − p_mode_p
       tail_gap   = (mass ≥2 strikes from each distribution's own
                     mode) — same definition both sides, anchored
                     to the relevant mode. 50bp on a 25bp grid.
       spread_gap = H(engine) − H(paper) on native support.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

REGIME_QUIET_FLOOR = 0.85
REGIME_CONTESTED_CEILING = 0.60

# Pre-meeting horizon: ONLY days within `PRE_MEETING_WINDOW_DAYS` of
# the meeting (exclusive of the meeting day itself) feed into the
# regime classifier.
PRE_MEETING_WINDOW_DAYS = 14
INCLUDE_MEETING_DAY = False  # meeting-day mode prob spikes to ~1.0

# Strike-grid spacing for Fed target-rate buckets. Far-tail threshold for
# tail_gap is 2 * GRID_STEP_PCT (anything ≥2 strikes from the modal
# bucket). DKW-aligned: their tail metrics in stagflation.R are
# explicit "above X / below X" thresholds, equivalent to this for the
# rate grid.
GRID_STEP_PCT = 0.25
TAIL_THRESHOLD_PCT = 2 * GRID_STEP_PCT  # 0.50

# Sample window. Lower bound (2022-09-21) is the first FOMC where
# Kalshi had non-trivial pre-meeting volume on fed-decision contracts,
# matching the DKW Section 6 sample start.
#
# Primary n=29 (Sept 2022 – Mar 2026): used for the headline regime
# tables; covers every meeting where both DKW's published distribution
# file and our engine have data. n=27 (Sept 2022 – Dec 2025) is
# preserved as the "DKW Table 3 Panel B exact-replication" comparator
# — set upper bound to "2025-12-10" to reproduce. Setting
# SAMPLE_WINDOW = None uses the full 37-meeting set (adds 8
# pre-Sept-2022 meetings) for robustness.
SAMPLE_WINDOW: tuple[str, str] | None = ("2022-09-21", "2026-03-18")


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
    """Compute mode/spread/tail metrics for one (meeting, day).

    Metric definitions:

      mode_gap   = e_mode_p − p_mode_p
        Compares the modal probability mass of each distribution —
        symmetric across engine and paper sides, no dependence on
        whether the two modal targets sit on the same strike.

      tail_gap   = e_far_tail − p_far_tail
        where far-tail = sum of mass in buckets ≥2 strikes from the
        distribution's own mode (i.e., excludes mode + adjacent
        buckets — 50bp+ away from the modal target on a 25bp grid).
        Matches DKW's stagflation.R approach (prob_above_X,
        prob_below_X — fixed threshold tails) and keeps tail_gap
        algebraically independent from mode_gap.

      spread_gap = H(engine_dist) − H(paper_dist)
        Shannon entropy (natural log) computed on each distribution's
        native support; 0·log(0)=0 so zero-mass strikes drop out.
    """
    if not engine_dist or not paper_dist:
        return None
    e_mode_tm, e_mode_p = max(engine_dist.items(), key=lambda kv: kv[1])
    p_mode_tm, p_mode_p = max(paper_dist.items(), key=lambda kv: kv[1])
    mode_gap = e_mode_p - p_mode_p

    # Far-tail mass: probability ≥2 strikes from the distribution's
    # own mode (i.e., 50bp+ away on a 25bp grid). DKW-style: same
    # definition applied to both distributions, each anchored to its
    # own mode. Independent of mode_gap by construction.
    e_far_tail = sum(v for k, v in engine_dist.items()
                     if abs(k - e_mode_tm) >= TAIL_THRESHOLD_PCT)
    p_far_tail = sum(v for k, v in paper_dist.items()
                     if abs(k - p_mode_tm) >= TAIL_THRESHOLD_PCT)
    tail_gap = e_far_tail - p_far_tail

    # Spread = entropy on each distribution's native support, no restriction.
    e_total = sum(engine_dist.values())
    p_total = sum(paper_dist.values())
    if e_total > 0 and p_total > 0:
        e_vec = [v / e_total for v in engine_dist.values()]
        p_vec = [v / p_total for v in paper_dist.values()]
        spread_gap = _entropy(e_vec) - _entropy(p_vec)
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
        # Enforce the pre-meeting window. Drop days outside
        # [meeting - PRE_MEETING_WINDOW_DAYS, meeting) so the regime
        # classifier is data-availability-invariant.
        meeting_d = _parse_date(meeting_iso)
        window_lo = meeting_d - timedelta(days=PRE_MEETING_WINDOW_DAYS)
        common_days = [
            d for d in common_days
            if window_lo <= d < meeting_d + (timedelta(days=1) if INCLUDE_MEETING_DAY else timedelta(days=0))
        ]
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
