"""Figure 2 from existing results only; run from any working directory."""
from __future__ import annotations

import csv
import json
import re
import statistics as st
import subprocess
import sys
from pathlib import Path

LW_DATA = 1.7
LW_AXIS = 0.8
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "scripts"))
import a_trial_1b_report as R

import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt
import numpy as np

STEMS = (
    "a_trial_seeds0-4_2ff2df1",
    "a_trial_extra_oh_rot_h90_58024ac",
    "a_trial_extra_b_online_b_boundary_h0_90_0e0715a",
)
TIERS = ((2.0, 10), (4.0, 16))
TAUS = (0.0, 0.5, 1.0)
SERIES = ("S1", "S_h", "S3", "B-boundary", "B-online(c=0.25)")
LABELS = ("S1", r"S$_h$", "S3", "B-boundary", r"B-online ($c$=0.25 s)")
STYLES = (("#222222", "o", "-"), ("#0072B2", "s", "--"),
          ("#009E73", "^", "-."), ("#D55E00", "D", ":"),
          ("#8856A7", "v", (0, (5, 1, 1, 1, 1, 1))))
PREFIX = ROOT / "results/fig2_aextra_tau"


def select_rows():
    rows, sources = [], {}
    for stem in STEMS:  # M + O + B order preserves the report's tie breaking.
        batch = json.loads((ROOT / "results" / (stem + ".meta.json")).read_text(
            encoding="utf-8"))["rows_full"]
        rows.extend(batch)
        sources.update({id(row): stem + ".csv" for row in batch})
    ok = [row for row in rows if row.get("status") == "success"]
    selected = {}
    assert R.TAUS == ("A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1")
    for U, d in TIERS:
        for seed in range(5):
            pools = R.pools_scheme(ok, seed, U)
            same = [r for r in ok if r["seed"] == seed and r["U"] == U]
            boundary = [r for r in same if r["variant"] == "b_boundary"]
            online = [r for r in same if r["variant"] == "b_online_c0.25"]
            assert len(boundary) == 2, (U, seed, "boundary", len(boundary))
            assert len(online) == 1, (U, seed, "online", len(online))
            boundary_row = min(boundary, key=lambda r: (r["total_time"], r["path_length"]))
            for tk in R.TAUS:
                choices = [R.pick_min(pools[s], tk) for s in SERIES[:3]]
                choices += [boundary_row, online[0]]
                for series, row in zip(SERIES, choices):
                    assert (row is None) == (series == "S_h" and U == 4 and seed == 4), (
                        U, seed, tk, series, "unexpected missing row")
                    if row is not None:
                        assert row["violations"] == 0, (U, seed, tk, series, row)
                        assert row["d"] == d, (U, d, row["d"])
                    selected[U, tk, series, seed] = row
    return selected, sources


def section(text, heading, level):
    matches = list(re.finditer(r"^" + re.escape(heading) + r"\n", text, re.M))
    assert len(matches) == 1, (heading, "heading count", len(matches))
    tail = text[matches[0].end():]
    return re.split(r"^#{1," + str(level) + r"} ", tail, maxsplit=1, flags=re.M)[0]


def check_report(selected):
    report = (ROOT / "results/a_trial_1b_0e0715a.report.md").read_text(encoding="utf-8")
    count = 0
    for baseline, name in ((SERIES[4], "B-online c=0.25"),
                           (SERIES[3], "B-boundary (min total_time)")):
        block = section(report, f"## 配对：S_h−{name} 与 S3−{name}", 2)
        for U, _ in TIERS:
            for tk in R.TAUS:
                sub = section(block, f"### U={U:g} · {R.TLAB[tk]}", 3)
                for series in ("S_h", "S3"):
                    pattern = (r"^- " + re.escape(series) + r"−B：n=(\d+)，mean \[min,max\] = "
                               r"(-?\d+\.\d{4}) \[(-?\d+\.\d{4}), (-?\d+\.\d{4})\]；")
                    matches = re.findall(pattern, sub, re.M)
                    assert len(matches) == 1, (name, U, tk, series, matches)
                    diffs = [selected[U, tk, series, s][tk] - selected[U, tk, baseline, s][tk]
                             for s in range(5) if selected[U, tk, series, s] is not None]
                    actual = (str(len(diffs)), f"{st.mean(diffs):.4f}",
                              f"{min(diffs):.4f}", f"{max(diffs):.4f}")
                    assert actual == matches[0], (name, U, tk, series, actual, matches[0])
                    count += 1
    assert count == 24, count


