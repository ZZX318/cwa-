"""Rebuild frozen Table 2 without planning; write only the requested artifacts.

The frozen rows establish the labels below, but cannot determine the original
ad-hoc script's tolerance or unobserved classification branches. We use 1e-9
for the observed hypothesis-(a) matches and reject unsupported cases.
"""

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREDICT = ROOT / "results/c1_blind_predict_seed10.json"
PLANS = ROOT / "results/c1_blind_plans_ed94b82.csv"
REFERENCE = ROOT / "results/c1_blind_error_table.csv"
COLUMNS = (
    "w d r L_a A_nom_a A_pred_a L_b A_nom_b A_pred_b A_extra_B A_extra_Sh "
    "err_a err_b which heuristic_lane_found applicable B_status H_status "
    "B_time H_time B_violations H_violations note sh_note source"
).split()
FLOATS = set("w d r A_nom_a A_pred_a A_nom_b A_pred_b A_extra_B A_extra_Sh "
             "err_a err_b B_time H_time".split())


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        return reader.fieldnames, rows


def build_rows(predict_json_path, plans_csv_path) -> list[dict]:
    """Join by numeric (w, d, variant), preserving JSON order and CSV columns."""
    combos = json.loads(Path(predict_json_path).read_text(encoding="utf-8"))["combos"]
    plans = {}
    for row in read_csv(plans_csv_path)[1]:
        key = (float(row["w"]), float(row["d"]), row["variant"])
        if key in plans:
            raise ValueError(f"Duplicate frozen plan: {key}")
        plans[key] = row
    rows = []
    for combo in combos:
        key = (combo["w"], combo["d"])
        b, h = (plans[(*key, variant)] for variant in ("b_boundary", "heuristic"))
        row = dict.fromkeys(COLUMNS, "")
        for column in ("w", "d", "r", "source"):
            row[column] = combo[column]
        for suffix, name in (("a", "a_w_minus_r"), ("b", "b_r")):
            hyp = combo["hyp"][name]
            if hyp["A_union"] != hyp["predict_B"]:
                raise ValueError("Frozen A_union and predict_B disagree")
            row[f"L_{suffix}"] = str(hyp["L"])
            row[f"A_nom_{suffix}"] = hyp["A_nom"]
            row[f"A_pred_{suffix}"] = hyp["A_union"]
        for prefix, plan in (("B", b), ("H", h)):
            row[f"{prefix}_status"] = plan["status"]
            row[f"{prefix}_time"] = float(plan["total_time"]) if plan["total_time"] else ""
            row[f"{prefix}_violations"] = plan["violations"]
        row["heuristic_lane_found"] = h["heuristic_lane_found"]
        row["applicable"] = b["status"] == h["status"] == "success" and h["heuristic_lane_found"] == "True"
        row["A_extra_Sh"] = float(h["A_extra_tau0"]) if h["A_extra_tau0"] else ""
        if row["A_extra_Sh"] != 0.0:
            raise ValueError("Unobserved heuristic measurement in frozen inputs")
        row["sh_note"] = "S_h A_extra=0"
        if b["status"] == "success":
            row["A_extra_B"] = float(b["A_extra_tau0"])
            for suffix in ("a", "b"):
                row[f"err_{suffix}"] = row["A_extra_B"] - row[f"A_pred_{suffix}"]
            if abs(row["err_a"]) > 1e-9 or abs(row["err_b"]) <= 1e-9:
                raise ValueError("Unobserved hypothesis classification in frozen inputs")
            row["which"] = "假说 (a) 成立"
        else:
            row["which"] = "无法判定（无实测 B）"
            row["note"] = f"B status={b['status']}: {b['reason']}"
        rows.append(row)
    return rows


def cell(value):
    return str(value).replace("|", "&#124;").replace("\n", "<br>")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/repro_main")
    args = parser.parse_args(argv)
    out_dir = args.out_dir.resolve()
    rebuilt = out_dir / "table2_error_table.csv"
    report = out_dir / "table2_error_diff.md"
    for target in (rebuilt, report):
        if target.is_symlink() or target.resolve().parent != out_dir:
            parser.error(f"Unsafe output path: {target}")
        for source in (PREDICT, PLANS, REFERENCE):
            if target.resolve() == source.resolve() or (target.exists() and target.samefile(source)):
                parser.error(f"Output would overwrite an input: {target}")
    rows = build_rows(PREDICT, PLANS)
    out_dir.mkdir(parents=True, exist_ok=True)
    with rebuilt.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    expected_header, expected = read_csv(REFERENCE)
    actual_header, actual = read_csv(rebuilt)
    header_equal = expected_header == actual_header
    count_equal = len(expected) == len(actual)
    columns = list(dict.fromkeys(expected_header + actual_header))
    details = ["| Row | Column | Committed | Rebuilt | Field equal | Float exact | abs(diff) <= 1e-9 |",
               "| --- | --- | --- | --- | --- | --- | --- |"]
    equal_count = total = 0
    for index in range(max(len(expected), len(actual))):
        old = expected[index] if index < len(expected) else {}
        new = actual[index] if index < len(actual) else {}
        for column in columns:
            left, right = old.get(column), new.get(column)
            equal = column in old and column in new and left == right
            exact = close = "N/A"
            if column in FLOATS:
                if left == right == "":
                    exact = close = "N/A (both empty)"
                else:
                    try:
                        a, b = float(left), float(right)
                        exact, close = a == b, abs(a - b) <= 1e-9
                    except (TypeError, ValueError):
                        exact = close = False
            equal_count += equal
            total += 1
            values = (index + 1, column, left, right, equal, exact, close)
            details.append("| " + " | ".join(map(cell, values)) + " |")
    original_bytes, rebuilt_bytes = REFERENCE.read_bytes(), rebuilt.read_bytes()
    identical = original_bytes == rebuilt_bytes
    success = header_equal and count_equal and equal_count == total
    summary = [f"Fields equal: {equal_count}/{total}",
               f"Header equal: {header_equal}; row counts equal: {count_equal}",
               f"Byte-identical: {identical}",
               f"Committed SHA256: {hashlib.sha256(original_bytes).hexdigest()}",
               f"Rebuilt SHA256: {hashlib.sha256(rebuilt_bytes).hexdigest()}"]
    report.write_text("# Table 2 comparison\n\n" + "\n\n".join(summary)
                      + "\n\nField equality is exact CSV text equality; tolerance does not affect exit status.\n\n"
                      + "\n".join(details) + "\n", encoding="utf-8")
    print("\n".join(summary))
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
