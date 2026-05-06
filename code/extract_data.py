"""Extract the data needed for the replication analysis from a local
Postgres instance and emit two CSVs into ../data/.

Outputs:
  data/engine_distributions.csv
    Engine-implied probability per (probe_event, observation_date,
    target_mid_pct, snapshot_kind) where snapshot_kind ∈ {'eod','daily_avg'}.
    Engine here = standard CME FedWatch methodology applied to ZQ
    futures + chaining contracts via the cross_asset_translation
    pipeline (FedWatch decomposition with linear interpolation across
    five 25-bp target-rate buckets centered on pre_target_mid).

  data/paper_distributions.csv
    Replicates Diercks, Katz, Wright (2026) published Kalshi
    distributions for fed_levels (trade-based construction). Identical
    in content to:
      https://kalshi-and-the-rise-of-macro-markets.s3.amazonaws.com/
        daily_distribution_data/daily_distributions_fed_levels.csv

Connection: the script expects DATABASE_URL set to a Postgres instance
hosting the cross_asset_translation tables (probe_backtest_runs,
probe_backtest_predictions, kalshi_paper_distributions). For pure
external replication, you can skip this script and pull the paper data
directly from the URL above; the engine output is published as a CSV
in this repository under data/.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import psycopg2

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://terminal:terminal@127.0.0.1:5432/terminal",
)


def _outcome_to_target_mid(outcome_id: str) -> float | None:
    if not outcome_id.startswith("target_"):
        return None
    try:
        return float(outcome_id.split("_", 1)[1])
    except (ValueError, IndexError):
        return None


def extract_engine() -> Path:
    out_path = DATA_DIR / "engine_distributions.csv"
    sql_eod = """
        WITH last_run AS (
          SELECT run_id FROM probe_backtest_runs
           ORDER BY started_at DESC LIMIT 1
        ),
        day_max_ts AS (
          SELECT p.probe_event_id,
                 date_trunc('day', p.ts AT TIME ZONE 'UTC')::date AS d,
                 max(p.ts) AS ts_max
            FROM probe_backtest_predictions p, last_run lr
           WHERE p.run_id = lr.run_id
           GROUP BY 1, 2
        )
        SELECT p.probe_event_id,
               date_trunc('day', p.ts AT TIME ZONE 'UTC')::date AS observation_date,
               p.outcome_id,
               p.predicted_prob::float8 AS prob_eod
          FROM probe_backtest_predictions p
          JOIN day_max_ts dm
            ON p.probe_event_id = dm.probe_event_id
           AND date_trunc('day', p.ts AT TIME ZONE 'UTC')::date = dm.d
           AND p.ts = dm.ts_max
          JOIN last_run lr ON p.run_id = lr.run_id
         ORDER BY 1, 2, 3
    """
    sql_avg = """
        WITH last_run AS (
          SELECT run_id FROM probe_backtest_runs
           ORDER BY started_at DESC LIMIT 1
        )
        SELECT p.probe_event_id,
               date_trunc('day', p.ts AT TIME ZONE 'UTC')::date AS observation_date,
               p.outcome_id,
               avg(p.predicted_prob)::float8 AS prob_avg
          FROM probe_backtest_predictions p, last_run lr
         WHERE p.run_id = lr.run_id
         GROUP BY 1, 2, 3
         ORDER BY 1, 2, 3
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cur = conn.cursor()
        cur.execute(sql_eod)
        eod_rows = cur.fetchall()
        cur.execute(sql_avg)
        avg_rows = cur.fetchall()
    finally:
        conn.close()

    keyed: dict[tuple, dict[str, float]] = {}
    for ev, d, oid, prob in eod_rows:
        keyed.setdefault((ev, d, oid), {})["prob_eod"] = float(prob)
    for ev, d, oid, prob in avg_rows:
        keyed.setdefault((ev, d, oid), {})["prob_avg"] = float(prob)

    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "probe_event_id", "observation_date", "outcome_id",
            "target_mid_pct", "prob_eod", "prob_daily_avg",
        ])
        for (ev, d, oid), probs in sorted(keyed.items()):
            tm = _outcome_to_target_mid(oid)
            w.writerow([
                ev,
                d.isoformat() if hasattr(d, "isoformat") else str(d),
                oid,
                "" if tm is None else f"{tm:.4f}",
                f"{probs.get('prob_eod', float('nan')):.6f}" if "prob_eod" in probs else "",
                f"{probs.get('prob_avg', float('nan')):.6f}" if "prob_avg" in probs else "",
            ])
    print(f"wrote {out_path} ({sum(1 for _ in keyed)} rows)")
    return out_path


def extract_paper() -> Path:
    out_path = DATA_DIR / "paper_distributions.csv"
    sql = """
        SELECT contract_preamble, observation_date, expiry_date,
               strike, probability, daily_volume, swapped
          FROM kalshi_paper_distributions
         WHERE source = 'trades'
         ORDER BY contract_preamble, observation_date, strike
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
    finally:
        conn.close()
    with out_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "contract_preamble", "observation_date", "expiry_date",
            "strike", "probability_pct", "daily_volume", "swapped",
        ])
        for (preamble, obs, expiry, strike, prob, volume, swapped) in rows:
            w.writerow([
                preamble,
                obs.isoformat() if hasattr(obs, "isoformat") else str(obs),
                expiry.isoformat() if expiry and hasattr(expiry, "isoformat") else (str(expiry) if expiry else ""),
                f"{float(strike):.4f}" if strike is not None else "",
                f"{float(prob):.6f}" if prob is not None else "",
                f"{float(volume):.2f}" if volume is not None else "",
                str(swapped) if swapped is not None else "",
            ])
    print(f"wrote {out_path} ({len(rows)} rows)")
    return out_path


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    extract_engine()
    extract_paper()
    return 0


if __name__ == "__main__":
    sys.exit(main())