_CSV_CACHE = {}


def _check_against_csv(row, tk, csv_name):
    """Traceability: the meta rows_full value must equal the committed CSV row (same plan_hash)."""
    if csv_name not in _CSV_CACHE:
        with (ROOT / "results" / csv_name).open(encoding="utf-8") as fh:
            _CSV_CACHE[csv_name] = list(csv.DictReader(fh))
    hits = [r for r in _CSV_CACHE[csv_name] if r["plan_hash"] == row["plan_hash"]
            and int(r["seed"]) == row["seed"] and r["variant"] == row["variant"]]
    assert len(hits) == 1, (csv_name, row["plan_hash"], len(hits))
    assert float(hits[0][tk]) == row[tk], (csv_name, row["plan_hash"], tk, hits[0][tk], row[tk])


def tables(selected, sources):
    long, summary = [], []
    for U, d in TIERS:
        for tau, tk in zip(TAUS, R.TAUS):
            for series in SERIES:
                values = []
                for seed in range(5):
                    row = selected[U, tk, series, seed]
                    if row is None:
                        continue
                    values.append(row[tk])
                    _check_against_csv(row, tk, sources[id(row)])
                    long.append(dict(U=U, d=d, tau_s=tau, series=series, seed=seed,
                                     A_extra_m2=row[tk], variant=row["variant"],
                                     heading=row["heading"], offset=row["offset"],
                                     plan_hash=row["plan_hash"], source_csv=sources[id(row)]))
                assert len(values) == (4 if U == 4 and series == "S_h" else 5), (U, tk, series)
                summary.append(dict(U=U, tau_s=tau, series=series, n=len(values),
                                    mean=st.mean(values), sd=st.stdev(values),
                                    min=min(values), max=max(values)))
    return long, summary


def configure_fonts():
    path = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    if not path.exists():
        listing = subprocess.check_output(["fc-list", "--format=%{file}\t%{family}\n"], text=True)
        candidates = [line.split("\t", 1)[0] for line in listing.splitlines()
                      if "Noto Sans CJK SC" in line or "Noto Serif CJK SC" in line]
        assert candidates, "No requested Noto CJK font found"
        path = Path(candidates[0])
    font_manager.fontManager.addfont(str(path))
    names = {f.name for f in font_manager.fontManager.ttflist}
    # Prefer the Simplified-Chinese face of the TTC (face 0 is JP).
    family = next((n for n in ("Noto Sans CJK SC", "Noto Serif CJK SC") if n in names),
                  font_manager.FontProperties(fname=str(path)).get_name())
    matplotlib.rcParams.update({
        "font.family": family, "font.size": 7, "axes.titlesize": 7,
        "axes.labelsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
        "legend.fontsize": 7, "figure.titlesize": 7, "axes.unicode_minus": False,
        "pdf.fonttype": 42, "axes.linewidth": LW_AXIS,
        "xtick.major.width": LW_AXIS, "ytick.major.width": LW_AXIS,
        "xtick.minor.width": LW_AXIS, "ytick.minor.width": LW_AXIS,
    })


