from pathlib import Path
def run():
 s=Path('web/execution.js').read_text(encoding='utf8')
 assert 'function handleSeekInput' in s and "$('execution-seek').oninput = handleSeekInput" in s and "$('execution-seek').onchange = handleSeekInput" in s
 assert "$('execution-time').value=value" in s and 'queryTime(value)' in s
 print('通过 · Web 回放滑块同步回归'); return 0
