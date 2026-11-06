"""Extract the 6 main-text figure/table bodies, titles and numeric notes from the manuscript (read-only).

Usage: python scripts/p8_extract_manuscript.py MANUSCRIPT.md [SOURCE_LABEL] > expected.json
"""
import json, hashlib, re, sys
src = sys.argv[1]
label = sys.argv[2] if len(sys.argv) > 2 else src
txt = open(src, encoding='utf-8').read()
lines = txt.splitlines()
sha = hashlib.sha256(txt.encode('utf-8')).hexdigest()
def table_after(prefix):
    i = next(k for k, l in enumerate(lines) if l.startswith(prefix))
    j = i
    while not lines[j].startswith('|'): j += 1
    hdr = [c.strip() for c in lines[j].strip('|').split('|')]
    rows = []
    k = j + 2
    while k < len(lines) and lines[k].startswith('|'):
        rows.append({'line': k + 1, 'cells': [c.strip() for c in lines[k].strip().strip('|').split('|')]})
        k += 1
    return {'title_line': i + 1, 'title': lines[i].strip(), 'header': hdr, 'rows': rows}
m_ver = re.search(r'v3\.\d+(?= 可迭代骨架)', txt)
out = {'source': label, 'source_sha256': sha, 'version': m_ver.group(0) if m_ver else 'unknown',
       'tables': {t: table_after(t + '\u3000') for t in ['表1', '表2', '表3', '表4']}}
def line_of(s):
    return next(k + 1 for k, l in enumerate(lines) if s in l)
# figure 1 / figure 2 caption lines and note lines with numbers (raw text, checked by scripts)
out['captions'] = {
  '图1_note': {'line': line_of('注：(a) 主实验果园俯视图'), 'text': lines[line_of('注：(a) 主实验果园俯视图') - 1]},
  '图2_note': {'line': line_of('注：(b1) S_h'), 'text': lines[line_of('注：(b1) S_h') - 1]},
  '表1_note': {'line': line_of('注：数据 `wt-F/results/F3_main_postcache_46360be_geom.csv`'), 'text': lines[line_of('注：数据 `wt-F/results/F3_main_postcache_46360be_geom.csv`') - 1]},
  '表3_note': {'line': line_of('注：非整数档数据'), 'text': lines[line_of('注：非整数档数据') - 1]},
  '表3_time': {'line': line_of('**时间代价（与结论同处）**'), 'text': lines[line_of('**时间代价（与结论同处）**') - 1]},
  '图1_title': {'line': line_of('图1\u3000'), 'text': lines[line_of('图1\u3000') - 1]},
  '图2_title': {'line': line_of('图2\u3000'), 'text': lines[line_of('图2\u3000') - 1]},
  '表2_source': {'line': line_of('出处：`wt-F/results/c1_blind_predict_seed10.json`'), 'text': lines[line_of('出处：`wt-F/results/c1_blind_predict_seed10.json`') - 1]},
}
print(json.dumps(out, ensure_ascii=False, indent=1))
