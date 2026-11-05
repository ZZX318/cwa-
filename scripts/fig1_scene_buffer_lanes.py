"""Figure 1; validate two isolated regenerations unless --no-regen is supplied."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import csv
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys

LW_DATA = 1.7
LW_AXIS = 0.8
ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
import numpy as np
import matplotlib
matplotlib.use('Agg')
from matplotlib import font_manager
from matplotlib.path import Path as MplPath
from matplotlib.patches import Circle, Polygon, PathPatch, Patch
from matplotlib.lines import Line2D
import matplotlib.pyplot as plt

PREFIX = ROOT / 'results/fig1_scene_buffer_lanes'
SOURCES = {
    'S_h': ('a_trial_seeds0-4_2ff2df1', 'a_trial_seed0_2ff2df1',
            'heuristic_U2_h0_o1.88', 'heuristic'),
    'B-boundary(0°)': ('a_trial_extra_b_online_b_boundary_h0_90_0e0715a',
                       'a_trial_extra_b_online_b_boundary_h0_90_0e0715a',
                       'b_boundary_s0_U2_h0_o1.88', 'b_boundary'),
}
COLS = ('seed variant U d heading offset lane_offset_used A_excluded A_extra_tau0 '
        'A_extra_tau0.5 A_extra_tau1 cut_segments path_cut_off violations plan_hash').split()
METRICS = ['A_extra_tau0', 'A_extra_tau0.5', 'A_extra_tau1', 'A_excluded',
           'cut_segments', 'path_cut_off']
BLUE, ORANGE, RED = '#0072B2', '#A65E00', '#B22222'


def configure_fonts():
    path = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    if not path.exists():
        listing = subprocess.check_output(['fc-list', '--format=%{file}\t%{family}\n'], text=True)
        candidates = [line.split('\t', 1)[0] for line in listing.splitlines()
                      if 'Noto Sans CJK SC' in line or 'Noto Serif CJK SC' in line]
        assert candidates, 'No requested Noto CJK font found'
        path = Path(candidates[0])
    font_manager.fontManager.addfont(str(path))
    names = {f.name for f in font_manager.fontManager.ttflist}
    family = next((n for n in ('Noto Sans CJK SC', 'Noto Serif CJK SC') if n in names),
                  font_manager.FontProperties(fname=str(path)).get_name())
    matplotlib.rcParams.update({
        'font.family': family, 'font.size': 7, 'axes.titlesize': 7,
        'axes.labelsize': 7, 'xtick.labelsize': 7, 'ytick.labelsize': 7,
        'legend.fontsize': 7, 'figure.titlesize': 7, 'axes.unicode_minus': False,
        'pdf.fonttype': 42, 'axes.linewidth': LW_AXIS,
        'xtick.major.width': LW_AXIS, 'ytick.major.width': LW_AXIS,
        'xtick.minor.width': LW_AXIS, 'ytick.minor.width': LW_AXIS,
    })


def regenerate(method):
    import a_trial_heading as H
    assert H.TIERS[2.0] == 10.0 and float(H.JOB['swath']) == 2.0
    if method == 'S_h':
        return H.run(dict(seed=0, U=2.0, heading=0, offset=0.0, variant='heuristic'))
    import a_trial_extra_runs as X
    return X.run_job(dict(seed=0, U=2.0, heading=0, variant='b_boundary'))


def assert_geometry(a, b, location='geometry'):
    """Check structure, metadata and every numeric coordinate, absolute tolerance only."""
    if isinstance(a, dict):
        assert a.keys() == b.keys(), location
        for key in a:
            assert_geometry(a[key], b[key], f'{location}.{key}')
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b), location
        for i, (x, y) in enumerate(zip(a, b)):
            assert_geometry(x, y, f'{location}[{i}]')
    elif isinstance(a, (float, int)) and not isinstance(a, bool):
        assert abs(a - b) <= 1e-9, (location, a, b)
    else:
        assert a == b, (location, a, b)


def disc_hits_polygon(center, radius, vertices):
    p, v = np.asarray(center[:2]), np.asarray(vertices)[:, :2]
    if MplPath(np.vstack([v, v[0]])).contains_point(p):
        return True
    a, b = v, np.roll(v, -1, axis=0)
    edge = b - a
    t = np.clip(np.sum((p - a) * edge, axis=1) / np.sum(edge * edge, axis=1), 0, 1)
    return bool(np.any(np.linalg.norm(a + t[:, None] * edge - p, axis=1) <= radius))


def buffer_patch(F, zones):
    # Oppositely wound inner rings leave Z unfilled: the orange area is F minus Z.
    rings, codes = [], []
    for vertices, reverse in [(f['vertices'], False) for f in F] + [(z, True) for z in zones]:
        v = np.asarray(vertices)[:, :2]
        area = np.sum(v[:, 0] * np.roll(v[:, 1], -1) - v[:, 1] * np.roll(v[:, 0], -1))
        if (area > 0) == reverse:
            v = v[::-1]
        rings.extend([*v, v[0]])
        codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(v) - 1) + [MplPath.CLOSEPOLY])
    return PathPatch(MplPath(rings, codes), facecolor='#F6B65C', edgecolor='#D68416',
                     alpha=0.35, linewidth=LW_AXIS, zorder=1)


def metric_text(row):
    extra = '/'.join(f'{row[k]:.2f}' for k in METRICS[:3])
    return f"o_h={row['offset']:.2f} m, A_extra(τ=0/0.5/1.0)={extra} m²"


def draw(scene, geoms, rows, report, cuts, swath):
    configure_fonts()
    fig, axes = plt.subplots(1, 2, figsize=(170 / 25.4, 85 / 25.4))
    fig.subplots_adjust(left=0.075, right=0.985, bottom=0.29, top=0.90, wspace=0.24)
    F = geoms['S_h']['F']
    zones = [z['footprint']['vertices'] for z in scene['no_spray_zones']]
    excluded = [any(disc_hits_polygon(t['geometry']['center'], t['geometry']['radius'], f['vertices'])
                    for f in F) for t in scene['targets']]
    report['n_canopies_intersecting_F_drawn'] = sum(excluded)
    for ax in axes:
        ax.add_patch(buffer_patch(F, zones))
        for z in zones:
            ax.add_patch(Polygon(z, facecolor='white', edgecolor='#802020', hatch='////', linewidth=LW_AXIS))
        ax.add_patch(Polygon(scene['plot']['vertices'], fill=False, edgecolor='black', linewidth=0.5))
        for t, exc in zip(scene['targets'], excluded):
            g = t['geometry']
            ax.add_patch(Circle(g['center'][:2], g['radius'], facecolor='#BBBBBB' if exc else '#D9E9C5',
                                edgecolor='#365B35', linewidth=0.4, zorder=2))
        ax.set_aspect('equal')
        ax.set_xlabel('x/m', labelpad=1)
        ax.set_ylabel('y/m', labelpad=1)
        ax.tick_params(pad=2, length=2.5, width=LW_AXIS)
    for s in geoms['S_h']['segments']:
        if not s['spray']:
            continue
        a, b = np.array(s['start'][:2]), np.array(s['end'][:2])
        # Overview data lines are thinner than 1.7 pt for legibility.
        axes[0].plot(*np.array([a, b]).T, color=BLUE, lw=0.5, zorder=3)
        length = np.linalg.norm(b - a)
        if length:
            normal = np.array([-(b-a)[1], (b-a)[0]]) / length * swath / 2
            axes[1].add_patch(Polygon([a+normal, b+normal, b-normal, a-normal],
                                      facecolor=BLUE, alpha=0.25, edgecolor='none', zorder=3))
        axes[1].plot(*np.array([a, b]).T, color=BLUE, lw=LW_DATA, zorder=4)
    for s in geoms['B-boundary(0°)']['segments']:
        if s['spray']:
            # Coincident B-boundary overlay: dashed orange-brown, linewidth 1.0 pt.
            axes[1].plot(*np.array([s['start'][:2], s['end'][:2]]).T,
                         color=ORANGE, lw=1.0, ls='--', zorder=5)
    for ax in axes:
        for s in report['cut_segment_coordinates']['S_h']:
            ax.plot(*np.array([s['start'][:2], s['end'][:2]]).T, color=RED, lw=LW_DATA, zorder=6)
    cut = geoms['S_h']['segments'][cuts['S_h'][0]]
    midpoint = (np.array(cut['start'][:2]) + np.array(cut['end'][:2])) / 2
    axes[0].plot(*midpoint, 'o', ms=5, mfc='none', mec=RED, mew=0.8, zorder=7)
    axes[0].annotate('被切条带', xy=midpoint, xytext=(22, 12), color=RED,
                     arrowprops=dict(arrowstyle='-', color=RED, lw=LW_AXIS))
    axes[0].text(-5, 52, '禁喷区 Z', rotation=90, ha='center', va='center', color='#802020',
                 bbox=dict(facecolor='white', edgecolor='none', alpha=0.9, pad=0.4))
    axes[0].annotate('缓冲区 F (d=10 m)', xy=(6, 82), xytext=(22, 85),
                     bbox=dict(facecolor='white', edgecolor='none', alpha=0.9, pad=0.5),
                     arrowprops=dict(arrowstyle='-', color='#D68416', lw=LW_AXIS))
    axes[0].annotate('', xy=(89, 94), xytext=(66, 94), arrowprops=dict(arrowstyle='->', lw=LW_AXIS))
    axes[0].text(77.5, 96, '风 U=2 m/s', ha='center',
                 bbox=dict(facecolor='white', edgecolor='none', alpha=0.9, pad=0.4))
    axes[0].set(xlim=(-10, 102), ylim=(-2, 102), title='(a) 场景、禁喷区与缓冲区（seed 0，S$_h$）')
    axes[0].set_xticks([0, 20, 40, 60, 80, 100])
    axes[1].set(xlim=(-9, 16), ylim=(-1, 22), title='(b) 局部放大：S$_h$ 与 B-boundary(0°) 喷洒段')
    for key, y in [('x_F', 0.0), ('x_Z', 0.0)]:
        x = report[key]
        axes[1].axvline(x, color='#555555', ls=':', lw=LW_AXIS, zorder=6)
        axes[1].text(x - 0.4, y, f'{key}={x:g} m', ha='right',
                     bbox=dict(facecolor='white', alpha=0.85, edgecolor='none', pad=0.4), zorder=7)
    row = rows['S_h']
    axes[1].annotate(f"被切条带（cut={row['cut_segments']:g}，{row['path_cut_off']:.2f} m）",
                     xy=midpoint, xytext=(-8, 10.3), color=RED, zorder=8,
                     bbox=dict(facecolor='white', alpha=0.9, edgecolor='none', pad=0.5),
                     arrowprops=dict(arrowstyle='-', color=RED, lw=LW_AXIS))
    # Wrap each CSV-derived method line to retain 7 pt text within the zoom panel.
    lines = []
    for method, row in rows.items():
        lines.append(('S$_h$' if method == 'S_h' else method) + ': ' + metric_text(row).replace(', ', '\n'))
    # CSV-derived numbers placed below the panels (not inside axes) to avoid covering data.
    fig.text(0.5, 0.115, '\n'.join(l.replace('\n', ', ') for l in lines), ha='center', va='bottom',
             linespacing=1.15)
    handles = [Patch(facecolor='white', edgecolor='#802020', hatch='////', label='禁喷区 Z'),
               Patch(facecolor='#F6B65C', alpha=0.35, edgecolor='#D68416', label='缓冲区 F'),
               Patch(facecolor='#D9E9C5', edgecolor='#365B35', label='冠层'),
               Patch(facecolor='#BBBBBB', edgecolor='#365B35', label='与 F 相交冠层'),
               Line2D([], [], color=BLUE, lw=LW_DATA, label='S$_h$ 喷洒段'),
               Line2D([], [], color=ORANGE, lw=1, ls='--', label='B-boundary(0°) 喷洒段'),
               Line2D([], [], color=RED, lw=LW_DATA, label='被切条带')]
    fig.legend(handles=handles, loc='lower center', bbox_to_anchor=(0.5, 0.0),
               ncol=4, frameon=False, columnspacing=1.3, handlelength=2)
    fig.savefig(str(PREFIX) + '.png', dpi=300)
    fig.savefig(str(PREFIX) + '.pdf')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-regen', action='store_true', help='Skip expensive validation; report null match results.')
    args = parser.parse_args()
    import a_trial_heading as H
    import a_trial_eval as ev
    swath = float(H.JOB['swath'])
    assert swath == 2.0, 'Figure requires the original 2 m swath'
    rows, geoms = {}, {}
    for method, (csv_stem, geom_stem, key, variant) in SOURCES.items():
        with (ROOT / 'results' / (csv_stem + '.csv')).open(encoding='utf-8', newline='') as f:
            hits = [r for r in csv.DictReader(f) if int(r['seed']) == 0 and r['variant'] == variant
                    and float(r['U']) == 2.0 and float(r['heading']) == 0]
        assert len(hits) == 1, (method, len(hits))
        rows[method] = {k: (hits[0][k] if k in ('variant', 'plan_hash') else float(hits[0][k])) for k in COLS}
        assert rows[method]['d'] == 10 and rows[method]['violations'] == 0
        geoms[method] = json.loads((ROOT / 'results' / (geom_stem + '.geom.json')).read_text())[key]
    report = dict(csv_rows_used=rows, regenerated_plan_hash={}, hash_match={}, geom_match={},
                  regeneration_enabled=not args.no_regen,
                  sources={m: dict(csv=v[0]+'.csv', geometry=v[1]+'.geom.json', key=v[2]) for m, v in SOURCES.items()})
    if not args.no_regen:
        print('Regenerating both methods in separate spawned subprocesses...', flush=True)
        with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context('spawn')) as pool:
            futures = {m: pool.submit(regenerate, m) for m in SOURCES}
            for method, future in futures.items():
                row, geom = future.result()
                assert row['plan_hash'] == rows[method]['plan_hash'], (method, 'plan_hash', row)
                assert_geometry(geom, geoms[method], method)
                for key in METRICS:
                    assert abs(row[key] - rows[method][key]) <= 1e-9, (method, key)
                report['regenerated_plan_hash'][method] = row['plan_hash']
                report['hash_match'][method] = report['geom_match'][method] = True
                print(f'{method}: hash, geometry and CSV metric assertions passed.', flush=True)
    else:
        for field in ('regenerated_plan_hash', 'hash_match', 'geom_match'):
            report[field] = dict.fromkeys(SOURCES)
    a, b = [geoms[m]['segments'] for m in SOURCES]
    assert len(a) == len(b)
    assert all((x['spray'], x['type']) == (y['spray'], y['type']) for x, y in zip(a, b))
    report['max_segment_coord_diff_Sh_vs_Bboundary'] = max(
        abs(x - y) for s, t in zip(a, b) for k in ('start', 'end') for x, y in zip(s[k], t[k]))
    scene = H.scene0(0)
    report['x_F'] = max(v[0] for f in geoms['S_h']['F'] for v in f['vertices'])
    report['x_Z'] = max(v[0] for z in scene['no_spray_zones'] for v in z['footprint']['vertices'])
    cuts = {m: ev.cut_analysis(g['segments'], swath / 2, g['F'])[0] for m, g in geoms.items()}
    report['cut_segment_coordinates'] = {m: [geoms[m]['segments'][i] for i in ids] for m, ids in cuts.items()}
    report['n_spray_segments'] = {m: sum(bool(s['spray']) for s in g['segments']) for m, g in geoms.items()}
    for m, ids in cuts.items():
        assert len(ids) == rows[m]['cut_segments']
        length = sum(float(np.linalg.norm(np.array(geoms[m]['segments'][i]['end']) -
                                          np.array(geoms[m]['segments'][i]['start']))) for i in ids)
        assert abs(length - rows[m]['path_cut_off']) <= 1e-9
    draw(scene, geoms, rows, report, cuts, swath)
    Path(str(PREFIX) + '.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # Caption numbers come from precisely the same records written to JSON.
    numbers = '；'.join(f"{m}: {metric_text(r)}, A_excluded={r['A_excluded']:.2f} m², "
                       f"cut={r['cut_segments']:g}, path_cut_off={r['path_cut_off']:.2f} m" for m, r in report['csv_rows_used'].items())
    caption = ('图1 试验场景、禁喷区 Z、风致缓冲区 F 与航线对比（seed 0，U=2 m/s，d=10 m，喷幅 w=2 m）。'
               '(a) 全场 S_h 喷洒段；(b) 局部放大，S_h 与 B-boundary(0°) 喷洒段重合（d 为 w 的整数倍时二者相位相同）。'
               '红线为被切条带。B-boundary 为文献方法的简化代理，非原方法复现。 ' + numbers + '。\n\n'
               'Fig. 1 Scene, no-spray zone Z, wind-induced buffer F and lane comparison '
               '(seed 0, U=2 m/s, d=10 m, swath w=2 m). (a) Full-field S_h spray segments; '
               '(b) coincident S_h and B-boundary(0°) spray segments: d is an integer multiple of w, '
               'giving the same lane phase. Red lines show cut segments. B-boundary is a simplified '
               'proxy for a published method, not a reproduction.\n\n'
               '数据来源 / Data sources: ' + '; '.join(v['csv'] + ', ' + v['geometry'] + ' [' + v['key'] + ']'
                                                        for v in report['sources'].values()) +
               '; scene: a_trial_heading.scene0(0); script: scripts/fig1_scene_buffer_lanes.py.\n')
    Path(str(PREFIX) + '.caption.md').write_text(caption, encoding='utf-8')
    for m, r in rows.items():
        print(f"{m}: offset={r['offset']!r}, lane_offset_used={r['lane_offset_used']!r}")
    print('Maximum segment coordinate difference:', repr(report['max_segment_coord_diff_Sh_vs_Bboundary']))
    print('(xmin − x_Z) mod w = (xmin − x_F) mod w because d=10 m is a multiple of w=2 m.')
    print(numbers)
    print('Canopies intersecting F drawn (disc test; planner excluded_targets in CSV may differ):', report['n_canopies_intersecting_F_drawn'])
    print('Wrote', str(PREFIX) + '.{png,pdf,json,caption.md}')


if __name__ == '__main__':
    main()
