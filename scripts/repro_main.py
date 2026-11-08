"""项目8 一键复现：正文 6 张图表（图1、图2、表1–表4）的全部数字。

默认模式只读冻结 CSV/JSON（先校验 9 个输入 + 2 张参照图的 SHA256），不重新规划；
输出全部写到 results/repro_main/（已 gitignore），不改任何入库文件。
逐格与稿件快照比对（scripts/p8_manuscript_expected.json，当前为 draft_v3_skeleton.md v3.12，
版本与 sha256 记录在该文件内），比对表写 results/repro_main/compare.md；每次运行另查现行稿件是否仍与快照一致。

用法（wt-P8 根目录）：
    MPLCONFIGDIR=/tmp/mplcfg /workspace/.venv-fig/bin/python scripts/repro_main.py
    ... scripts/repro_main.py --replan      # 只打印全量重规划命令（约 12525.6 s 上界），不执行

退出码：0 全部通过；1 稿件比对有不等；2 冻结输入 SHA256 不符；3 子步骤校验失败
（表2 误差表重建不一致、图2 checks 与 CSV 不符、规划器被调用等）；4 入库文件被改动。
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
sys.dont_write_bytecode = True
from p8_common import OUT_DIR, ROOT, match, ms_numbers, sha256, verify_frozen  # noqa: E402

EXPECTED = HERE / "p8_manuscript_expected.json"
LIVE_MANUSCRIPT = Path("/workspace/paper/draft_v3_skeleton.md")

# Full replan (NOT run by default; never run in 项目8). Upper bound = sum of recorded wall times.
REPLAN_STEPS = [
    ("F2 60 plans (5 workers)", "/home/box/.venvs/mpl/bin/python scripts/f2_noninteger_dw.py",
     1772.9, "results/F2.report.md L11"),
    ("F3 first run: main 80 + geom seeds5-9 60 (5 workers)",
     "/home/box/.venvs/mpl/bin/python scripts/f3_seed_expand.py --workers 5 --f2-csv results/F2_noninteger_dw_71278c2.csv",
     5574.2, "results/F3_run.log last line"),
    ("F3 main postcache 80 (4 workers, maxtasksperchild=1)",
     "/home/box/.venvs/mpl/bin/python scripts/f3_seed_expand.py --workers 4 --main-seeds 0-9 --geom-seeds none "
     "--reuse-geom-csv results/F3_seeds0-9_a9916cb_geom.csv --main-checkpoint results/F3_main_postcache_checkpoint.jsonl "
     "--out-stem F3_main_postcache_46360be", 5178.5, "results/F3_main_postcache_run.log last line"),
]
REPLAN_EXTRA = [
    ("表2 blind 12 plans (4 workers)", "/home/box/.venvs/mpl/bin/python scripts/c1_blind_plans.py", 303.1,
     "results/c1_blind_plans.run.log"),
    ("几何档 cold rerun 16 cells", "/home/box/.venvs/mpl/bin/python scripts/c1_geom_cold_rerun.py", 622.6,
     "results/c1_geom_cold_rerun.run.log"),
]


# ------------------------------------------------------------------ planner guard
GUARD = {"calls": 0, "patched": []}


def install_planner_guard():
    """Replace every loaded planner entry point with a raising counter (proves default mode never plans)."""
    import importlib

    def guard(name):
        def _g(*a, **k):
            GUARD["calls"] += 1
            raise RuntimeError(f"项目8 default mode must not plan: {name} called")
        return _g
    for modname in ("planning", "planning.planner", "planner_api"):
        try:
            importlib.import_module(modname)
        except Exception:
            pass
    for modname, mod in list(sys.modules.items()):
        if mod is None:
            continue
        for attr in ("generate_plan", "make_planner"):
            if hasattr(mod, attr) and callable(getattr(mod, attr)):
                setattr(mod, attr, guard(f"{modname}.{attr}"))
                GUARD["patched"].append(f"{modname}.{attr}")


# ------------------------------------------------------------------ comparison engine
class Cmp:
    def __init__(self):
        self.rows = []

    def _add(self, item, where, ms, comp, ok, kind, source):
        self.rows.append(dict(item=item, where=where, manuscript=ms, computed=comp,
                              result="PASS" if ok else "FAIL", kind=kind, source=source))

    def nums(self, item, where, ms_text, values, source, kind="data"):
        """Every number token in ms_text must equal the matching value at manuscript precision."""
        toks = ms_numbers(re.sub(r"[表图]\d", "", ms_text))
        if len(toks) != len(values):
            self._add(item, where, ms_text, f"token count {len(toks)} vs {len(values)} values", False, kind, source)
            return
        for i, (t, v) in enumerate(zip(toks, values)):
            ok, comp, diff = match(t, float(v))
            self._add(item, f"{where}#{i + 1}" if len(toks) > 1 else where, t,
                      f"{comp} (raw {v!r}, |Δ|={diff:.3g})", ok, kind, source)

    def sub(self, item, where, text, substring, values, source, kind="data"):
        if substring not in text:
            self._add(item, where, substring, "substring not found in manuscript text", False, kind, source)
            return
        self.nums(item, where, substring, values, source, kind)

    def claim(self, item, where, ms, ok, comp, source):
        self._add(item, where, ms, comp, bool(ok), "claim", source)


def mean(s, c):
    return s[c][0]


def sd(s, c):
    return s[c][1]


def ms_cells_for_stat(cell, stat):
    """'0.41±0.27' -> [mean, sd]; '0.00' or '0' -> [mean] (manuscript omits SD)."""
    return list(stat) if "±" in cell else [stat[0]]


def compare_all(E, T, D4, T2rows, F1, F2) -> Cmp:
    C = Cmp()
    G = "F3_main_postcache_46360be_geom.csv"
    M = "F3_main_postcache_46360be_main.csv"
    taus = ["A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1"]
    cols = taus + ["total_time"]
    cap = {k: v["text"] for k, v in E["captions"].items()}

    # ---------------- 表1
    t = E["tables"]["表1"]
    keys = [(11, "S_h"), (11, "B"), (13, "S_h"), (13, "B"), (15, "S_h"), (15, "B")]
    for row, key in zip(t["rows"], keys):
        c = row["cells"]
        s = T["table1"][key]
        C.nums("表1", f"L{row['line']} d", c[0], [key[0]], G, "label")
        for j, col in enumerate(cols):
            C.nums("表1", f"L{row['line']} d={key[0]} {key[1]} {col}", c[2 + j],
                   ms_cells_for_stat(c[2 + j], s[col]), G + (" (p8_table1_d15.py)" if key[0] == 15 else ""))
    C.sub("表1", "title", t["title"], r"\(w=2\,\mathrm{m}\)，\(n=10\)", [2, T["table1"][(11, "S_h")]["n"]], G, "label")
    note = cap["表1_note"]
    W = T["notes"]["wilcoxon"]
    C.claim("表1", "note 10 个配对差同号 (d=11/13, 各 τ)", "10 个配对差同号（S_h 漏喷更少）",
            all(v["all_negative"] and v["n"] == 10 for v in W.values()),
            {f"d{k[0]} {k[1]}": f"n={v['n']} all<0={v['all_negative']}" for k, v in W.items()}, G)
    for k, v in W.items():
        C.sub("表1", f"note p (d={k[0]}, {k[1]})", note, r"\(p=0.0020\)", [v["p"]], G + " exact Wilcoxon")
    C.sub("表1", "note 冷重跑", note, "分层冷重跑 16 格", [T["notes"]["cold_rerun"][0]], "c1_geom_cold_rerun.csv")
    C.claim("表1", "note 冷重跑 16/16 metrics_equal", "16 格指标一致（16/16）",
            "16 格指标一致（16/16）" in note and T["notes"]["cold_rerun"] == (16, 16),
            f"{T['notes']['cold_rerun'][0]}/{T['notes']['cold_rerun'][1]}", "c1_geom_cold_rerun.csv")
    C.sub("表1", "note d=15 S_h 行数", note, r"\(S_h\) 的 10 行数据", [10], G)
    C.claim("表1", "note d=15 首条航道不存在（0/10）", r"首条航道不存在（0/10），前提 A0 不成立",
            "首条航道不存在（0/10），前提 A0 不成立" in note
            and T["notes"]["d15_heuristic_lane_found_true"] == 0,
            f"True count={T['notes']['d15_heuristic_lane_found_true']}; n=10", G)
    C.sub("表1", "note d=15 可配对 n", note, r"可配对 \(n=0\)", [T["notes"]["d15_paired_n"]], G)
    C.sub("表1", "note d=15 L", note, r"\(L=[14,15]\)", T["notes"]["d15_lost_strip"], G + " cut_geometry.lost_strip")

    # ---------------- 表2
    t = E["tables"]["表2"]
    by_wd = {(float(r["w"]), float(r["d"])): r for r in T2rows}
    S2 = "c1_blind_predict_seed10.json + c1_blind_plans_ed94b82.csv (p8_table2_error.py)"
    for row in t["rows"]:
        c = row["cells"]
        w, d = float(c[0]), float(c[1])
        r = by_wd[(w, d)]
        lab = f"L{row['line']} (w={c[0]},d={c[1]})"
        C.nums("表2", f"{lab} w,d,r", " ".join(c[:3]), [r["w"], r["d"], r["r"]], S2, "label")
        C.nums("表2", f"{lab} 预测(a)", c[3], [r["A_pred_a"]], S2)
        C.nums("表2", f"{lab} 预测(b)", c[4], [r["A_pred_b"]], S2)
        C.nums("表2", f"{lab} 实测 S_h", c[6], [r["A_extra_Sh"]], S2)
        if r["B_status"] == "success":
            C.nums("表2", f"{lab} 实测 B", c[5], [r["A_extra_B"]], S2)
            C.nums("表2", f"{lab} 误差(a)", c[7], [r["err_a"]], S2 + " err=实测−预测 (CSV)")
            C.nums("表2", f"{lab} 误差(b)", c[8], [r["err_b"]], S2 + " err=实测−预测 (CSV)")
            C.claim("表2", f"{lab} 判定", c[9], c[9] == "(a) 成立" and r["which"] == "假说 (a) 成立", r["which"], S2)
        else:
            C.claim("表2", f"{lab} 实测 B", c[5], c[5].startswith("—") and r["B_status"] == "failed",
                    f"B_status={r['B_status']}", S2)
            C.claim("表2", f"{lab} 误差(a)/(b)", f"{c[7]} / {c[8]}", c[7] == c[8] == "—" and r["err_a"] == r["err_b"] == "",
                    "empty (no measured B)", S2)
            C.claim("表2", f"{lab} 判定", c[9], c[9] == "不适用" and r["applicable"] == "False",
                    f"applicable={r['applicable']}; which={r['which']}", S2)
    C.sub("表2", "title", t["title"], r"seed 10，0°，\(\tau=0\)", [10, 0, 0], S2, "label")
    src_note = cap["表2_note"]
    ok_sign = all(float(r["err_a"]) == float(r["A_extra_B"]) - float(r["A_pred_a"])
                  and float(r["err_b"]) == float(r["A_extra_B"]) - float(r["A_pred_b"])
                  for r in T2rows if r["B_status"] == "success")
    C.claim("表2", "表注 误差定义 = 实测 − 预测（与 CSV 符号一致）", "误差 = 实测 − 预测",
            "误差 = 实测 − 预测" in src_note and "误差 = 预测 − 实测" not in src_note and ok_sign,
            f"definition in note: {'实测 − 预测' if '误差 = 实测 − 预测' in src_note else 'NOT FOUND'}; "
            f"CSV err == A_extra_B − A_pred for all 5 measured rows: {ok_sign}", S2)
    C.claim("表2", "title w≠2", r"\(w\neq2\)", all(float(r["w"]) != 2 for r in T2rows), sorted({r["w"] for r in T2rows}), S2)

    # ---------------- 表3
    t = E["tables"]["表3"]
    keys = [("11", "0°", "S_h"), ("11", "0°", "B"), ("11", "90°", "B"), ("13", "0°", "S_h"), ("13", "0°", "B"),
            ("13", "90°", "B"), ("10", "0°", "S_h≡B"), ("10", "90°", "B")]
    for row, key in zip(t["rows"], keys):
        c = row["cells"]
        s = T["table3"][key]
        src = M if key[0] == "10" else G
        C.nums("表3", f"L{row['line']} d,U", c[0], [int(key[0]), 2] if key[0] == "10" else [int(key[0])], src, "label")
        C.nums("表3", f"L{row['line']} heading", c[1], [int(key[1][:-1])], src, "label")
        for j, col in enumerate(cols):
            C.nums("表3", f"L{row['line']} d={key[0]} {key[1]} {key[2]} {col}", c[3 + j],
                   ms_cells_for_stat(c[3 + j], s[col]), src)
    ck = T["checks"]
    for name in ("d11_90_B_equiv_oh_rot", "d13_90_B_equiv_oh_rot", "d10_90_B_equiv_oh_rot", "d10_0_S_h_equiv_B"):
        v = ck[name]
        C.claim("表3", f"≡ claim {name} (per-seed |Δ|≤1e-9, A_extra τ0/0.5/1 + time)", "≡", v["equal"],
                f"max|Δ|={v['max_abs_diff']:.3g}; identical plan_hash {v['plan_hash_equal']}/{v['n']}",
                M if name.startswith("d10") else G)
    C.sub("表3", "title", t["title"], r"\(w=2\,\mathrm{m}\)，\(n=10\)", [2, 10], G, "label")
    s15 = T["table3_d15_90"]
    C.sub("表3", "note d=15 90°", cap["表3_note"], "0/2.31/5.59", [mean(s15, c) for c in taus], G)
    tm = T["time"]
    tt = cap["表3_time"]
    C.sub("表3", "时间代价 S_h 0°", tt, r"0° \(S_h\) 的估算飞行时间 1616.14 s", [0, tm["t_sh"]], G)
    C.sub("表3", "时间代价 vs 90°", tt, "比 90° 的 1382.12 s 多 234.02 s（约 +16.9%）",
          [90, tm["t_90"], tm["d_sh_90"], tm["pct_sh_90"]], G)
    C.sub("表3", "时间代价 vs 0° B", tt, "比 0° B-boundary 的 1460.19 s 多 155.94 s（约 +10.7%）",
          [0, tm["t_b0"], tm["d_sh_b0"], tm["pct_sh_b0"]], G)

    # ---------------- 表4 (derived from 表3 d=11 by p8_table4.py)
    t = E["tables"]["表4"]
    V = {k: v for k, (v, _) in D4["values"].items()}
    cond = D4["conditions"]
    S4 = "表3 d=11 rows (p8_table4.py)"
    r1, r2, r3, r4, r5 = [r["cells"] for r in t["rows"]]
    L = [r["line"] for r in t["rows"]]
    i10 = T["table3"][("10", "0°", "S_h≡B")]
    i90 = T["table3"][("10", "90°", "B")]
    # row 1: r=0 integer tiers
    C.claim("表4", f"L{L[0]} 条件 r=0 (d=10/16)", r1[0], cond["r_d10"] == 0 and cond["r_d16"] == 0,
            f"10 mod 2={cond['r_d10']}, 16 mod 2={cond['r_d16']}", M)
    C.nums("表4", f"L{L[0]} 条件 d", re.sub(r"r=0", "", r1[0]), [10, 16], M, "label")
    C.nums("表4", f"L{L[0]} 可选航向", r1[2], [0, 90], M, "label")
    C.nums("表4", f"L{L[0]} 建议 (heading token)", r1[3], [90], M, "label")
    C.claim("表4", f"L{L[0]} 建议: 同相位无差别 + 有滞后时 90° 漏喷更大、估算飞行时间更短", r1[3],
            ck["d10_0_S_h_equiv_B"]["equal"] and all(mean(i90, c) > mean(i10, c) for c in taus[1:])
            and mean(i90, "total_time") < mean(i10, "total_time"),
            f"0° S_h≡B={ck['d10_0_S_h_equiv_B']['equal']}; 90° τ0.5/1 {mean(i90,taus[1]):.2f}/{mean(i90,taus[2]):.2f} > "
            f"0° {mean(i10,taus[1]):.2f}/{mean(i10,taus[2]):.2f}; time {mean(i90,'total_time'):.2f} < {mean(i10,'total_time'):.2f}", M)
    # row 2
    C.claim("表4", f"L{L[1]} 条件 r≠0, C∩L≠∅ (d=11)", r2[0], cond["r_d11"] != 0 and cond["CL_d11_nonempty"],
            f"11 mod 2={cond['r_d11']}; B τ0 mean={V['r3_extra_b0_tau0']:.2f}>0", G)
    C.nums("表4", f"L{L[1]} τ", r2[1], [0], G, "label")
    C.nums("表4", f"L{L[1]} 可选航向", r2[2], [90], G, "label")
    C.nums("表4", f"L{L[1]} 建议 (heading token)", r2[3], [90], G, "label")
    C.claim("表4", f"L{L[1]} 建议: 90° 最快", r2[3], V["r2_time_90"] < V["r3_time_b0"] < V["r3_time_sh"],
            f"{V['r2_time_90']:.2f} < {V['r3_time_b0']:.2f} < {V['r3_time_sh']:.2f}", S4)
    C.nums("表4", f"L{L[1]} 额外漏喷", r2[4], [V["r2_extra_90_tau0"]], S4)
    C.nums("表4", f"L{L[1]} 时间", r2[5], [V["r2_time_90"]], S4)
    # row 3
    C.claim("表4", f"L{L[2]} 条件 r≠0, C∩L≠∅ (d=11)", r3[0], cond["r_d11"] != 0 and cond["CL_d11_nonempty"], "同上", G)
    C.nums("表4", f"L{L[2]} τ", r3[1], [0], G, "label")
    C.nums("表4", f"L{L[2]} 可选航向", r3[2], [0], G, "label")
    C.nums("表4", f"L{L[2]} 建议 +Δt(+%)", r3[3], [V["r3_dt_sh_b0"], V["r3_pct_sh_b0"]], S4)
    C.nums("表4", f"L{L[2]} 额外漏喷 S_h 对 B", r3[4], [V["r3_extra_sh_tau0"], V["r3_extra_b0_tau0"]], S4)
    C.nums("表4", f"L{L[2]} 时间 S_h 对 B", r3[5], [V["r3_time_sh"], V["r3_time_b0"]], S4)
    # row 4
    C.claim("表4", f"L{L[3]} 条件 r≠0, C∩L≠∅ (d=11)", r4[0], cond["r_d11"] != 0 and cond["CL_d11_nonempty"], "同上", G)
    C.nums("表4", f"L{L[3]} τ", r4[1], [0.5, 1.0], G, "label")
    C.nums("表4", f"L{L[3]} 可选航向", r4[2], [0, 90], G, "label")
    C.nums("表4", f"L{L[3]} 建议", r4[3], [0, 90, V["r4_dt_sh_90"], V["r4_pct_sh_90"], 0, V["r4_dt_sh_b0"], V["r4_pct_sh_b0"]],
           S4 + " (0/90 are heading tokens)")
    C.claim("表4", f"L{L[3]} 建议: 0° S_h 漏喷最小", r4[3],
            V["r4_sh_tau05"] < min(V["r4_b0_tau05"], V["r4_b90_tau05"]) and V["r4_sh_tau1"] < min(V["r4_b0_tau1"], V["r4_b90_tau1"]),
            "S_h < 0° B and < 90° at τ=0.5 and 1.0", S4)
    C.nums("表4", f"L{L[3]} 额外漏喷", r4[4], [V["r4_sh_tau05"], V["r4_sh_tau1"], 0, V["r4_b0_tau05"], V["r4_b0_tau1"],
                                             90, V["r4_b90_tau05"], V["r4_b90_tau1"]], S4 + " (0/90 are heading tokens)")
    C.nums("表4", f"L{L[3]} 时间", r4[5], [V["r4_time_sh"], V["r4_time_b0"], V["r4_time_90"]], S4)
    # row 5
    C.claim("表4", f"L{L[4]} 判据推论；d=15 超出适用范围，仅作参照", r5[0] + "；" + r5[3],
            "判据推论" in r5[0] and "超出适用范围，仅作参照" in r5[0]
            and "本文无满足前提 A0 的此类算例" in r5[3]
            and cond["CL_d15_empty"] and T["notes"]["d15_heuristic_lane_found_true"] == 0,
            "d=15: C∩L=∅，但首条航道存在数 0/10，A0 不成立，不作为条件②的验证", G)
    C.nums("表4", f"L{L[4]} 条件 d", r5[0].replace(r"r\neq0", ""), [15], G, "label")
    C.claim("表4", f"L{L[4]} 数值列", " / ".join(r5[1:]), r5[4] == r5[5] == "—" and r5[2] == "—", "no numbers (—)", S4)
    C.sub("表4", "title", t["title"], r"数值取 \(d=11\,\mathrm{m}\) 几何档", [11], S4, "label")
    only_zero = sum(row["cells"][2] == "仅 0°" for row in t["rows"])
    C.claim("表4", "note 「仅 0°」一行（按表体计数）", "表中「仅 0°」一行",
            "表中「仅 0°」一行" in cap["表4_note"] and only_zero == 1,
            f"表体共 {len(t['rows'])} 行；可选航向恰为「仅 0°」的行数={only_zero}", "稿件表4 可选航向列")

    # ---------------- 图1
    m = F1["meta"]
    n1, t1 = cap["图1_note"], "scripts/figA_scene_construction.py → results/repro_main/fig1_scene_construction.json"
    C.sub("图1", "note (a) seed/buffer_expand/U/d", n1, "seed 0，buffer_expand=1，风速档 U=2 m/s → 有效缓冲 d=10 m",
          [m["panel_a"]["seed"], m["buffer_expand"], m["wind_speed"], m["d_m"]], t1)
    C.sub("图1", "note x_F d=10 → d=16", n1, "x_F 由 9 m 变为 15 m", [m["panel_a"]["x_F"], F1["x_F_d16"]],
          t1 + " + a_trial_eval.buffer_set(scene0(0), 16)")
    C.claim("图1", "note x_F=−1+d", "x_F=−1+d", m["panel_a"]["x_F"] == -1 + m["d_m"] and F1["x_F_d16"] == -1 + 16,
            f"{m['panel_a']['x_F']} = -1+{m['d_m']}; {F1['x_F_d16']} = -1+16", t1)
    from planning.wind import effective_speed
    wind_cfg = dict(wind_speed=m["wind_speed"], wind_direction=m["wind_direction"], wind_cost=0.25)
    toward_plus = effective_speed((0, 0, 0), (1, 0, 0), 2.0, wind_cfg)
    toward_minus = effective_speed((0, 0, 0), (-1, 0, 0), 2.0, wind_cfg)
    C.claim("图1", "note 风来自 +x，吹向 −x", "风来自 +x；箭头表示风向吹向 −x",
            "风来自 +x" in n1 and "箭头表示风向吹向 −x" in n1
            and m["wind_direction"] == 0 and toward_plus < 2.0 < toward_minus,
            f"wind_direction=0 是来向 +x；沿 +x 逆风速度={toward_plus}，沿 −x 顺风速度={toward_minus}",
            "planning/wind.py:8–10,38–44；planning/drift.py:217,231–234；scripts/figA_scene_construction.py:458")
    C.claim("图1", "note 主实验配置 ha_orchard", "ha_orchard",
            "ha_orchard" in n1 and m["panel_a"]["scene"].startswith("ha_orchard "), m["panel_a"]["scene"], t1)
    provenance = cap["图1_source_B2"]
    reference_commit = json.loads((ROOT / "results/figA_scene_construction.json").read_text(encoding="utf-8"))["commit"]
    C.claim("图1", "附录 B.2 图1 出处", provenance,
            all(s in provenance for s in ("wt-fig/results/figA_scene_construction.caption.md",
                                          "scripts/figA_scene_construction.py", "2e35a75"))
            and reference_commit.startswith("2e35a75") and (HERE / "figA_scene_construction.py").is_file(),
            f"附录 B.2 保留图注文件、绘图脚本；历史 commit 与参照 JSON {reference_commit} 一致；脚本存在",
            f"稿件 L{E['captions']['图1_source_B2']['line']} 附录 B.2")
    for (style, seed), pm in zip([("jitter_rows", 1), ("clusters_gaps", 2), ("random_obstacles_zones", 0)], m["panels_bcd"]):
        C.claim("图1", f"note panel style {style}", style, pm["style"] == style, pm["style"], t1)
        C.sub("图1", f"note {style} seed", n1, f"{style}，seed {seed}", [pm["seed"]], t1)
    C.claim("图1", "planning_ran=False", "本图仅由场景数据重绘，未运行任何规划", m["planning_ran"] is False,
            f"planning_ran={m['planning_ran']}", t1)
    C.claim("图1", "metadata == reference json (除 commit/输出路径)", "results/figA_scene_construction.json",
            F1["meta_equal_reference_except_commit_and_paths"], str(F1["meta_equal_reference_except_commit_and_paths"]), t1)

    # ---------------- 图2
    rep, cc = F2["report"], F2["csv_checks"]
    s, b = rep["checks"]["S_h"], rep["checks"]["B-boundary(0°)"]
    n2, t2 = cap["图2_note"], "F2_noninteger_dw_71278c2.csv/.geom.json via fig1b_noninteger_buffer_lanes.py"
    cs = cc["S_h"]
    C.sub("图2", "title", cap["图2_title"], "seed 0，U=2 m/s，航向 0°，d=11 m，w=2 m",
          [cs["seed"], cs["U"], cs["heading"], cs["d"], cs["w"]], t2, "label")
    C.sub("图2", "note S_h offset", n2, "o=0.88 m", [s["offset"]], t2)
    C.sub("图2", "note S_h 首条带中心", n2, "首条带中心 x=11 m", [float(cs["first_lane_center"])], t2)
    C.sub("图2", "note B offset", n2, "o=1.88 m", [b["offset"]], t2)
    w_ = cs["w"]
    r_ = rep["cut_geometry"]["r"]
    C.sub("图2", "note 损失带", n2, "[x_F, x_F+(w−r)]=[10, 11] m", rep["cut_geometry"]["lost_strip"][:2], t2)
    C.claim("图2", "note 损失带上界 = x_F+(w−r)", "x_F+(w−r)",
            rep["cut_geometry"]["lost_strip"][1] == rep["cut_geometry"]["x_F"] + (w_ - r_),
            f"{rep['cut_geometry']['x_F']}+({w_}−{r_})", t2)
    C.sub("图2", "note w−r=r=1", n2, "本例 w−r=r=1 m", [r_], t2)
    C.claim("图2", "note w−r = r", "w−r=r", w_ - r_ == r_, f"w−r={w_ - r_}, r={r_}", t2)
    C.sub("图2", "note A_extra(τ=0)", n2, "S_h 0.00 m² vs B-boundary 42.61 m²", [s["A_extra_tau0"], b["A_extra_tau0"]], t2)
    C.sub("图2", "note 估算飞行时间", n2, "估算飞行时间 1606.25 s vs 1459.62 s", [s["total_time"], b["total_time"]], t2)
    for mm in ("S_h", "B-boundary(0°)"):
        ok = all(cc[mm][k] for k in ("plan_hash", "A_extra_tau0", "total_time", "offset"))
        C.claim("图2", f"json checks vs CSV ({mm}): plan_hash/A_extra/total_time/offset", "—", ok,
                {k: cc[mm][k] for k in ("plan_hash", "A_extra_tau0", "total_time", "offset")}, t2)
    C.claim("图2", "regenerated checks == reference json checks", "results/fig1b_noninteger_buffer_lanes.json",
            F2["checks_equal_reference"] and F2["cut_geometry_equal_reference"],
            f"checks={F2['checks_equal_reference']} cut_geometry={F2['cut_geometry_equal_reference']}", t2)
    return C


def write_compare(C: Cmp, out: Path, E: dict, live: dict, F1: dict, F2: dict):
    from collections import Counter
    items = ["图1", "图2", "表1", "表2", "表3", "表4"]
    cnt = {i: Counter((r["kind"], r["result"]) for r in C.rows if r["item"] == i) for i in items}
    L = [f"# 项目8 逐格比对：正文 6 张图表 vs 稿件 {E['version']}", "",
         f"- 快照版本：**{E['version']}**；稿件文件 sha256 `{E['source_sha256']}`（期望值 `scripts/p8_manuscript_expected.json`，抽自 `{E['source']}`）",
         f"- 现行稿件 `{live['path']}`：sha256 `{live['sha256']}`；6 张图表的表体/标题/注与快照{'一致' if live['tables_equal_snapshot'] else '**不一致**（见 live_manuscript_diff）'}",
         f"- 信息项（不影响退出码）：现行 {live.get('version')}，快照 {live.get('snapshot_version')}；行号偏移 "
         + ("、".join(f"{o:+d}" for o in live.get("line_offsets", [])) or "—"),
         "- 判定：稿件写几位小数就按几位比（f-string 四舍五入后字符串相等）；科学计数按有效数字；|Δ| 为稿件值与原始值之差。",
         "- kind：data＝数据数字；label＝参数/标签数字（d、w、seed、航向等，也从数据核对）；claim＝逻辑/等价/文本判定。", "",
         "| 图表 | data PASS/FAIL | label PASS/FAIL | claim PASS/FAIL |", "|---|---|---|---|"]
    for i in items:
        c = cnt[i]
        L.append(f"| {i} | {c[('data','PASS')]}/{c[('data','FAIL')]} | {c[('label','PASS')]}/{c[('label','FAIL')]} | "
                 f"{c[('claim','PASS')]}/{c[('claim','FAIL')]} |")
    tot = Counter(r["result"] for r in C.rows)
    L += ["", f"**合计：PASS {tot['PASS']}，FAIL {tot['FAIL']}**", ""]
    migration = E["migration"]
    L += ["## v3.9 → v3.12 快照迁移", "",
          f"旧稿件 sha256 `{migration['from_sha256']}`。{migration['data_audit']}", "",
          "| 图表 | data 旧→新（Δ） | label 旧→新（Δ） | claim 旧→新（Δ） |",
          "|---|---|---|---|"]
    for item in items:
        counts = []
        for kind in ("data", "label", "claim"):
            old = migration["previous_counts"][item][kind]
            new = sum(cnt[item][(kind, result)] for result in ("PASS", "FAIL"))
            counts.append(f"{old}→{new}（{new-old:+d}）")
        L.append("| " + " | ".join([item] + counts) + " |")
    L += ["", "### 删除、替换、迁移与新增检查项", ""]
    L += ["- " + s for s in migration["check_changes"]]
    L += ["", "### 每项文字变更：旧句 → 新句", "",
          "以下逐字段列出中英文标题、表头、表体、图注、表注及出处的全部变化；行号变化不计为文字变更。", ""]
    for change in migration["text_changes"]:
        L += [f"- **{change['item']}**", f"  - 旧句：{change['old']}", f"  - 新句：{change['new']}"]
    L += ["", "## 图像字节/像素比对（信息项，不计入 PASS/FAIL）", ""]
    for name, F in (("图1", F1), ("图2", F2)):
        p = F["png"]
        L.append(f"- {name}：`{p['new_png']}` sha256 `{p['new_sha256']}`；参照 `{p['ref_png']}` `{p['ref_sha256']}`；"
                 f"字节相同={p['bytes_identical']}；像素差异数={p.get('pixels_differing')}，max|Δ|={p.get('max_abs_diff')}")
    L += ["", "## 逐格明细", "", "| 图表 | 位置 | 稿件 | 复算 | 结果 | kind | 来源 |", "|---|---|---|---|---|---|---|"]
    esc = lambda x: str(x).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    for r in C.rows:
        L.append("| " + " | ".join(esc(r[k]) for k in ("item", "where", "manuscript", "computed", "result", "kind", "source")) + " |")
    (out / "compare.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    with (out / "compare.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(C.rows[0]))
        w.writeheader()
        w.writerows({k: str(v) for k, v in r.items()} for r in C.rows)
    return tot, cnt


def write_numbers(out: Path, T: dict, D4: dict, F1: dict, F2: dict):
    cols = ["A_extra_tau0", "A_extra_tau0.5", "A_extra_tau1", "total_time"]

    def dump(name, table, keyfields):
        with (out / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(keyfields + [f"{c}_{s}" for c in cols for s in ("mean", "sd")] + [f"{c}_fmt" for c in cols])
            for k, s in table.items():
                w.writerow(list(k) + [repr(s[c][i]) for c in cols for i in (0, 1)]
                           + [f"{s[c][0]:.2f}±{s[c][1]:.2f}" for c in cols])
    dump("table1_numbers.csv", T["table1"], ["d", "rule"])
    dump("table3_numbers.csv", {**T["table3"], ("15", "90°", "B (note)"): T["table3_d15_90"]}, ["d", "heading", "rule"])
    (out / "table1_table3_notes.json").write_text(json.dumps(
        {"wilcoxon": {f"d{k[0]}_{k[1]}": v for k, v in T["notes"]["wilcoxon"].items()},
         "cold_rerun": T["notes"]["cold_rerun"], "d15_heuristic_lane_found_true": T["notes"]["d15_heuristic_lane_found_true"],
         "d15_paired_n": T["notes"]["d15_paired_n"], "d15_lost_strip": T["notes"]["d15_lost_strip"],
         "equivalence_checks": T["checks"], "time": T["time"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "fig1_numbers.json").write_text(json.dumps(
        {"d_m": F1["meta"]["d_m"], "x_F_d10": F1["meta"]["panel_a"]["x_F"], "x_F_d16": F1["x_F_d16"],
         "seed_a": F1["meta"]["panel_a"]["seed"], "wind_speed": F1["meta"]["wind_speed"],
         "wind_direction": F1["meta"]["wind_direction"], "buffer_expand": F1["meta"]["buffer_expand"],
         "panels_bcd": [(p["style"], p["seed"]) for p in F1["meta"]["panels_bcd"]], "png": F1["png"]},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "fig2_numbers.json").write_text(json.dumps(
        {"checks": F2["report"]["checks"], "cut_geometry": F2["report"]["cut_geometry"], "csv_checks": F2["csv_checks"],
         "checks_equal_reference": F2["checks_equal_reference"], "png": F2["png"]}, ensure_ascii=False, indent=1),
        encoding="utf-8")


def live_manuscript_status(E: dict, path: Path, out: Path) -> dict:
    st = {"path": str(path), "sha256": "MISSING", "tables_equal_snapshot": False}
    if not path.exists():
        return st
    st["sha256"] = sha256(path)
    r = subprocess.run([sys.executable, str(HERE / "p8_extract_manuscript.py"), str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        st["error"] = r.stderr[-500:]
        return st
    cur = json.loads(r.stdout)
    # 退出码只看 6 张图表的内容（表体、标题、表头、注文字）；版本号与行号只作信息项写进 compare.md。
    strip = lambda e: ({k: [x["cells"] for x in v["rows"]] + [v["title"], v["header"]] for k, v in e["tables"].items()},  # noqa: E731
                       {k: v["text"] for k, v in e["captions"].items()})
    st["tables_equal_snapshot"] = strip(cur) == strip(E)
    st["version"], st["snapshot_version"] = cur.get("version"), E["version"]
    lines = lambda e: ([("t", k, -1, v["title_line"]) for k, v in e["tables"].items()]  # noqa: E731
                       + [("t", k, i, x["line"]) for k, v in e["tables"].items() for i, x in enumerate(v["rows"])]
                       + [("c", k, -1, v["line"]) for k, v in e["captions"].items()])
    a, b = {x[:3]: x[3] for x in lines(cur)}, {x[:3]: x[3] for x in lines(E)}
    st["line_offsets"] = sorted({a[k] - b[k] for k in a.keys() & b.keys()})
    if not st["tables_equal_snapshot"]:
        (out / "live_manuscript_diff.json").write_text(r.stdout, encoding="utf-8")
    return st


def tracked_changes() -> str:
    return subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                          capture_output=True, text=True).stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--manuscript", default=str(LIVE_MANUSCRIPT), help="live manuscript to check against the snapshot")
    ap.add_argument("--replan", action="store_true", help="print the full-replan command list and exit (does NOT run it)")
    a = ap.parse_args(argv)
    if a.replan:
        tot = sum(x[2] for x in REPLAN_STEPS)
        print("Full replan for 表1/表3/表4 (NOT executed by repro_main; run manually in a scratch worktree):")
        for name, cmd, secs, src in REPLAN_STEPS + REPLAN_EXTRA:
            print(f"  - {name}: {cmd}   # recorded {secs} s ({src})")
        print(f"Upper bound 表1/3/4 = {' + '.join(str(x[2]) for x in REPLAN_STEPS)} = {tot:.1f} s ≈ {tot/3600:.1f} h")
        print("WARNING: f3_seed_expand.py rewrites results/F3_tables.md and results/F3.report.md; "
              "c1_blind_plans.py asserts results/c1_blind_plans_{HEAD}.csv does not exist.")
        return 0

    t0 = time.perf_counter()
    out = Path(a.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    before = tracked_changes()

    sha = verify_frozen(include_png=True)
    (out / "sha256_check.json").write_text(json.dumps(sha, indent=1), encoding="utf-8")
    for r in sha:
        print(("OK  " if r["ok"] else "BAD ") + r["file"] + "  " + r["actual"])
    if not all(r["ok"] for r in sha):
        print("FROZEN INPUT SHA256 MISMATCH — abort", file=sys.stderr)
        return 2

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplcfg")
    import p8_main_tables
    import p8_table1_d15
    import p8_table2_error
    import p8_table4
    import p8_figures
    import figA_scene_construction  # noqa: F401  (import before guard so its planning imports get patched)
    import fig1b_noninteger_buffer_lanes  # noqa: F401
    install_planner_guard()
    print("planner guard installed on:", ", ".join(GUARD["patched"]))

    rc_sub = 0
    T = p8_main_tables.compute()
    p8_table1_d15.main(["--out-dir", str(out)])
    D4 = p8_table4.derive(T)
    p8_table4.main(["--out-dir", str(out)])
    if p8_table2_error.main(["--out-dir", str(out)]) != 0:
        print("表2 误差表重建与入库 c1_blind_error_table.csv 不一致", file=sys.stderr)
        rc_sub = 3
    with (out / "table2_error_table.csv").open(encoding="utf-8", newline="") as f:
        T2rows = list(csv.DictReader(f))
    F1 = p8_figures.render_fig1(out)
    F2 = p8_figures.render_fig2(out)
    if not (all(all(v[k] for k in ("plan_hash", "A_extra_tau0", "total_time", "offset")) for v in F2["csv_checks"].values())):
        rc_sub = 3
    write_numbers(out, T, D4, F1, F2)

    E = json.loads(EXPECTED.read_text(encoding="utf-8"))
    live = live_manuscript_status(E, Path(a.manuscript), out)
    C = compare_all(E, T, D4, T2rows, F1, F2)
    tot, cnt = write_compare(C, out, E, live, F1, F2)

    if GUARD["calls"]:
        rc_sub = 3
    after = tracked_changes()
    elapsed = time.perf_counter() - t0
    import matplotlib
    import numpy
    meta = dict(git_head=subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip(),
                python=sys.executable, python_version=platform.python_version(), numpy=numpy.__version__,
                matplotlib=matplotlib.__version__, planner_calls=GUARD["calls"], planner_guard=GUARD["patched"],
                compare={"PASS": tot["PASS"], "FAIL": tot["FAIL"]}, snapshot_version=E["version"],
                snapshot_sha256=E["source_sha256"], live_manuscript=live, elapsed_seconds_in_script=round(elapsed, 2),
                tracked_changes_before=before, tracked_changes_after=after)
    (out / "run_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"compare: PASS {tot['PASS']} FAIL {tot['FAIL']}  -> {out / 'compare.md'}")
    for i, c in cnt.items():
        print(f"  {i}: " + ", ".join(f"{k[0]} {k[1]}={v}" for k, v in sorted(c.items())))
    print(f"planner calls: {GUARD['calls']}; live manuscript 6 items equal snapshot ({E['version']}): {live['tables_equal_snapshot']}")
    print(f"elapsed (in-script): {elapsed:.1f} s")
    if after != before:
        print("TRACKED FILES MODIFIED:\n" + after, file=sys.stderr)
        return 4
    if rc_sub:
        return rc_sub
    return 0 if tot["FAIL"] == 0 and live["tables_equal_snapshot"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