def plot(long, summary):
    configure_fonts()
    fig, axes = plt.subplots(1, 2, figsize=(170 / 25.4, 70 / 25.4), sharey=False)
    x = np.array(TAUS)
    offsets = np.linspace(-0.08, 0.08, len(SERIES))
    for ax, (U, d), letter in zip(axes, TIERS, "ab"):
        for series, label, (color, marker, style), offset in zip(SERIES, LABELS, STYLES, offsets):
            means = np.array([r["mean"] for r in summary if r["U"] == U and r["series"] == series])
            ax.fill_between(x, means - 1, means + 1, color="grey", alpha=0.15,
                            linewidth=0, zorder=1)
            ax.plot(x, means, color=color, marker=marker, linestyle=style,
                    linewidth=LW_DATA, markersize=3.5, label=label, zorder=3)
            points = [r for r in long if r["U"] == U and r["series"] == series]
            ax.scatter([r["tau_s"] + offset for r in points],
                       [r["A_extra_m2"] for r in points], marker=marker, s=9,
                       facecolors="none", edgecolors=color, linewidths=0.6, zorder=2)
        ax.set_xticks(TAUS, ["0", "0.5", "1.0"])
        ax.set_xlim(-0.13, 1.13)
        ax.set_xlabel("阀门延迟 τ/s")
        ax.set_ylabel(r"额外喷洒面积 $A_{\mathrm{extra}}$/m$^2$")
        ax.set_title(f"({letter}) U={U:g} m/s, d={d} m")
        if U == 4:
            ax.text(0.04, 0.94, r"S$_h$: n=4", transform=ax.transAxes, va="top", fontsize=7)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, 0.015),
               ncol=5, frameon=False, columnspacing=1.4, handlelength=2.5)
    fig.tight_layout(rect=(0, 0.13, 1, 1), pad=0.7, w_pad=1.4)
    # Do not use bbox_inches='tight': preserve the exact 170 mm figure width.
    fig.savefig(str(PREFIX) + ".png", dpi=300)
    fig.savefig(str(PREFIX) + ".pdf")
    plt.close(fig)


def main():
    selected, sources = select_rows()
    check_report(selected)
    long, summary = tables(selected, sources)
    for suffix, records in ((".csv", long), (".summary.csv", summary)):
        with Path(str(PREFIX) + suffix).open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    plot(long, summary)
    caption = (
        "图2 两风速档下额外喷洒面积 A_extra 随阀门延迟 τ 的变化；线为 5 个随机场景均值（U=4 时 S_h 为 n=4），"
        "空心点为逐场景值，灰带为均值 ±1 m²（0.05 m 栅格相位误差，差值小于 1 m² 不解读）。"
        "τ=1.0 s 为假设值（Wang 2023 等效约 0.6–1.0 s）。B-online、B-boundary 为文献方法的简化代理，非原方法复现。\n\n"
        "Fig. 2 Extra sprayed area A_extra versus valve delay τ at two wind speeds. Lines show means over five random "
        "scenarios (S_h: n=4 at U=4); hollow points show individual scenarios. Grey bands indicate mean ±1 m² "
        "(phase error of the 0.05 m raster); differences below 1 m² are not interpreted. The delay τ=1.0 s is assumed "
        "(Wang 2023: equivalent approximately 0.6–1.0 s). B-online and B-boundary are simplified proxies for published "
        "methods, not reproductions of the original methods.\n\n"
        "数据来源 / Data sources: existing rows_full results at commits 2ff2df1/58024ac/0e0715a; "
        "script: scripts/fig2_aextra_tau.py.\n"
    )
    Path(str(PREFIX) + ".caption.md").write_text(caption, encoding="utf-8")
    print("All 24 paired report checks, sample counts, and zero-violation assertions passed.")
    print(f"{'U':>2} {'tau':>4} {'series':<19} {'n':>2} {'mean':>9} {'sd':>9} {'min':>9} {'max':>9}")
    for r in summary:
        print(f"{r['U']:2g} {r['tau_s']:4.1f} {r['series']:<19} {r['n']:2d} "
              f"{r['mean']:9.4f} {r['sd']:9.4f} {r['min']:9.4f} {r['max']:9.4f}")
    print(f"Wrote {len(long)} observations, {len(summary)} summary rows, PNG, PDF, and caption.")


if __name__ == "__main__":
    main()
