# Kalshi Regime Replication

A short replication note on **Diercks, Katz, and Wright (2026), "Kalshi and the Rise of Macro Markets"** (FEDS 2026-010).

The note has two parts.

**Part 1 — Replication of Diercks Table 3 Panel B.** We faithfully reproduce DKW's Kalshi-side forecast accuracy numbers on a 27-meeting sample comparable to theirs (Sept 2022 – Dec 2025), using their own published moments file. Kalshi median and mode MAE replicate to **0.0000 exactly**; Kalshi mean MAE replicates within their two-decimal table-display rounding (0.0128 vs. their reported 0.010). The FF Futures side cannot be exactly replicated from public materials — DKW's repo README explicitly states their FFR forecast uses FRB-licensed CME data not included.

**Part 2 — Regime-conditional extension.** The documented qualitative patterns from DKW Section 5 (mode over-concentration, narrower spread, tail under-allocation) are operationalized as three sign-match metrics and conditioned on a regime classification by minimum pre-meeting Kalshi mode probability. On the same 27-meeting sample:

- **Quiet meetings** (n=18): 39% / 56% / 39% sign-match — coin flips on every measure.
- **Mixed meetings** (n=7): 71% / 71% / 71% (5/7 each) — just clears the implicit 70% threshold.
- **Contested meetings** (n=2): 50% / 50% / 50% (1/2 each). March 2023 (post-SVB) matches the predicted directions; September 2024 50bp surprise goes the other way once the engine catches up by FOMC close.

A robustness check on the full 37-meeting sample (which adds 9 pre-Sept-2022 meetings + 3 early-2026 meetings) strengthens the mixed-bucket sign-match to 80% (8/10) and contested to 67% (2/3) without changing the qualitative finding.

## Repository contents

```
paper/
  paper.tex                      # the replication note (LaTeX source)
  refs.bib                       # bibliography
  figures/                       # generated PDFs
code/
  extract_data.py                # pulls engine + paper distributions
                                 # from Postgres → CSV (one-time)
  analyze.py                     # regime classification + sign-match
                                 # metrics; reads CSVs in data/, writes
                                 # tables in output/
  make_figures.py                # generates the three paper figures
data/
  engine_distributions.csv       # engine-implied probabilities per
                                 # (meeting, observation_date, outcome)
  paper_distributions.csv        # mirror of paper's S3 publication
output/
  per_meeting.csv                # one row per FOMC with regime + summary
  per_day.csv                    # per (meeting, day) gap measurements
  regime_summary.json            # the headline numbers for the paper
```

## Reproducing the analysis

The two CSVs in `data/` are committed so the full analysis runs without external dependencies:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install matplotlib

python3 code/analyze.py        # writes output/{per_meeting.csv, per_day.csv, regime_summary.json}
python3 code/make_figures.py   # writes paper/figures/*.pdf

cd paper && pdflatex paper.tex && bibtex paper && pdflatex paper.tex && pdflatex paper.tex
```

To regenerate the input CSVs from a fresh source rather than the committed ones:

- `data/paper_distributions.csv` is a verbatim copy of [`daily_distributions_fed_levels.csv`](https://kalshi-and-the-rise-of-macro-markets.s3.amazonaws.com/daily_distribution_data/daily_distributions_fed_levels.csv) from the original authors' S3 bucket. Re-download with `curl -O <url>`. The columns differ slightly (we add a normalized header); see `code/extract_data.py` for the exact transformation.

- `data/engine_distributions.csv` is computed by the FedWatch-style decomposition of CME ZQ futures (linear interpolation across five 25-bp target-rate buckets, with chaining to the next non-FOMC contract month when fewer than five days remain in the contract month). The engine implementation lives in our companion repository (TODO link). With Databento access and that repository, run `code/extract_data.py` against a Postgres instance hosting our backtest predictions.

## Citation

If you find this replication useful:

```
@misc{grund2026kalshi,
  author = {Oliver Grund},
  title  = {Regime-Conditional Bias in Fed Funds Futures vs Kalshi
            Distributions: A Replication Note on Diercks, Katz, and
            Wright (2026)},
  year   = {2026},
  url    = {https://github.com/t-e-lawrence/kalshi_regime_replication},
}
```

The paper being replicated:

```
@techreport{dkw2026,
  author      = {Diercks, Anthony M. and Katz, Jared Dean and Wright, Jonathan H.},
  title       = {Kalshi and the Rise of Macro Markets},
  institution = {Board of Governors of the Federal Reserve System},
  type        = {Finance and Economics Discussion Series},
  number      = {2026-010},
  year        = {2026},
  doi         = {10.17016/FEDS.2026.010},
}
```

with replication code and data published by the original authors at [github.com/jdkatz21/Prediction_Markets_Public](https://github.com/jdkatz21/Prediction_Markets_Public).

## Limitations and honest caveats

- Our primary sample is 27 meetings (Sept 2022 – Dec 2025), chosen to match DKW's reported sample size for like-for-like replication. We additionally have engine output for 10 meetings outside this window (9 pre-Sept-2022 + 3 early 2026), used as a robustness check in Section 7.3 of the paper.
- We do not address SOFR options-derived distributions, which the original paper discusses separately in their Section 5 (Figure 11 and surrounding text on p. 18-19). SOFR options carry an additional ~6 bp SOFR–EFFR spread bias and an institutional hedging-demand bias not present in fed funds futures; whether those translate into more systematic per-meeting bias than the binomial-tree-driven patterns we evaluate here is a question this note does not test.
- The structural-disagreement patterns we test are those framed in the original paper's Section 5. We do not evaluate calibration of the implied densities against realized rates, which is a separate question. The original paper covers it in Section 6.1, "Probability Integral Transform" (their Figure 15).
- Our engine implements the standard FedWatch decomposition with five 25-bp buckets via linear interpolation, richer than the strict two-bucket binomial-tree decomposition the paper critiques but still narrower than Kalshi's 7-bucket support. The spread-gap pattern emerges mechanically from this support gap regardless of bucket count, not from the binomial-tree bias per se. The 71% sign-match in mixed meetings (n=7) is just above the 70% threshold; with such small n, the binomial 95% confidence interval is roughly 29%–96% — directionally consistent with DKW's claim but not statistically robust on its own.
