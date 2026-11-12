from pathlib import Path


def run():
    s = Path('web/execution.js').read_text(encoding='utf8')
    assert 'function handleSeekInput' in s and "$('execution-seek').oninput = handleSeekInput" in s and "$('execution-seek').onchange = handleSeekInput" in s
    assert 'function localStateAt' in s and "'/api/state'" not in s
    assert "$('execution-seek').value = state.time" in s and "$('execution-time').value = state.time.toFixed(2)" in s
    assert 'queryTime(value, true)' in s and 'queryTime(desiredTime())' in s
    assert 'id="execution-end"' in s and "$('execution-end').onclick" in s
    assert 'queryTime(timeline.duration, true)' in s
    for marker in ('value="five"', 'compare-contributions', 'comparisonRequestVersion', 'compare-save'):
        assert marker in s, marker
    assert 'id="evaluation-resolution"' in s and 'timeline,time,resolution' in s

    editor = Path('web/editor.js').read_text(encoding='utf8')
    for marker in (
        'function screenToWorld',
        'function groundPoint',
        'window.drawEditor',
        'window.editorPointerDown',
        'function commit(',
        "/api/validate",
        "/api/random",
        'editor-random-lock',
        'editor-launch-json',
        'place3d',
    ):
        assert marker in editor, marker
    index = Path('web/index.html').read_text(encoding='utf8')
    assert 'src="/editor.js"' in index
    app = Path('web/app.js').read_text(encoding='utf8')
    assert 'id="plan-nofly-example"' in app and "$('plan-nofly-example').onclick" in app
    assert 'id="plan-nospray-example"' in app and "loadRestrictionExample('no_spray_zones')" in app
    assert 'id="plan-obstacle-example"' in app and "loadRestrictionExample('obstacles')" in app
    assert '<option value="caw-a*-3d-wind" selected>' in app
    assert 'window.sceneEditorHost' in app and 'typeof drawEditor' in app and 'typeof editorPointerDown' in app
    server = Path('server.py').read_text(encoding='utf8')
    assert '"/api/random"' in server and '"/api/validate"' in server and '"/editor.js"' in server
    assert '"/api/depot"' in server and '"/api/sorties"' in server
    assert "ev.missed_targets" in s and "ev.repeated_targets" in s
    assert "function clearExperiment" in s
    assert "sortie-wh-per-eu" in s and "total_energy_wh" in s
    assert "coverage_note" in s
    for marker in (
        'id="multi-algorithm"',
        "function multiAlgorithm",
        "function multiOptions",
        'id="sortie-refill"',
        'id="sortie-recharge"',
        "refill_seconds:Number($('sortie-refill').value)",
        "recharge_seconds:Number($('sortie-recharge').value)",
    ):
        assert marker in s, marker
    assert "multiRequest()" in s
    assert '"/api/multi"' in server and "algorithm" in server
    assert "algorithm=payload.get('algorithm'" in server

    # Sidebar panels must be continuous: 01-08 historical panels + 09 editor.
    for title in (
        '01 · 场景与图层',
        '02 · 单机作业计划',
        '03 · 时间模型与回放',
        '04 · 真实算法对照',
        '05 · 多机协同',
        '06 · 实验统计',
        '07 · 转场搜索诊断',
        '08 · 联合作业顺序',
    ):
        assert f'<summary>{title}</summary>' in s, title
    assert '<summary>09 · 场景编辑器</summary>' in editor
    assert '10 · 场景编辑器' not in editor
    assert '<summary>10 · 起降点优化</summary>' in s
    assert '<summary>11 · 多批次（载药）</summary>' in s
    for old in (
        '05 · 真实算法对照',
        '06 · 多机协同',
        '07 · 实验统计',
        '08 · 转场搜索诊断',
        '09 · 联合作业顺序',
    ):
        assert f'<summary>{old}</summary>' not in s, old
    assert '见 03/04 面板' in app and '见 03/05 面板' not in app
    print('通过 · Web 回放滑块、编辑器钩子、端点与 01–11 面板连续性回归')
    return 0
