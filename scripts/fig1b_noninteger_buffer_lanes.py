"""Figure 1(b): S_h vs B-boundary(0°) at non-integer d=11 m (F2, seed 0, U=2, heading 0)."""
from __future__ import annotations
import csv, json, sys, hashlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import numpy as np
import fig1_scene_buffer_lanes as A
from matplotlib.patches import Circle, Polygon, Patch, Rectangle
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt

STEM = 'F2_noninteger_dw_71278c2'
KEYS = {'S_h': ('d11_s0_h0_heuristic', 'heuristic'), 'B-boundary(0°)': ('d11_s0_h0_b_boundary', 'b_boundary')}
PREFIX = ROOT / 'results/fig1b_noninteger_buffer_lanes'

def main():
    import a_trial_heading as H, a_trial_eval as ev
    swath = 2.0
    allg = json.loads((ROOT / 'results' / (STEM + '.geom.json')).read_text())
    rows, geoms = {}, {}
    with (ROOT / 'results' / (STEM + '.csv')).open(encoding='utf-8', newline='') as f:
        recs = list(csv.DictReader(f))
    for m, (key, var) in KEYS.items():
        assert key in allg, key
        hits = [r for r in recs if r['seed'] == '0' and r['variant'] == var and float(r['d']) == 11
                and float(r['U']) == 2 and float(r['heading']) == 0]
        assert len(hits) == 1, (m, len(hits))
        rows[m] = hits[0]; geoms[m] = allg[key]
        assert rows[m]['violations'] == '0' and rows[m]['status'] == 'success'
    cg = json.loads(rows['S_h']['cut_geometry'])
    assert cg == json.loads(rows['B-boundary(0°)']['cut_geometry'])
    x0, x1 = cg['lost_strip'][:2]
    report = dict(sources={m: dict(csv=STEM + '.csv', geometry=STEM + '.geom.json', key=k[0]) for m, k in KEYS.items()},
                  lost_strip=cg['lost_strip'], cut_geometry=cg, checks={})
    for m, g in geoms.items():
        r = rows[m]
        xF = max(v[0] for f in g['F'] for v in f['vertices'])
        assert abs(xF - cg['x_F']) < 1e-9, (m, xF)
        ids = ev.cut_analysis(g['segments'], swath / 2, g['F'])[0]
        assert len(ids) == int(r['cut_segments']), (m, len(ids), r['cut_segments'])
        L = sum(float(np.linalg.norm(np.array(g['segments'][i]['end']) - np.array(g['segments'][i]['start']))) for i in ids)
        assert abs(L - float(r['path_cut_off'])) <= 1e-9, (m, L)
        spray = sum(float(np.linalg.norm(np.array(s['end']) - np.array(s['start']))) for s in g['segments'] if s['spray'])
        report['checks'][m] = dict(x_F=xF, cut_segments=len(ids), path_cut_off=L, spray_len_geom=spray,
                                   path_spray_csv=float(r['path_spray']), plan_hash=r['plan_hash'],
                                   n_lanes=int(r['n_lanes']), strip_count=int(r['strip_count']),
                                   total_time=float(r['total_time']), A_extra_tau0=float(r['A_extra_tau0']),
                                   offset=float(r['offset']), cut_ids=ids)
    scene = H.scene0(0)
    A.configure_fonts()
    fig, axes = plt.subplots(1, 2, figsize=(170 / 25.4, 85 / 25.4))
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.29, top=0.90, wspace=0.24)
    zones = [z['footprint']['vertices'] for z in scene['no_spray_zones']]
    for ax, (m, g) in zip(axes, geoms.items()):
        r = rows[m]
        ax.add_patch(A.buffer_patch(g['F'], zones))
        for z in zones:
            ax.add_patch(Polygon(z, facecolor='white', edgecolor='#802020', hatch='////', linewidth=A.LW_AXIS))
        ax.add_patch(Rectangle((x0, -50), x1 - x0, 200, facecolor='#9467BD', alpha=0.18, edgecolor='none', zorder=1.5))
        ax.add_patch(Polygon(scene['plot']['vertices'], fill=False, edgecolor='black', linewidth=0.5))
        for t in scene['targets']:
            gg = t['geometry']
            ax.add_patch(Circle(gg['center'][:2], gg['radius'], facecolor='#D9E9C5', edgecolor='#365B35', linewidth=0.4, zorder=2))
        color = A.BLUE if m == 'S_h' else A.ORANGE
        for s in g['segments']:
            if not s['spray']:
                continue
            a, b = np.array(s['start'][:2]), np.array(s['end'][:2]); n = np.linalg.norm(b - a)
            if n:
                nv = np.array([-(b - a)[1], (b - a)[0]]) / n * swath / 2
                ax.add_patch(Polygon([a + nv, b + nv, b - nv, a - nv], facecolor=color, alpha=0.22, edgecolor='none', zorder=3))
            ax.plot(*np.array([a, b]).T, color=color, lw=A.LW_DATA, zorder=4)
        for i in report['checks'][m]['cut_ids']:
            s = g['segments'][i]
            ax.plot(*np.array([s['start'][:2], s['end'][:2]]).T, color=A.RED, lw=A.LW_DATA, zorder=6)
        for x, lab in [(x0, f'x_F={x0:g}'), (x1, f'x_F+r={x1:g}')]:
            ax.axvline(x, color='#555555', ls=':', lw=A.LW_AXIS, zorder=6)
        ax.text((x0 + x1) / 2, 21.0, f'损失带\n[{x0:g},{x1:g}]', ha='center', va='top', color='#5B3A8A', zorder=8,
                bbox=dict(facecolor='white', alpha=0.85, edgecolor='none', pad=0.4))
        name = 'S$_h$' if m == 'S_h' else m
        ax.set(xlim=(-9, 20), ylim=(-1, 22), title=f"({'b1' if m == 'S_h' else 'b2'}) {name}，d=11 m，o={float(r['offset']):.2f} m")
        ax.set_aspect('equal'); ax.set_xlabel('x/m', labelpad=1); ax.set_ylabel('y/m', labelpad=1)
        ax.tick_params(pad=2, length=2.5, width=A.LW_AXIS)
    c = report['checks']; s, b = c['S_h'], c['B-boundary(0°)']
    txt = (f"S$_h$: A_extra(τ=0)={s['A_extra_tau0']:.2f} m², 航道 {s['n_lanes']}, 用时 {s['total_time']:.2f} s；"
           f"B-boundary(0°): A_extra(τ=0)={b['A_extra_tau0']:.2f} m², 航道 {b['n_lanes']}, 用时 {b['total_time']:.2f} s\n"
           f"d=11 m 为几何假设档（非孔令标风速档）；τ=0 差值为损失带内非 F 冠层面积的几何核算")
    fig.text(0.5, 0.115, txt, ha='center', va='bottom', linespacing=1.3)
    handles = [Patch(facecolor='white', edgecolor='#802020', hatch='////', label='禁喷区 Z'),
               Patch(facecolor='#F6B65C', alpha=0.35, edgecolor='#D68416', label='缓冲区 F'),
               Patch(facecolor='#9467BD', alpha=0.18, label='损失带 [x_F, x_F+r]'),
               Patch(facecolor='#D9E9C5', edgecolor='#365B35', label='冠层'),
               Line2D([], [], color=A.BLUE, lw=A.LW_DATA, label='S$_h$ 喷洒段'),
               Line2D([], [], color=A.ORANGE, lw=A.LW_DATA, label='B-boundary(0°) 喷洒段'),
               Line2D([], [], color=A.RED, lw=A.LW_DATA, label='被切条带')]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 0.0), ncol=4, frameon=False, columnspacing=1.3, handlelength=2)
    fig.savefig(str(PREFIX) + '.png', dpi=300); fig.savefig(str(PREFIX) + '.pdf'); plt.close(fig)
    report['png_sha256'] = hashlib.sha256(Path(str(PREFIX) + '.png').read_bytes()).hexdigest()
    Path(str(PREFIX) + '.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cap = (f"图1(b) 非整数缓冲距离下的对齐对比（seed 0，U=2 m/s，航向 0°，d=11 m，喷幅 w=2 m）。"
           f"(b1) S_h（o={s['offset']:.2f} m，首条带中心 x=11 m，对齐缓冲边界）；(b2) B-boundary(0°)（o={b['offset']:.2f} m，对齐田块边界）。"
           f"紫色为损失带 [x_F, x_F+r]=[{x0:g}, {x1:g}] m，红线为被切条带。"
           f"A_extra(τ=0)：S_h {s['A_extra_tau0']:.2f} m² vs B-boundary {b['A_extra_tau0']:.2f} m²，"
           f"该差值即损失带内非 F 冠层面积（{cg['n_trees']} 棵，{cg['canopy_m2']:.2f} m²），为几何核算，非独立实验证据。"
           f"代价并列：航道 {s['n_lanes']} vs {b['n_lanes']}，总用时 {s['total_time']:.2f} s vs {b['total_time']:.2f} s"
           f"（S_h 多 {s['total_time']-b['total_time']:.2f} s）。d=11 m 为几何假设档，不是孔令标风速档。"
           f"B-boundary 为文献方法的简化代理，非原方法复现。\n\n数据来源：results/{STEM}.csv、results/{STEM}.geom.json "
           f"[{KEYS['S_h'][0]}, {KEYS['B-boundary(0°)'][0]}]；plan_hash S_h {s['plan_hash'][:8]}…，B {b['plan_hash'][:8]}…；"
           f"scene: a_trial_heading.scene0(0)；script: scripts/fig1b_noninteger_buffer_lanes.py。\n")
    Path(str(PREFIX) + '.caption.md').write_text(cap, encoding='utf-8')
    print(json.dumps(report['checks'], ensure_ascii=False)); print(cap)

if __name__ == '__main__':
    main()
