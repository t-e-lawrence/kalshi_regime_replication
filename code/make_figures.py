"""Generate the figures for the paper. Outputs PDF files into
paper/figures/.

Required inputs (produced by analyze.py):
  output/per_meeting.csv
  output/per_day.csv
  output/regime_summary.json

Figures:
  fig1_regime_sign_match.pdf        — three sign-match patterns × four
      regime buckets, with the paper's 70% threshold drawn as a line.
  fig2_case_studies.pdf             — engine and paper Kalshi mode
      probability over the 14-day pre-meeting window for two case
      studies: fed_2024-09-18 (the canonical contested case the paper
      cites) and fed_2025-12-10 (a mixed case where Kalshi committed
      faster than the engine).
  fig3_per_meeting_scatter.pdf      — per-meeting mean mode-gap on the
      y-axis, meeting date on x-axis, colored by regime.

Styling: Latin Modern Serif via matplotlib usetex (matches the LaTeX
paper body). Muted three-color palette (navy, gold, deep red), top
and right spines off, horizontal-only grid at low alpha, in-figure
annotations rather than chart titles (captions in paper.tex carry
the descriptive load).
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, date
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
FIG_DIR = REPO_ROOT / "paper" / "figures"

NAVY  = "#1F3A5F"
GOLD  = "#B8860B"
RED   = "#962C2E"
GRAY  = "#525252"
LIGHTGRAY = "#9C9C9C"

REGIME_COLORS = {
    "quiet":     NAVY,
    "mixed":     GOLD,
    "contested": RED,
}


def _savefig(fig, stem: str) -> None:
    """Save both PDF (for the paper) and PNG (for the README) of a figure."""
    fig.savefig(FIG_DIR / f"{stem}.pdf")
    fig.savefig(FIG_DIR / f"{stem}.png", dpi=200)


def _set_style() -> None:
    plt.rcParams.update({
        "text.usetex":           True,
        "text.latex.preamble":   r"\usepackage{lmodern}\usepackage{amsmath}",
        "font.family":           "serif",
        "font.serif":            ["Latin Modern Roman", "Computer Modern Roman"],
        "font.size":             10,
        "axes.labelsize":        10,
        "axes.titlesize":        10.5,
        "legend.fontsize":       8.5,
        "xtick.labelsize":       9,
        "ytick.labelsize":       9,
        "axes.spines.top":       False,
        "axes.spines.right":     False,
        "xtick.direction":       "in",
        "ytick.direction":       "in",
        "xtick.major.size":      3.5,
        "ytick.major.size":      3.5,
        "xtick.minor.visible":   False,
        "ytick.minor.visible":   False,
        "axes.linewidth":        0.7,
        "axes.edgecolor":        GRAY,
        "axes.labelcolor":       GRAY,
        "xtick.color":           GRAY,
        "ytick.color":           GRAY,
        "axes.grid":             False,
        "legend.frameon":        False,
        "savefig.bbox":          "tight",
        "savefig.pad_inches":    0.04,
    })


def _hgrid(ax) -> None:
    ax.yaxis.grid(True, linestyle=":", color=LIGHTGRAY, alpha=0.55, linewidth=0.6)
    ax.set_axisbelow(True)


def _load_per_meeting() -> list[dict]:
    rows = []
    with (OUTPUT_DIR / "per_meeting.csv").open() as f:
        for row in csv.DictReader(f):
            rows.append({
                **row,
                "n_days": int(row["n_days"]),
                "paper_min_mode_prob": float(row["paper_min_mode_prob"]),
                "modes_aligned_share": float(row["modes_aligned_share"]),
                "mean_mode_gap": float(row["mean_mode_gap"]),
                "mean_spread_gap": float(row["mean_spread_gap"]),
                "mean_tail_gap": float(row["mean_tail_gap"]),
                "last_day_mode_gap": float(row["last_day_mode_gap"]),
                "last_day_e_mode_p": float(row["last_day_e_mode_p"]),
                "last_day_p_mode_p": float(row["last_day_p_mode_p"]),
            })
    return rows


def _load_per_day() -> list[dict]:
    rows = []
    with (OUTPUT_DIR / "per_day.csv").open() as f:
        for row in csv.DictReader(f):
            rows.append({
                **row,
                "observation_date": datetime.strptime(
                    row["observation_date"], "%Y-%m-%d"
                ).date(),
                "e_mode_p": float(row["e_mode_p"]),
                "p_mode_p": float(row["p_mode_p"]),
                "e_mode_tm": float(row["e_mode_tm"]),
                "p_mode_tm": float(row["p_mode_tm"]),
                "modes_align": row["modes_align"] == "True",
                "mode_gap": float(row["mode_gap"]),
                "spread_gap": float(row["spread_gap"]),
                "tail_gap": float(row["tail_gap"]),
            })
    return rows


def _load_summary() -> dict:
    with (OUTPUT_DIR / "regime_summary.json").open() as f:
        return json.load(f)


def figure_1_regime_sign_match() -> None:
    summary = _load_summary()
    regimes = ["quiet", "mixed", "contested", "all"]
    patterns = [
        ("mode_gap_positive_share",   r"$P(\Delta_{\mathrm{mode}} > 0)$",  NAVY),
        ("spread_gap_negative_share", r"$P(\Delta_{\mathrm{spread}} < 0)$", GOLD),
        ("tail_gap_negative_share",   r"$P(\Delta_{\mathrm{tail}} < 0)$",  RED),
    ]
    fig, ax = plt.subplots(figsize=(7.0, 3.6))
    width = 0.24
    x = list(range(len(regimes)))

    for i, (key, label, color) in enumerate(patterns):
        vals = [
            summary[r].get(key, 0) * 100 if summary[r].get("n", 0) else 0
            for r in regimes
        ]
        offsets = [xi + (i - 1) * width for xi in x]
        bars = ax.bar(offsets, vals, width=width * 0.92, label=label,
                       color=color, edgecolor="white", linewidth=0.6)
        for b, v, n in zip(bars, vals,
                            [summary[r].get("n", 0) for r in regimes]):
            if n == 0:
                continue
            weight = "bold" if v >= 70 else "normal"
            ax.text(b.get_x() + b.get_width() / 2, v + 1.8,
                    f"{v:.0f}", ha="center", va="bottom",
                    fontsize=8, color=GRAY, fontweight=weight)

    ax.axhline(70, linestyle=(0, (4, 3)), color=GRAY, linewidth=0.8, zorder=1)
    ax.text(len(regimes) - 0.5, 71.5, r"paper's $70\%$ threshold",
            fontsize=8, color=GRAY, ha="right", va="bottom", style="italic")

    ax.set_xticks(x)
    ax.set_xticklabels([
        r"\textbf{%s}" % r + "\n" + r"$n=%d$" % summary[r].get("n", 0)
        for r in regimes
    ])
    ax.set_ylabel(r"share of meetings matching expected sign (\%)")
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 70, 100])
    ax.legend(loc="upper left", bbox_to_anchor=(0.02, 1.0), ncol=1,
              handlelength=1.2, handletextpad=0.6, borderpad=0.4)
    _hgrid(ax)
    _savefig(fig, "fig1_regime_sign_match")
    plt.close(fig)


def figure_2_case_studies() -> None:
    per_day = _load_per_day()
    cases = [
        ("fed_2024-09-18",
         r"(a) Sept~17, 2024 \textemdash{} contested 50bp surprise",
         date(2024, 9, 18)),
        ("fed_2025-12-10",
         r"(b) Dec~10, 2025 \textemdash{} mixed; Kalshi committed faster",
         date(2025, 12, 10)),
    ]
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 3.2), sharey=True)
    fig.subplots_adjust(wspace=0.12)

    for idx, (ax, (event_id, title, fomc_date)) in enumerate(zip(axes, cases)):
        rows = sorted(
            (r for r in per_day if r["probe_event_id"] == event_id),
            key=lambda r: r["observation_date"],
        )
        if not rows:
            ax.set_title(title + r" \emph{(no data)}", loc="left", fontsize=9.5)
            continue
        dates = [r["observation_date"] for r in rows]
        engine = [r["e_mode_p"] for r in rows]
        kalshi = [r["p_mode_p"] for r in rows]

        ax.plot(dates, engine, color=NAVY, linewidth=1.4,
                marker="o", markersize=3.5, markerfacecolor="white",
                markeredgewidth=1.0, label="engine (FedWatch / ZQ)")
        ax.plot(dates, kalshi, color=RED, linewidth=1.4,
                marker="s", markersize=3.5, markerfacecolor="white",
                markeredgewidth=1.0, label="paper Kalshi")

        ax.set_title(title, loc="left", fontsize=9.5, color=GRAY, pad=4)
        ax.set_ylim(0, 1.05)
        if idx == 0:
            ax.set_ylabel("mode probability")
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=4))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b~%d"))
        for label in ax.get_xticklabels():
            label.set_rotation(0)
        _hgrid(ax)

    axes[0].legend(loc="upper left", handlelength=1.6, handletextpad=0.5,
                   borderaxespad=0.3, fontsize=8)
    _savefig(fig, "fig2_case_studies")
    plt.close(fig)


def figure_3_per_meeting_scatter() -> None:
    rows = _load_per_meeting()
    fig, ax = plt.subplots(figsize=(7.0, 3.6))

    for regime in ("quiet", "mixed", "contested"):
        subset = [r for r in rows if r["regime"] == regime]
        if not subset:
            continue
        xs = [datetime.strptime(r["meeting_date"], "%Y-%m-%d").date() for r in subset]
        ys = [r["mean_mode_gap"] for r in subset]
        ax.scatter(xs, ys, s=55, color=REGIME_COLORS[regime],
                   label=r"\textbf{%s} ($n=%d$)" % (regime, len(subset)),
                   edgecolors="white", linewidths=0.8, zorder=5, alpha=0.92)

    ax.axhline(0, color=GRAY, linewidth=0.7, zorder=1)

    annotate = {
        "fed_2024-09-18": ("Sept 2024 (contested)", (-12, 36)),
        "fed_2025-12-10": ("Dec 2025 (mixed outlier)", (-105, 30)),
    }
    for r in rows:
        if r["probe_event_id"] in annotate:
            label, offset = annotate[r["probe_event_id"]]
            x = datetime.strptime(r["meeting_date"], "%Y-%m-%d").date()
            ax.annotate(
                label,
                xy=(x, r["mean_mode_gap"]),
                xytext=offset,
                textcoords="offset points",
                fontsize=8,
                color=GRAY,
                arrowprops=dict(arrowstyle="-", color=GRAY, lw=0.5,
                                shrinkA=2, shrinkB=4),
            )

    ax.set_ylabel(r"mean window mode-gap (engine $-$ paper Kalshi)")
    ax.legend(loc="lower left", handlelength=0.6, handletextpad=0.5,
              borderaxespad=0.4)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(maxticks=10))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for label in ax.get_xticklabels():
        label.set_rotation(30)
        label.set_ha("right")
    _hgrid(ax)
    _savefig(fig, "fig3_per_meeting_scatter")
    plt.close(fig)


def main() -> int:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    _set_style()
    figure_1_regime_sign_match()
    figure_2_case_studies()
    figure_3_per_meeting_scatter()
    print(f"figures in {FIG_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
