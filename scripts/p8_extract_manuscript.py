"""Read-only extraction of the six main figures/tables, including bilingual titles.

Usage: python scripts/p8_extract_manuscript.py MANUSCRIPT.md [SOURCE_LABEL]
Notes are located within their figure/table, not by wording that changes on revision.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path


def extract(src, label=None):
    raw = Path(src).read_bytes()
    txt = raw.decode('utf-8')
    lines = txt.splitlines()

    def record(i):
        return {'line': i + 1, 'text': lines[i].strip()}

    def find(prefix, start=0, end=None):
        return next(i for i in range(start, len(lines) if end is None else end)
                    if lines[i].startswith(prefix))

    version = re.search(r'v3\.\d+(?= 可迭代骨架)', txt)
    out = dict(source=label or str(src), source_sha256=hashlib.sha256(raw).hexdigest(),
               version=version.group(0) if version else 'unknown', tables={}, captions={})
    for name in ('图1', '图2', '表1', '表2', '表3', '表4'):
        start = find(name + '　')
        end = next((i for i in range(start + 1, len(lines))
                    if lines[i].startswith('### ') or re.match(r'[图表][1-4]　', lines[i])), len(lines))
        english = ('Fig.' if name[0] == '图' else 'Table ') + name[1] + '　'
        out['captions'][name + '_english'] = record(find(english, start, end))
        if name[0] == '表':
            j = find('|', start, end)
            cells = lambda line: [c.strip() for c in line.strip().strip('|').split('|')]
            rows = []
            k = j + 2
            while k < end and lines[k].startswith('|'):
                rows.append(dict(line=k + 1, cells=cells(lines[k])))
                k += 1
            out['tables'][name] = dict(title_line=start + 1, title=lines[start].strip(),
                                       header=cells(lines[j]), rows=rows)
            note_start = k
        else:
            out['captions'][name + '_title'] = record(start)
            note_start = start
        note = next(i for i in range(note_start, end) if lines[i].startswith(('注：', '出处：')))
        out['captions'][name + '_note'] = record(note)
        if name == '表3':
            out['captions']['表3_time'] = record(find('**时间代价（与结论同处）**', note, end))
        if name[0] == '图':
            source = next((i for i in range(note + 1, end)
                           if lines[i].startswith(('（图注照 ', '（图注据 '))), None)
            if source is not None:
                out['captions'][name + '_source'] = record(source)

    # Only this appendix section may supply the relocated provenance checks.
    b2 = next((i for i, line in enumerate(lines) if line.startswith('**B.2 ')), None)
    if b2 is not None:
        end = next(i for i in range(b2 + 1, len(lines)) if lines[i].startswith('**B.3 '))
        for name in ('图1', '图2'):
            out['captions'][name + '_source_B2'] = record(find('- ' + name + '：', b2, end))
    return out


def text_changes(old, new):
    """All changed titles, headers, body cells and notes, without line-number noise."""
    def fields(e):
        result = {k: v['text'] for k, v in e['captions'].items()}
        for name, table in e['tables'].items():
            result[name + ' title'] = table['title']
            for j, cell in enumerate(table['header'], 1):
                result[f'{name} header {j}'] = cell
            for i, row in enumerate(table['rows'], 1):
                for j, cell in enumerate(row['cells'], 1):
                    result[f'{name} row {i} col {j}'] = cell
        return result
    a, b = fields(old), fields(new)
    return [dict(item=k, old=a.get(k, '（无）'), new=b.get(k, '（删除；出处见附录 B.2）'))
            for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('manuscript')
    ap.add_argument('source_label', nargs='?')
    args = ap.parse_args()
    print(json.dumps(extract(args.manuscript, args.source_label), ensure_ascii=False, indent=1))
