"""项目8 shared helpers: frozen-input SHA256 gate, stats, read-only CSV access, cell comparison.

Read-only: nothing here plans or writes outside the caller-chosen output directory.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import math
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT_DIR = RESULTS / "repro_main"

# Spec §2 (/workspace/paper/proj8_repro_spec.md): 9 frozen inputs + 2 reference PNGs.
FROZEN_INPUTS = {
    "results/F3_main_postcache_46360be_geom.csv": "609e7187e06da2e029e06589ed8fe094039214321f5a389ca81e88b691646892",
    "results/F3_main_postcache_46360be_main.csv": "52bf59e2a16789ee55218e8c79e2c7cabab55d41eff6e940b59605d5bcdf9bd7",
    "results/F3_main_postcache_checkpoint.jsonl": "1fcd2c8f6818251199bf372de103bce19b24ca685f89a8347b1911f0abcdae35",
    "results/F2_noninteger_dw_71278c2.csv": "b766203d3e1d125c99dd1cc90230346fafc2032205b99498ced25497569b6896",
    "results/F2_noninteger_dw_71278c2.geom.json": "207afd526a400218961485a6c1cc449f638ac195d8a8f9c2e1c633d3975b5354",
    "results/c1_blind_predict_seed10.json": "e0a8bc2ef1a6b311a0f805f5802fad3461bbabc1e8134820278a4f81f43de979",
    "results/c1_blind_plans_ed94b82.csv": "d2e95326825c99b7bca202b1ecc6e7018d8044ccba587fb00d7f40cf14973032",
    "results/c1_blind_error_table.csv": "3e062171801a82a614a2f2e34fc7c115bc971588b16a73773e78e2dd695e1c18",
    "results/c1_geom_cold_rerun.csv": "e6907dd057ba03aebabecc73226a89554d9b07e05520c7926d5ada13d5a4072a",
}
REFERENCE_PNGS = {
    "results/figA_scene_construction.png": "caa67906badcd59477de7a6b683eb1a6bb2c0b637c62c8fad442b3875ff7e992",
    "results/fig1b_noninteger_buffer_lanes.png": "1f4ff5034cde5a988498b53eed206a5a74c7ce3f24189599b515fce560d206ef",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_frozen(include_png: bool = True) -> list[dict]:
    """Return one record per file; caller must abort if any ok is False."""
    items = dict(FROZEN_INPUTS)
    if include_png:
        items.update(REFERENCE_PNGS)
    out = []
    for rel, want in items.items():
        p = ROOT / rel
        got = sha256(p) if p.exists() else "MISSING"
        out.append(dict(file=rel, expected=want, actual=got, ok=(got == want)))
    return out


def read_csv(rel: str) -> list[dict]:
    with (ROOT / rel).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def select(rows, **kw):
    """Filter rows; numeric fields compared as float, others as str."""
    out = []
    for r in rows:
        ok = True
        for k, v in kw.items():
            if isinstance(v, (int, float)):
                ok = ok and r[k] != "" and float(r[k]) == float(v)
            else:
                ok = ok and r[k] == v
        if ok:
            out.append(r)
    return sorted(out, key=lambda r: int(r["seed"]))


def mean_sd(vals):
    vals = [float(v) for v in vals]
    return statistics.fmean(vals), (statistics.stdev(vals) if len(vals) > 1 else float("nan"))


def exact_wilcoxon_two_sided(diffs, zero_tol: float = 1e-12) -> tuple[int, float]:
    """Exact two-sided Wilcoxon signed-rank p (drop zeros, average ranks, full sign enumeration).

    Same definition as F1/F2/F3 reports (F2.report.md L7). Returns (n_nonzero, p).
    """
    d = [x for x in diffs if abs(x) > zero_tol]
    n = len(d)
    if n == 0:
        return 0, float("nan")
    a = sorted((abs(x), i) for i, x in enumerate(d))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and a[j + 1][0] == a[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[a[k][1]] = (i + j) / 2 + 1
        i = j + 1
    total = sum(ranks)
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    obs = abs(w_plus - total / 2)
    hit = 0
    for signs in itertools.product((0, 1), repeat=n):
        w = sum(r for r, s in zip(ranks, signs) if s)
        if abs(w - total / 2) >= obs - 1e-12:
            hit += 1
    return n, hit / 2 ** n


# ---------------------------------------------------------------- comparison
NUM_RE = re.compile(r"[−-]?\d+(?:\.\d+)?(?:\s*\\times\s*10\^\{?[−-]?\d+\}?)?")


def parse_ms_number(tok: str) -> tuple[float, str]:
    """Manuscript token -> (value, kind). kind 'dp:N' (fixed decimals) or 'sig:N' (scientific)."""
    t = tok.replace("−", "-").replace(" ", "")
    m = re.fullmatch(r"(-?\d+(?:\.\d+)?)\\times10\^\{?(-?\d+)\}?", t)
    if m:
        mant = m.group(1)
        sig = len(mant.replace("-", "").replace(".", "").lstrip("0")) or 1
        return float(mant) * 10 ** int(m.group(2)), f"sig:{sig}"
    dp = len(t.split(".")[1]) if "." in t else 0
    return float(t), f"dp:{dp}"


def ms_numbers(cell: str) -> list[str]:
    return [m.group(0) for m in NUM_RE.finditer(cell)]


def fmt_like(value: float, kind: str) -> str:
    k, n = kind.split(":")
    n = int(n)
    if k == "dp":
        s = f"{value:.{n}f}"
        if float(s) == 0:
            s = s.lstrip("-")
        return s
    return f"{value:.{n - 1}e}"


def match(ms_token: str, value: float) -> tuple[bool, str, float]:
    """Manuscript-rounding equality. Returns (equal, computed_formatted, abs_diff)."""
    ms_val, kind = parse_ms_number(ms_token)
    comp = fmt_like(value, kind)
    if kind.startswith("dp"):
        ms_fmt = fmt_like(ms_val, kind)
        ok = comp == ms_fmt
    else:
        ok = fmt_like(ms_val, kind) == comp
    return ok, comp, abs(ms_val - value)
