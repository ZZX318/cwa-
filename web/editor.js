'use strict';
/* Scene editor: precise plan-view editing plus 3D ghost placement.
   The server's /api/validate is authoritative; this file only previews. */
(function () {
  const $ = id => document.getElementById(id);
  const canvas = $('view');
  const host = () => window.sceneEditorHost;
  const PRESET_SIZES = {
    shed: [3.0, 4.0, 2.5],
    wall: [0.4, 6.0, 2.0],
    container: [2.4, 6.0, 2.6],
    post: [0.3, 0.3, 3.0]
  };
  const STYLE_LABELS = {
    regular: '规则果园（确定性）',
    jitter_rows: '抖动行株',
    clusters_gaps: '簇状 / 缺株',
    size_mix: '冠层尺寸混合',
    random_obstacles_zones: '随机障碍与区域'
  };
  const TYPE_LABEL = {
    obstacle: '障碍',
    no_fly_zone: '禁飞',
    no_spray_zone: '禁喷',
    launch: '起降点',
    tree: '树'
  };

  let tool = 'select';
  let selected = null;
  let draft = null;
  let dragState = null;
  let ghost = null;
  let placePreset = 'shed';
  let editorPointer = false;
  let lastClick = { t: 0, x: 0, y: 0 };
  let history = { undo: [], redo: [] };
  const HISTORY_LIMIT = 20;
  let snap = { enabled: true, step: 0.5 };
  let randomLock = false;
  let lastSourceKey = null;
  let lastGround = null;
  let commitSeq = 0;
  let commitBusy = false;
  let lastInspectorApply = 0;

  const scene = () => host() && host().getScene();
  const copy = value => JSON.parse(JSON.stringify(value));
  const view = () => host() && host().getView();

  function setStatus(text, type) {
    if (host()) host().status(text, type || '');
  }

  // ---------------------------------------------------------------- transforms
  function groundPoint(sx, sy) {
    const v = view();
    if (!v) return null;
    const X = (sx - v.W / 2 - v.pan[0]) / v.scale;
    const Y = (v.H / 2 + v.pan[1] - sy) / v.scale;
    const cp = Math.cos(v.pitch);
    const sp = Math.sin(v.pitch);
    if (Math.abs(sp) < 1e-6) return null;
    const zc = host().terrainHeight() - v.center[2];
    const u = (Y - cp * zc) / sp;
    const cy = Math.cos(v.yaw);
    const syaw = Math.sin(v.yaw);
    return [v.center[0] + cy * X + syaw * u, v.center[1] - syaw * X + cy * u];
  }

  function screenToWorld(sx, sy) {
    const v = view();
    if (!v) return null;
    if (v.mode === 'top' || Math.abs(v.pitch - Math.PI / 2) < 1e-9) {
      return [
        v.center[0] + (sx - v.W / 2 - v.pan[0]) / v.scale,
        v.center[1] - (sy - v.H / 2 - v.pan[1]) / v.scale
      ];
    }
    return groundPoint(sx, sy);
  }

  function worldToScreen(p) {
    if (!host()) return null;
    const point = p.length === 2 ? [p[0], p[1], host().terrainHeight()] : p;
    return host().project(point);
  }

  window.screenToWorld = screenToWorld;
  window.worldToScreen = worldToScreen;
  window.groundPoint = groundPoint;

  function canvasPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return [event.clientX - rect.left, event.clientY - rect.top];
  }

  function snapValue(value) {
    if (!snap.enabled || window._editorAlt) return value;
    return Math.round(value / snap.step) * snap.step;
  }

  function snapPoint(point) {
    return [snapValue(point[0]), snapValue(point[1])];
  }

  function screenDistance(a, b) {
    return Math.hypot(a[0] - b[0], a[1] - b[1]);
  }

  // ----------------------------------------------------------------- geometry
  function onSegment(p, a, b) {
    const cross = (a[0] - p[0]) * (b[1] - p[1]) - (a[1] - p[1]) * (b[0] - p[0]);
    if (Math.abs(cross) > 1e-9) return false;
    return (
      Math.min(a[0], b[0]) - 1e-9 <= p[0] &&
      p[0] <= Math.max(a[0], b[0]) + 1e-9 &&
      Math.min(a[1], b[1]) - 1e-9 <= p[1] &&
      p[1] <= Math.max(a[1], b[1]) + 1e-9
    );
  }

  function inPolygon(p, vertices) {
    let result = false;
    for (let i = 0; i < vertices.length; i++) {
      const a = vertices[i];
      const b = vertices[(i + 1) % vertices.length];
      if (onSegment(p, a, b)) return true;
      if (
        a[1] > p[1] !== b[1] > p[1] &&
        p[0] < ((b[0] - a[0]) * (p[1] - a[1])) / (b[1] - a[1]) + a[0]
      ) {
        result = !result;
      }
    }
    return result;
  }

  function cross(a, b, c) {
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  }

  function segmentsIntersect(a, b, c, d) {
    if (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) return true;
    return (
      onSegment(a, c, d) ||
      onSegment(b, c, d) ||
      onSegment(c, a, b) ||
      onSegment(d, a, b)
    );
  }

  function distanceToSegment(p, a, b) {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const length = dx * dx + dy * dy;
    if (length < 1e-12) return screenDistance(p, a);
    let t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
  }

  function polygonProblems(vertices) {
    const problems = [];
    if (!Array.isArray(vertices)) return ['需要顶点数组'];
    if (vertices.length < 3) problems.push('至少需要 3 个顶点');
    if (vertices.length > 1000) problems.push('最多 1000 个顶点');
    for (const vertex of vertices) {
      if (
        !Array.isArray(vertex) ||
        vertex.length !== 2 ||
        !Number.isFinite(vertex[0]) ||
        !Number.isFinite(vertex[1])
      ) {
        problems.push('顶点需要有限数值');
        return problems;
      }
    }
    const keys = new Set(vertices.map(v => v[0] + ',' + v[1]));
    if (keys.size !== vertices.length) problems.push('顶点不可重复');
    let area = 0;
    for (let i = 0; i < vertices.length; i++) {
      const a = vertices[i];
      const b = vertices[(i + 1) % vertices.length];
      area += a[0] * b[1] - a[1] * b[0];
    }
    if (Math.abs(area) <= 1e-9) problems.push('多边形面积必须非零');
    for (let i = 0; i < vertices.length; i++) {
      const a = vertices[i];
      const b = vertices[(i + 1) % vertices.length];
      for (let j = i + 1; j < vertices.length; j++) {
        if (j === i + 1 || (i === 0 && j === vertices.length - 1)) continue;
        const c = vertices[j];
        const d = vertices[(j + 1) % vertices.length];
        if (segmentsIntersect(a, b, c, d)) {
          problems.push(`边 ${i} 与边 ${j} 自交`);
          return problems;
        }
      }
    }
    return problems;
  }

  function inExtent(p, extent) {
    return (
      p[0] >= extent.min[0] - 1e-9 &&
      p[0] <= extent.max[0] + 1e-9 &&
      p[1] >= extent.min[1] - 1e-9 &&
      p[1] <= extent.max[1] + 1e-9
    );
  }

  function pointInBox(p, box) {
    return (
      box.min[0] - 1e-9 <= p[0] &&
      p[0] <= box.max[0] + 1e-9 &&
      box.min[1] - 1e-9 <= p[1] &&
      p[1] <= box.max[1] + 1e-9 &&
      box.min[2] - 1e-9 <= p[2] &&
      p[2] <= box.max[2] + 1e-9
    );
  }

  function boxesOverlap(a, b) {
    return [0, 1, 2].every(
      i => a.min[i] < b.max[i] - 1e-9 && b.min[i] < a.max[i] - 1e-9
    );
  }

  function targetBox(target) {
    const g = target.geometry;
    return {
      id: target.id,
      min: [g.center[0] - g.radius, g.center[1] - g.radius, g.z_min],
      max: [g.center[0] + g.radius, g.center[1] + g.radius, g.z_max]
    };
  }

  function boxIssues(box, s, strict) {
    const issues = [];
    for (let i = 0; i < 3; i++) {
      if (
        !Number.isFinite(box.min[i]) ||
        !Number.isFinite(box.max[i]) ||
        box.min[i] >= box.max[i]
      ) {
        issues.push('每个轴必须满足 min < max');
        return issues;
      }
    }
    if (
      !inExtent([box.min[0], box.min[1]], s.extent) ||
      !inExtent([box.max[0], box.max[1]], s.extent) ||
      box.min[2] < s.extent.min[2] - 1e-9 ||
      box.max[2] > s.extent.max[2] + 1e-9
    ) {
      issues.push('障碍超出场景范围');
    }
    for (const p of s.launch_points) {
      if (pointInBox(p.position, box)) issues.push('覆盖起降点 ' + p.id);
    }
    if (strict || box.preset) {
      for (const t of s.targets) {
        if (boxesOverlap(box, targetBox(t))) issues.push('与目标 ' + t.id + ' 体积重叠');
      }
    }
    return issues;
  }

  function zoneIssues(zone, s) {
    const problems = polygonProblems(zone.footprint.vertices);
    if (!Number.isFinite(zone.z_min) || !Number.isFinite(zone.z_max) || zone.z_min >= zone.z_max) {
      problems.push('z_min 必须小于 z_max');
    }
    if (zone.z_min < s.extent.min[2] - 1e-9 || zone.z_max > s.extent.max[2] + 1e-9) {
      problems.push('区域高度超出场景范围');
    }
    for (const v of zone.footprint.vertices) {
      if (!inExtent(v, s.extent)) {
        problems.push('区域足迹超出场景范围');
        break;
      }
    }
    for (const p of s.launch_points) {
      if (inPolygon(p.position, zone.footprint.vertices)) {
        problems.push('覆盖起降点 ' + p.id);
      }
    }
    return problems;
  }

  function launchIssues(point, s) {
    const issues = [];
    if (!Number.isFinite(point.position[0]) || !Number.isFinite(point.position[1])) {
      return ['坐标必须是有限数值'];
    }
    const flat = [point.position[0], point.position[1]];
    if (!inExtent(flat, s.extent)) issues.push('起降点超出场景范围');
    if (inPolygon(flat, s.plot.vertices)) issues.push('起降点必须在作业地块外');
    for (const o of s.obstacles) {
      if (pointInBox(point.position, o)) issues.push('落入障碍 ' + o.id);
    }
    for (const o of s.no_fly_zones) {
      if (inPolygon(flat, o.footprint.vertices)) issues.push('落入禁飞区 ' + o.id + ' 的 XY 足迹');
    }
    for (const o of s.no_spray_zones) {
      if (inPolygon(flat, o.footprint.vertices)) issues.push('落入禁喷区 ' + o.id + ' 的足迹');
    }
    if (point.role && !['both', 'start', 'return'].includes(point.role)) {
      issues.push('role 必须是 both、start 或 return');
    }
    return issues;
  }

  function allObjects() {
    const s = scene();
    if (!s) return [];
    return [
      ...(s.obstacles || []),
      ...(s.no_fly_zones || []),
      ...(s.no_spray_zones || []),
      ...(s.launch_points || []),
      ...(s.wind_buffer?.sources || [])
    ];
  }

  function nextId(prefix) {
    const used = new Set(allObjects().map(o => o.id));
    let index = 1;
    while (used.has(`${prefix}-${String(index).padStart(2, '0')}`)) index++;
    return `${prefix}-${String(index).padStart(2, '0')}`;
  }

  function nextLaunchId() {
    const used = new Set((scene().launch_points || []).map(p => p.id));
    let index = 1;
    while (used.has('launch-' + index)) index++;
    return 'launch-' + index;
  }

  function findObject(type, id) {
    const s = scene();
    if (!s) return null;
    const map = {
      obstacle: s.obstacles,
      no_fly_zone: s.no_fly_zones,
      no_spray_zone: s.no_spray_zones,
      launch: s.launch_points,
      tree: s.trees
    };
    const array = map[type];
    if (!array) return null;
    const index = array.findIndex(o => o.id === id);
    if (index < 0) return null;
    return { type, array, index, obj: array[index] };
  }

  function objectCenter(object) {
    if (object.kind === 'box') {
      return [
        (object.min[0] + object.max[0]) / 2,
        (object.min[1] + object.max[1]) / 2
      ];
    }
    if (object.footprint) {
      const vertices = object.footprint.vertices;
      return [
        vertices.reduce((sum, v) => sum + v[0], 0) / vertices.length,
        vertices.reduce((sum, v) => sum + v[1], 0) / vertices.length
      ];
    }
    return [object.position[0], object.position[1]];
  }

  // ------------------------------------------------------------------ history
  function pushHistory(label, before, after) {
    history.undo.push({ label, before, after });
    while (history.undo.length > HISTORY_LIMIT) history.undo.shift();
    history.redo = [];
  }

  function applyHistory(state) {
    host().setScene(copy(state));
    selected = null;
    draft = null;
    ghost = null;
    host().markSceneEdited();
    host().invalidatePlan();
    syncFromScene();
    host().redraw();
  }

  function undo() {
    if (guardBusy()) return;
    const entry = history.undo.pop();
    if (!entry) return;
    history.redo.push(entry);
    applyHistory(entry.before);
    setStatus('撤销：' + entry.label);
  }

  function redo() {
    if (guardBusy()) return;
    const entry = history.redo.pop();
    if (!entry) return;
    history.undo.push(entry);
    applyHistory(entry.after);
    setStatus('重做：' + entry.label);
  }

  // --------------------------------------------------------------- committing
  async function commit(candidate, label, selection) {
    if (commitBusy) {
      setStatus('上一次校验尚未完成，请稍候', 'error');
      return false;
    }
    commitBusy = true;
    const reference = scene();
    const sequence = ++commitSeq;
    try {
      setStatus('校验中… ' + label);
      let result;
      try {
        result = await host().api('/api/validate', {
          scene: candidate,
          mode: 'fast',
          strict: true
        });
      } catch (error) {
        setStatus(label + '失败：' + error.message, 'error');
        return false;
      }
      if (sequence !== commitSeq || scene() !== reference) return false;
      if (!result.ok) {
        const first = (result.errors || [])[0] || {};
        setStatus(
          label + '失败：' + (first.message || '校验未通过') + (first.path ? '\n位置：' + first.path : ''),
          'error'
        );
        return false;
      }
      const before = copy(reference);
      host().setScene(copy(candidate));
      host().markSceneEdited();
      host().invalidatePlan();
      pushHistory(label, before, copy(candidate));
      if (selection) selected = selection;
      syncFromScene();
      host().redraw();
      const warnings = result.warnings || [];
      setStatus(label + ' · 通过校验' + (warnings.length ? '\n' + warnings.join('\n') : ''));
      return true;
    } finally {
      commitBusy = false;
    }
  }

  function guardBusy() {
    if (commitBusy) {
      setStatus('校验中，请稍候…');
      return true;
    }
    return false;
  }

  function selectedTypeArray(name) {
    const s = scene();
    return s ? s[name] : null;
  }

  // ------------------------------------------------------------------ drawing
  function boxCorners(box) {
    const [x, y, z] = box.min;
    const [X, Y, Z] = box.max;
    return [
      [x, y, z],
      [X, y, z],
      [X, Y, z],
      [x, Y, z],
      [x, y, Z],
      [X, y, Z],
      [X, Y, Z],
      [x, Y, Z]
    ];
  }

  function drawWireBox(box, color, fillTop) {
    const p = boxCorners(box);
    const edges = [
      [0, 1], [1, 2], [2, 3], [3, 0],
      [4, 5], [5, 6], [6, 7], [7, 4],
      [0, 4], [1, 5], [2, 6], [3, 7]
    ];
    for (const [a, b] of edges) path([p[a], p[b]], color, 1.5);
    if (fillTop) path([p[4], p[5], p[6], p[7], p[4]], color, 1, fillTop);
  }

  function drawWirePrism(zone, color, fillTop) {
    const lo = zone.footprint.vertices.map(v => [v[0], v[1], zone.z_min]);
    const hi = zone.footprint.vertices.map(v => [v[0], v[1], zone.z_max]);
    for (let i = 0; i < lo.length; i++) {
      const j = (i + 1) % lo.length;
      path([lo[i], lo[j], hi[j], hi[i], lo[i]], color, 1.2);
    }
    if (fillTop) path([...hi, hi[0]], color, 1, fillTop);
  }

  function drawCircleWorld(center, radius, color, fill, width) {
    const p = worldToScreen([center[0], center[1], host().terrainHeight()]);
    if (!p) return;
    const v = view();
    ctx.beginPath();
    ctx.arc(p[0], p[1], Math.max(.8, radius * v.scale), 0, Math.PI * 2);
    if (fill) {
      ctx.fillStyle = fill;
      ctx.fill();
    }
    ctx.strokeStyle = color;
    ctx.lineWidth = width || 1;
    ctx.stroke();
  }

  function drawHandle(p, color) {
    const screen = worldToScreen([p[0], p[1], host().terrainHeight()]);
    if (!screen) return;
    ctx.fillStyle = '#0b1823';
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(screen[0], screen[1], 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }

  function drawDraft() {
    if (!draft) return;
    if (draft.kind === 'rect') {
      const box = draftBox();
      const bad = boxIssues(box, scene(), true).length > 0;
      const color = bad ? '#f78585' : '#7ee2a8';
      if (view().mode === 'top') {
        rectangle(box, host().terrainHeight(), color, color + '22');
      } else {
        drawWireBox(box, color, color + '22');
      }
      const labelPoint = [box.max[0], box.max[1], host().terrainHeight()];
      label(`障碍 ${(box.max[0] - box.min[0]).toFixed(2)} × ${(box.max[1] - box.min[1]).toFixed(2)} m`, labelPoint, color);
      return;
    }
    if (draft.kind === 'poly') {
      const vertices = draft.vertices.slice();
      if (draft.cursor) vertices.push(draft.cursor);
      const bad = polygonProblems(draft.vertices).length > 0;
      const color = bad ? '#f78585' : '#7ee2a8';
      if (vertices.length > 1) {
        const closed = vertices.concat([vertices[0]]);
        path(
          closed.map(v => [v[0], v[1], host().terrainHeight()]),
          color,
          2,
          bad ? 'rgba(247,133,133,.15)' : 'rgba(126,226,168,.15)'
        );
      }
      for (const vertex of draft.vertices) {
        drawHandle(vertex, color);
      }
      if (draft.cursor) drawHandle(draft.cursor, '#8da6b7');
    }
  }

  function draftBox(source) {
    const active = source || draft;
    const start = active.start;
    const current = active.current || active.start;
    const z0 = host().terrainHeight();
    const z1 = z0 + Number($('editor-obstacle-height').value || 3);
    return {
      id: 'draft',
      kind: 'box',
      min: [Math.min(start[0], current[0]), Math.min(start[1], current[1]), z0],
      max: [Math.max(start[0], current[0]), Math.max(start[1], current[1]), z1]
    };
  }

  function dragPreview() {
    if (!dragState) return null;
    return dragState.preview || null;
  }

  function boxHandles(box) {
    const [x, y] = box.min;
    const [X, Y] = box.max;
    return [
      { tag: 'minmin', p: [x, y] },
      { tag: 'maxmin', p: [X, y] },
      { tag: 'maxmax', p: [X, Y] },
      { tag: 'minmax', p: [x, Y] },
      { tag: 'midminy', p: [(x + X) / 2, y] },
      { tag: 'midmaxx', p: [X, (y + Y) / 2] },
      { tag: 'midmaxy', p: [(x + X) / 2, Y] },
      { tag: 'midminx', p: [x, (y + Y) / 2] }
    ];
  }

  function drawSelection() {
    if (!selected) return;
    const found = findObject(selected.type, selected.id);
    if (!found) return;
    const obj = found.obj;
    const inTop = view().mode === 'top';
    if (selected.type === 'obstacle') {
      if (inTop) {
        rectangle(obj, host().terrainHeight(), '#6debd6', 'rgba(109,235,214,.08)');
        for (const handle of boxHandles(obj)) drawHandle(handle.p, '#6debd6');
      } else {
        drawWireBox(obj, '#6debd6', 'rgba(109,235,214,.12)');
      }
      label(obj.id, [obj.max[0], obj.max[1], obj.max[2]], '#6debd6');
    } else if (selected.type === 'no_fly_zone' || selected.type === 'no_spray_zone') {
      const color = selected.type === 'no_fly_zone' ? '#c58cf2' : '#edc96c';
      if (inTop) {
        polygon(obj.footprint, host().terrainHeight(), color, color + '20');
        for (const vertex of obj.footprint.vertices) drawHandle(vertex, color);
      } else {
        drawWirePrism(obj, color, color + '18');
      }
      label(obj.id, [obj.footprint.vertices[0][0], obj.footprint.vertices[0][1], obj.z_max], color);
    } else if (selected.type === 'launch') {
      drawCircleWorld(obj.position, .7, '#6debd6', 'rgba(109,235,214,.15)', 2);
      label(obj.id + ' · ' + (obj.role || 'both'), [obj.position[0], obj.position[1], obj.position[2] + .2], '#6debd6');
    } else if (selected.type === 'tree') {
      drawCircleWorld(obj.position, obj.canopy.radius, '#6debd6', null, 2);
      label(obj.id + '（只读）', [obj.position[0], obj.position[1], obj.position[2] + .2], '#6debd6');
    }
    const preview = dragPreview();
    if (preview) {
      const bad = (dragState.issues || []).length > 0;
      const color = bad ? '#f78585' : '#7ee2a8';
      if (preview.kind === 'box') {
        if (inTop) rectangle(preview, host().terrainHeight(), color, color + '18');
        else drawWireBox(preview, color, color + '18');
      } else if (preview.footprint) {
        if (inTop) polygon(preview.footprint, host().terrainHeight(), color, color + '18');
        else drawWirePrism(preview, color, color + '18');
      } else if (preview.position) {
        drawCircleWorld(preview.position, .7, color, color + '22', 2);
      }
    }
  }

  function drawGhost() {
    if (!ghost) return;
    const color = ghost.valid ? '#7ee2a8' : '#f78585';
    drawWireBox(ghost.box, color, ghost.valid ? 'rgba(126,226,168,.18)' : 'rgba(247,133,133,.18)');
    label(
      '放置 ' + placePreset + (ghost.valid ? ' · 有效' : ' · ' + ghost.reason),
      [ghost.box.max[0], ghost.box.max[1], ghost.box.max[2]],
      color
    );
  }

  window.drawEditor = function () {
    if (!scene()) return;
    drawDraft();
    drawGhost();
    drawSelection();
  };
  window.sceneEditorHasDraft = () =>
    Boolean(draft && draft.kind === 'poly' && draft.vertices.length);
  window.sceneEditorDraftDescription = () =>
    draft && draft.kind === 'poly'
      ? `${draft.zone === 'poly_sensitive' ? '敏感区' : draft.zone === 'poly_no_fly' ? '禁飞' : '禁喷'}草稿（${draft.vertices.length} 点，未闭合）`
      : '';

  // ------------------------------------------------------------------ hit test
  function objectDistance(world, type, obj, tolerance) {
    if (type === 'obstacle') {
      const inside =
        obj.min[0] <= world[0] &&
        world[0] <= obj.max[0] &&
        obj.min[1] <= world[1] &&
        world[1] <= obj.max[1];
      if (inside) return 0;
      const corners = [
        [obj.min[0], obj.min[1]],
        [obj.max[0], obj.min[1]],
        [obj.max[0], obj.max[1]],
        [obj.min[0], obj.max[1]]
      ];
      let best = Infinity;
      for (let i = 0; i < 4; i++) {
        best = Math.min(best, distanceToSegment(world, corners[i], corners[(i + 1) % 4]));
      }
      return best <= tolerance ? best : Infinity;
    }
    if (type === 'no_fly_zone' || type === 'no_spray_zone') {
      const vertices = obj.footprint.vertices;
      if (inPolygon(world, vertices)) return 0;
      let best = Infinity;
      for (let i = 0; i < vertices.length; i++) {
        best = Math.min(best, distanceToSegment(world, vertices[i], vertices[(i + 1) % vertices.length]));
      }
      return best <= tolerance ? best : Infinity;
    }
    if (type === 'launch') {
      return screenDistance(world, obj.position) <= 10 / view().scale ? 0 : Infinity;
    }
    if (type === 'tree') {
      const distance = screenDistance(world, obj.position);
      return distance <= obj.canopy.radius + tolerance ? 0 : Infinity;
    }
    return Infinity;
  }

  function hitTestTop(sx, sy) {
    const s = scene();
    const world = screenToWorld(sx, sy);
    if (!world) return null;
    const tolerance = 7 / view().scale;
    const groups = [
      ['no_spray_zone', s.no_spray_zones],
      ['no_fly_zone', s.no_fly_zones],
      ['obstacle', s.obstacles],
      ['launch', s.launch_points],
      ['tree', s.trees]
    ];
    for (const [type, array] of groups) {
      for (let i = array.length - 1; i >= 0; i--) {
        if (objectDistance(world, type, array[i], tolerance) !== Infinity) {
          return { type, id: array[i].id, obj: array[i] };
        }
      }
    }
    return null;
  }

  function depthOf(point) {
    const v = view();
    const x = point[0] - v.center[0];
    const y = point[1] - v.center[1];
    const z = point[2] - v.center[2];
    return -Math.cos(v.pitch) * (Math.sin(v.yaw) * x + Math.cos(v.yaw) * y) + Math.sin(v.pitch) * z;
  }

  function hitTest3d(sx, sy) {
    const s = scene();
    const candidates = [];
    for (const obstacle of s.obstacles) {
      const projected = boxCorners(obstacle).map(p => worldToScreen(p));
      const xs = projected.map(p => p[0]);
      const ys = projected.map(p => p[1]);
      if (
        sx >= Math.min(...xs) &&
        sx <= Math.max(...xs) &&
        sy >= Math.min(...ys) &&
        sy <= Math.max(...ys)
      ) {
        const depth = boxCorners(obstacle).reduce((sum, p) => sum + depthOf(p), 0) / 8;
        candidates.push({ type: 'obstacle', id: obstacle.id, obj: obstacle, depth });
      }
    }
    for (const point of s.launch_points) {
      const projected = worldToScreen(point.position);
      if (screenDistance([sx, sy], projected) <= 12) {
        candidates.push({ type: 'launch', id: point.id, obj: point, depth: depthOf(point.position) + 1 });
      }
    }
    candidates.sort((a, b) => b.depth - a.depth);
    return candidates[0] || null;
  }

  function handleHit(sx, sy) {
    if (!selected) return null;
    const found = findObject(selected.type, selected.id);
    if (!found) return null;
    const obj = found.obj;
    const candidates = [];
    if (selected.type === 'obstacle') {
      for (const handle of boxHandles(obj)) candidates.push({ kind: 'resize', tag: handle.tag, p: handle.p });
    } else if (selected.type === 'no_fly_zone' || selected.type === 'no_spray_zone') {
      obj.footprint.vertices.forEach((vertex, index) => candidates.push({ kind: 'vertex', index, p: vertex }));
    }
    for (const candidate of candidates) {
      const screen = worldToScreen([candidate.p[0], candidate.p[1], host().terrainHeight()]);
      if (screen && screenDistance([sx, sy], screen) <= 7) return candidate;
    }
    return null;
  }

  // ------------------------------------------------------------------- editing
  function select(type, id, focus) {
    selected = { type, id };
    renderPanels();
    if (focus) {
      const found = findObject(type, id);
      if (found) host().focus(objectCenter(found.obj), 2.5);
    }
    host().redraw();
  }

  function startMove(hit, sx, sy) {
    const world = screenToWorld(sx, sy);
    if (!world) return;
    dragState = {
      kind: 'move',
      type: hit.type,
      id: hit.id,
      startWorld: snapPoint(world),
      original: copy(hit.obj),
      preview: null,
      issues: []
    };
    editorPointer = true;
  }

  function startHandle(handle, sx, sy) {
    dragState = {
      kind: handle.kind,
      type: selected.type,
      id: selected.id,
      tag: handle.tag,
      index: handle.index,
      original: copy(findObject(selected.type, selected.id).obj),
      preview: null,
      issues: []
    };
    editorPointer = true;
  }

  function patchMove(drag, world) {
    const dx = world[0] - drag.startWorld[0];
    const dy = world[1] - drag.startWorld[1];
    if (drag.type === 'obstacle') {
      return {
        id: drag.original.id,
        kind: 'box',
        min: [drag.original.min[0] + dx, drag.original.min[1] + dy, drag.original.min[2]],
        max: [drag.original.max[0] + dx, drag.original.max[1] + dy, drag.original.max[2]],
        ...(drag.original.preset ? { preset: drag.original.preset } : {})
      };
    }
    if (drag.type === 'no_fly_zone' || drag.type === 'no_spray_zone') {
      const zone = copy(drag.original);
      zone.footprint.vertices = zone.footprint.vertices.map(v => [v[0] + dx, v[1] + dy]);
      return zone;
    }
    const point = copy(drag.original);
    point.position[0] += dx;
    point.position[1] += dy;
    return point;
  }

  function patchResize(drag, world) {
    const box = copy(drag.original);
    const tag = drag.tag;
    if (['minmin', 'minmax', 'midminx'].includes(tag)) box.min[0] = world[0];
    if (['maxmin', 'maxmax', 'midmaxx'].includes(tag)) box.max[0] = world[0];
    if (['minmin', 'maxmin', 'midminy'].includes(tag)) box.min[1] = world[1];
    if (['maxmax', 'minmax', 'midmaxy'].includes(tag)) box.max[1] = world[1];
    if (box.min[0] > box.max[0]) {
      const low = box.max[0];
      box.max[0] = box.min[0];
      box.min[0] = low;
    }
    if (box.min[1] > box.max[1]) {
      const low = box.max[1];
      box.max[1] = box.min[1];
      box.min[1] = low;
    }
    return box;
  }

  function patchVertex(drag, world) {
    const zone = copy(drag.original);
    zone.footprint.vertices[drag.index] = [world[0], world[1]];
    return zone;
  }

  function issuesForObject(preview, s) {
    if (preview.kind === 'box') return boxIssues(preview, s, true);
    if (preview.footprint) return zoneIssues(preview, s);
    if (preview.position) return launchIssues(preview, s);
    return [];
  }

  function updateDrag(world) {
    if (!dragState) return;
    let preview;
    if (dragState.kind === 'move' || dragState.kind === 'move3d') {
      preview = patchMove(dragState, world);
    } else if (dragState.kind === 'resize') {
      preview = patchResize(dragState, world);
    } else if (dragState.kind === 'vertex') {
      preview = patchVertex(dragState, world);
    }
    dragState.preview = preview;
    dragState.issues = preview ? issuesForObject(preview, scene()) : [];
  }

  function finishDrag() {
    if (guardBusy()) return;
    if (!dragState || !dragState.preview) {
      dragState = null;
      host().redraw();
      return;
    }
    const issues = dragState.issues || [];
    if (issues.length) {
      setStatus('操作未提交：' + issues[0], 'error');
      dragState = null;
      host().redraw();
      return;
    }
    const candidate = copy(scene());
    const target = findObjectIn(candidate, dragState.type, dragState.id);
    if (!target) {
      dragState = null;
      return;
    }
    target.array[target.index] = copy(dragState.preview);
    const type = dragState.type;
    const id = dragState.id;
    const label =
      dragState.kind === 'resize'
        ? '调整尺寸 ' + id
        : dragState.kind === 'vertex'
        ? '移动顶点 ' + id
        : '移动 ' + id;
    dragState = null;
    commit(candidate, label, { type, id });
  }

  function finishRect() {
    if (guardBusy()) return;
    const d = draft;
    if (!d) return;
    const current = d.current || d.start;
    if (Math.abs(current[0] - d.start[0]) < 0.1 || Math.abs(current[1] - d.start[1]) < 0.1) {
      draft = null;
      setStatus('跨度过小（< 0.1 m），未创建障碍');
      host().redraw();
      return;
    }
    const box = draftBox(d);
    box.id = nextId('obstacle');
    delete box.preset;
    const candidate = copy(scene());
    candidate.obstacles.push(box);
    const issues = boxIssues(box, candidate, true);
    if (issues.length) {
      setStatus('障碍未创建：' + issues[0] + '\n草稿保留，可调整或按 Esc 取消', 'error');
      host().redraw();
      return;
    }
    draft = null;
    commit(candidate, '创建障碍 ' + box.id, { type: 'obstacle', id: box.id }).then(ok => {
      if (!ok) {
        draft = d;
        host().redraw();
      }
    });
  }

  function closePolygon() {
    if (guardBusy()) return;
    if (!draft || draft.kind !== 'poly') return;
    const vertices = draft.vertices.slice();
    const problems = polygonProblems(vertices);
    if (problems.length) {
      setStatus('多边形无效：' + problems[0] + '\n可继续调整顶点或按 Esc 取消', 'error');
      host().redraw();
      return;
    }
    const sensitive = draft.zone === 'poly_sensitive';
    const noFly = draft.zone === 'poly_no_fly';
    const zone = {
      id: nextId(sensitive ? 'sensitive' : noFly ? 'no-fly' : 'no-spray'),
      kind: 'polygon_prism',
      footprint: { kind: 'polygon', vertices },
      z_min: Number($('editor-zone-zmin').value),
      z_max: Number($('editor-zone-zmax').value)
    };
    if (sensitive) {
      const reference = scene();
      const saved = draft; draft = null;
      const sources = [...(reference.wind_buffer?.sources || []), zone];
      host().api('/api/wind-buffer', {scene:reference,sources,distance:Number($('buffer-distance').value),
        wind_speed:Number($('job-wind_speed').value),wind_direction:Number($('job-wind_direction').value)})
        .then(result => {if (scene() !== reference) return; return commit(result.scene, '创建敏感区并生成上风缓冲 '+zone.id, null);})
        .then(ok => {if (!ok) {draft=saved;host().redraw();}})
        .catch(error => {draft=saved;setStatus('敏感区未创建：'+error.message,'error');host().redraw();});
      return;
    }
    const candidate = copy(scene());
    (noFly ? candidate.no_fly_zones : candidate.no_spray_zones).push(zone);
    const issues = zoneIssues(zone, candidate);
    if (issues.length) {
      setStatus('区域未创建：' + issues[0], 'error');
      host().redraw();
      return;
    }
    const type = noFly ? 'no_fly_zone' : 'no_spray_zone';
    const savedDraft = draft;
    draft = null;
    commit(
      candidate,
      '创建' + (noFly ? '禁飞区 ' : '禁喷区 ') + zone.id,
      { type, id: zone.id }
    ).then(ok => {
      if (!ok) {
        draft = savedDraft;
        host().redraw();
      }
    });
  }

  function addLaunch(world) {
    if (guardBusy()) return;
    const role = $('editor-launch-role').value;
    const point = {
      id: nextLaunchId(),
      position: [world[0], world[1], host().terrainHeight()]
    };
    if (role !== 'both') point.role = role;
    const issues = launchIssues(point, scene());
    if (issues.length) {
      setStatus('起降点未创建：' + issues[0], 'error');
      return;
    }
    const candidate = copy(scene());
    candidate.launch_points.push(point);
    commit(candidate, '添加起降点 ' + point.id, { type: 'launch', id: point.id });
  }

  function deleteSelected() {
    if (guardBusy()) return;
    if (!selected) return;
    const found = findObject(selected.type, selected.id);
    if (!found) return;
    if (selected.type === 'tree') {
      setStatus('树/目标编辑不在本阶段范围', 'error');
      return;
    }
    if (selected.type === 'launch' && scene().launch_points.length <= 1) {
      setStatus('至少保留一个起降点，最后一个点不可删除', 'error');
      return;
    }
    if (selected.type === 'launch') {
      const references = (scene().launch_assignments || []).filter(
        item => item.start === selected.id || item.end === selected.id
      );
      if (references.length) {
        setStatus(
          '该起降点被 UAV ' +
            references.map(item => item.uav).join(', ') +
            ' 引用；请先修改起降分配，未自动级联删除',
          'error'
        );
        return;
      }
    }
    const candidate = copy(scene());
    const target = findObjectIn(candidate, selected.type, selected.id);
    if (!target) return;
    target.array.splice(target.index, 1);
    const type = selected.type;
    const id = selected.id;
    selected = null;
    commit(candidate, '删除 ' + TYPE_LABEL[type] + ' ' + id, null);
  }

  function findObjectIn(s, type, id) {
    const map = {
      obstacle: s.obstacles,
      no_fly_zone: s.no_fly_zones,
      no_spray_zone: s.no_spray_zones,
      launch: s.launch_points,
      tree: s.trees
    };
    const array = map[type];
    if (!array) return null;
    const index = array.findIndex(o => o.id === id);
    return index < 0 ? null : { array, index };
  }

  // -------------------------------------------------------------- 3D placement
  function ghostBoxAt(sx, sy) {
    const world = groundPoint(sx, sy);
    if (!world) return null;
    const point = snapPoint(world);
    const size = PRESET_SIZES[placePreset] || PRESET_SIZES.shed;
    const z0 = host().terrainHeight();
    return {
      id: 'ghost',
      kind: 'box',
      min: [point[0] - size[0] / 2, point[1] - size[1] / 2, z0],
      max: [point[0] + size[0] / 2, point[1] + size[1] / 2, z0 + size[2]],
      preset: placePreset
    };
  }

  function updateGhost(sx, sy) {
    const box = ghostBoxAt(sx, sy);
    if (!box) {
      ghost = null;
      host().redraw();
      return;
    }
    const issues = boxIssues(box, scene(), true);
    ghost = { box, valid: issues.length === 0, reason: issues[0] || '' };
    host().redraw();
  }

  function placeGhostAt(sx, sy) {
    const box = ghostBoxAt(sx, sy);
    if (!box) return;
    const issues = boxIssues(box, scene(), true);
    if (issues.length) {
      ghost = { box, valid: false, reason: issues[0] };
      setStatus('放置被拒绝：' + issues[0], 'error');
      host().redraw();
      return;
    }
    box.id = nextId('obstacle');
    const candidate = copy(scene());
    candidate.obstacles.push(box);
    const type = 'obstacle';
    const id = box.id;
    commit(candidate, '三维放置 ' + placePreset + ' ' + id, { type, id }).then(ok => {
      if (ok && !$('editor-place-continuous').checked) {
        setTool('select');
      } else if (ok) {
        ghost = null;
        host().redraw();
      }
    });
  }

  // -------------------------------------------------------------------- panels
  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[ch]);
  }

  function renderObjectList() {
    const element = $('editor-object-list');
    if (!element) return;
    const s = scene();
    if (!s) {
      element.innerHTML = '<p>场景加载中…</p>';
      return;
    }
    const rows = [];
    const add = (type, label, array) => {
      for (const object of array) {
        const active = selected && selected.type === type && selected.id === object.id;
        const extra =
          type === 'launch' && object.role ? ' · ' + object.role : '';
        rows.push(
          `<button type="button" class="${active ? 'selected' : ''}" data-type="${type}" data-id="${escapeHtml(object.id)}">${label} · ${escapeHtml(object.id)}${extra}</button>`
        );
      }
    };
    add('obstacle', '障碍', s.obstacles);
    add('no_fly_zone', '禁飞', s.no_fly_zones);
    add('no_spray_zone', '禁喷', s.no_spray_zones);
    add('launch', '起降点', s.launch_points);
    element.innerHTML =
      `<p class="editor-counts">障碍 ${s.obstacles.length} / 禁飞 ${s.no_fly_zones.length} / 禁喷 ${s.no_spray_zones.length} / 起降点 ${s.launch_points.length} / 树 ${s.trees.length}（树只读）</p>` +
      (rows.length ? rows.join('') : '<p>暂无附加对象。使用工具栏绘制或随机生成。</p>');
    for (const button of element.querySelectorAll('button[data-type]')) {
      button.onclick = () => select(button.dataset.type, button.dataset.id, true);
    }
  }

  function numberRow(label, key, value, step) {
    return `<label class="field">${label}<input type="number" step="${step}" data-insp="${key}" value="${value}"></label>`;
  }

  function renderInspector() {
    const element = $('editor-inspector');
    if (!element) return;
    if (!selected) {
      element.innerHTML = '<p>未选择对象。使用选择工具点击对象，或从对象列表选择。</p>';
      return;
    }
    const found = findObject(selected.type, selected.id);
    if (!found) {
      selected = null;
      element.innerHTML = '<p>选中对象已不存在。</p>';
      return;
    }
    const obj = found.obj;
    let html = `<p class="editor-id">${TYPE_LABEL[selected.type]} · ${escapeHtml(obj.id)}</p>`;
    if (selected.type === 'obstacle') {
      html += numberRow('min X', 'min-0', obj.min[0], 0.1);
      html += numberRow('min Y', 'min-1', obj.min[1], 0.1);
      html += numberRow('min Z', 'min-2', obj.min[2], 0.1);
      html += numberRow('max X', 'max-0', obj.max[0], 0.1);
      html += numberRow('max Y', 'max-1', obj.max[1], 0.1);
      html += numberRow('max Z', 'max-2', obj.max[2], 0.1);
      if (obj.preset) html += `<p>预设来源：${escapeHtml(obj.preset)}（仅提示，几何以 min/max 为准）</p>`;
      html += '<p><button type="button" id="insp-ground">底部落地</button></p>';
    } else if (selected.type === 'no_fly_zone' || selected.type === 'no_spray_zone') {
      html += numberRow('z_min', 'z_min', obj.z_min, 0.1);
      html += numberRow('z_max', 'z_max', obj.z_max, 0.1);
      if (selected.type === 'no_spray_zone') {
        html += '<p class="editor-hint">禁喷执行检查只看 XY 足迹，不看 z 范围。</p>';
      }
      html += `<p>顶点 ${obj.footprint.vertices.length} 个</p>`;
      const limit = Math.min(obj.footprint.vertices.length, 100);
      for (let i = 0; i < limit; i++) {
        html += `<div class="editor-vertex"><span>#${i}</span>${numberRow('X', 'v-' + i + '-x', obj.footprint.vertices[i][0], 0.1)}${numberRow('Y', 'v-' + i + '-y', obj.footprint.vertices[i][1], 0.1)}</div>`;
      }
      if (obj.footprint.vertices.length > limit) {
        html += `<p>仅显示前 ${limit} 个顶点，其余可用 JSON 同步编辑。</p>`;
      }
      html += '<p><button type="button" id="insp-ground">底面落地</button></p>';
    } else if (selected.type === 'launch') {
      html += numberRow('X', 'x', obj.position[0], 0.1);
      html += numberRow('Y', 'y', obj.position[1], 0.1);
      html += `<label class="field">角色<select data-insp="role">
        <option value="both" ${obj.role === 'both' ? 'selected' : ''}>both</option>
        <option value="start" ${obj.role === 'start' ? 'selected' : ''}>start</option>
        <option value="return" ${obj.role === 'return' ? 'selected' : ''}>return</option>
      </select></label>`;
      html += `<p>地面高度 ${host().terrainHeight().toFixed(2)} m（z 不可编辑）</p>`;
    } else if (selected.type === 'tree') {
      html += `<p>位置 [${obj.position.map(v => v.toFixed(2)).join(', ')}] m</p>`;
      html += `<p>冠层 r=${obj.canopy.radius.toFixed(2)} m · h=${(obj.canopy.z_max - obj.canopy.z_min).toFixed(2)} m</p>`;
      html += '<p>树与目标为只读；本阶段不提供树木级编辑。</p>';
    }
    if (selected.type !== 'tree') {
      html += '<div class="files"><button type="button" id="insp-apply">应用数值</button><button type="button" id="insp-delete">删除</button></div>';
    }
    element.innerHTML = html;
    for (const input of element.querySelectorAll('[data-insp]')) {
      input.onchange = applyInspector;
      input.onkeydown = event => {
        if (event.key === 'Enter') {
          event.preventDefault();
          applyInspector();
        }
      };
    }
    const apply = $('insp-apply');
    if (apply) apply.onclick = applyInspector;
    const remove = $('insp-delete');
    if (remove) remove.onclick = deleteSelected;
    const ground = $('insp-ground');
    if (ground) {
      ground.onclick = () => {
        const box = $('editor-inspector').querySelector('[data-insp="min-2"]');
        const zone = $('editor-inspector').querySelector('[data-insp="z_min"]');
        if (box) box.value = host().terrainHeight();
        if (zone) zone.value = host().terrainHeight();
        applyInspector();
      };
    }
  }

  function applyInspector() {
    if (guardBusy()) return;
    const now = performance.now();
    if (now - lastInspectorApply < 250) return;
    lastInspectorApply = now;
    if (!selected) return;
    const found = findObject(selected.type, selected.id);
    if (!found) return;
    const candidate = copy(scene());
    const target = findObjectIn(candidate, selected.type, selected.id);
    const obj = target.array[target.index];
    const value = key => {
      const input = $('editor-inspector').querySelector(`[data-insp="${key}"]`);
      if (!input || String(input.value).trim() === '') return NaN;
      return Number(input.value);
    };
    if (selected.type === 'obstacle') {
      obj.min = [value('min-0'), value('min-1'), value('min-2')];
      obj.max = [value('max-0'), value('max-1'), value('max-2')];
      const issues = boxIssues(obj, candidate, true);
      if (issues.length) {
        setStatus('修改被拒绝：' + issues[0], 'error');
        renderInspector();
        return;
      }
    } else if (selected.type === 'no_fly_zone' || selected.type === 'no_spray_zone') {
      obj.z_min = value('z_min');
      obj.z_max = value('z_max');
      const limit = Math.min(obj.footprint.vertices.length, 100);
      for (let i = 0; i < limit; i++) {
        obj.footprint.vertices[i] = [value('v-' + i + '-x'), value('v-' + i + '-y')];
      }
      const issues = zoneIssues(obj, candidate);
      if (issues.length) {
        setStatus('修改被拒绝：' + issues[0], 'error');
        renderInspector();
        return;
      }
    } else if (selected.type === 'launch') {
      obj.position[0] = value('x');
      obj.position[1] = value('y');
      const role = $('editor-inspector').querySelector('[data-insp="role"]');
      if (role) {
        if (role.value === 'both') delete obj.role;
        else obj.role = role.value;
      }
      const issues = launchIssues(obj, candidate);
      if (issues.length) {
        setStatus('修改被拒绝：' + issues[0], 'error');
        renderInspector();
        return;
      }
    } else {
      return;
    }
    commit(candidate, '修改 ' + selected.type + ' ' + selected.id, { type: selected.type, id: selected.id });
  }

  // --------------------------------------------------------------- random panel
  function randomParams() {
    const text = ($('editor-random-params').value || '{}').trim() || '{}';
    const params = JSON.parse(text);
    if (!params || Array.isArray(params) || typeof params !== 'object') {
      throw Error('参数必须是 JSON 对象');
    }
    return params;
  }

  function syncRandomPanel() {
    const s = scene();
    if (!s || !s.source) return;
    const key = JSON.stringify(s.source);
    if (key === lastSourceKey) return;
    lastSourceKey = key;
    const style = s.source.kind === 'random_orchard' ? s.source.style : 'regular';
    const styleSelect = $('editor-random-style');
    if (styleSelect && STYLE_LABELS[style]) styleSelect.value = style;
    const seedInput = $('editor-random-seed');
    if (seedInput && s.source.kind === 'random_orchard' && Number.isInteger(s.source.seed)) {
      seedInput.value = s.source.seed;
    }
    const paramsInput = $('editor-random-params');
    if (paramsInput && s.source.parameters && document.activeElement !== paramsInput) {
      paramsInput.value = JSON.stringify(s.source.parameters, null, 2);
    }
    if ($('editor-random-info')) {
      $('editor-random-info').textContent =
        s.source.kind === 'random_orchard'
          ? `当前来源：${s.source.style} · seed ${s.source.seed} · 生成器 v${s.source.generator_version}`
          : '当前来源：规则生成；随机生成会替换整个场景。';
    }
  }

  async function runRandom(kind) {
    if (guardBusy()) return;
    if (randomLock) {
      setStatus('随机结果已锁定；请先解除锁定', 'error');
      return;
    }
    if (host().isSceneEdited() && !confirm('当前场景已有手动修改，重新随机将丢弃这些修改。继续？')) return;
    const style = $('editor-random-style').value;
    const seedInput = $('editor-random-seed');
    let seed;
    if (seedInput.value.trim() === '' && kind === 'same') {
      setStatus('同 seed 重生成需要填写 seed', 'error');
      return;
    }
    if (kind === 'new') {
      seed = Math.floor(Math.random() * 900000000) + 1;
    } else if (seedInput.value.trim() === '' && kind === 'generate') {
      seed = Math.floor(Math.random() * 900000000) + 1;
    } else {
      seed = Number(seedInput.value);
      if (!Number.isInteger(seed)) {
        setStatus('seed 必须是整数', 'error');
        return;
      }
    }
    let params;
    try {
      params = randomParams();
    } catch (error) {
      setStatus('随机参数无效：' + error.message, 'error');
      return;
    }
    const before = copy(scene());
    setStatus('随机生成中… ' + style + ' · seed ' + seed);
    try {
      const response = await host().api('/api/random', {
        style,
        seed,
        params,
        require_reachable: $('editor-random-reachable').checked
      });
      pushHistory('随机生成 ' + style, before, copy(response.scene));
      host().accept(response, '随机生成成功');
      lastSourceKey = null;
      syncRandomPanel();
      seedInput.value = response.report.seed;
      const report = response.report;
      const reach = report.reachability || {};
      const reachText =
        reach.status === 'not_checked'
          ? '可达性未检查'
          : reach.status === 'success'
          ? '规划可达'
          : '规划失败：' + (reach.reason || '-');
      $('editor-random-info').textContent =
        `${report.style} · seed ${report.seed} · v${report.generator_version} · 树 ${report.counts.trees} / 障碍 ${report.counts.obstacles} / 禁飞 ${report.counts.no_fly_zones} / 禁喷 ${report.counts.no_spray_zones}\n` +
        `尝试 ${report.attempts} 次 · ${reachText}` +
        (report.warnings && report.warnings.length ? '\n' + report.warnings.join('\n') : '');
      setStatus(`随机生成成功 · ${style} · seed ${response.report.seed}`);
    } catch (error) {
      setStatus('随机生成失败：' + error.message + '\n当前场景未改变。', 'error');
    }
  }

  // --------------------------------------------------------------- JSON sync
  function setJson(id, value) {
    const element = $(id);
    if (element) element.value = JSON.stringify(value, null, 2);
  }

  function syncFromScene() {
    const s = scene();
    if (!s) return;
    setJson('obstacles', s.obstacles);
    setJson('no_fly_zones', s.no_fly_zones);
    setJson('no_spray_zones', s.no_spray_zones);
    setJson('editor-launch-json', s.launch_points);
    setJson('editor-assignments-json', s.launch_assignments || []);
    if (selected && !findObject(selected.type, selected.id)) selected = null;
    renderObjectList();
    renderInspector();
    syncRandomPanel();
    const ground = host().terrainHeight();
    if (lastGround === null || ground !== lastGround) {
      lastGround = ground;
      const zmin = $('editor-zone-zmin');
      const zmax = $('editor-zone-zmax');
      if (zmin) zmin.value = ground;
      if (zmax) zmax.value = ground + 8;
    }
  }

  window.syncEditorFromScene = function () {
    lastSourceKey = null;
    syncFromScene();
  };

  function parseJsonArray(id, label) {
    const text = ($(id).value || '[]').trim() || '[]';
    let value;
    try {
      value = JSON.parse(text);
    } catch (error) {
      throw Error(label + '：JSON 语法错误，' + error.message);
    }
    if (!Array.isArray(value)) throw Error(label + '：需要数组');
    return value;
  }

  function applyJson() {
    if (guardBusy()) return;
    let obstacles;
    let noFly;
    let noSpray;
    let launches;
    let assignments;
    try {
      obstacles = parseJsonArray('obstacles', '障碍物');
      noFly = parseJsonArray('no_fly_zones', '禁飞区');
      noSpray = parseJsonArray('no_spray_zones', '禁喷区');
      launches = parseJsonArray('editor-launch-json', '起降点');
      assignments = parseJsonArray('editor-assignments-json', '起降分配');
      launches = launches.map(point => {
        if (!point || typeof point !== 'object' || Array.isArray(point) || point.role !== 'both') {
          return point;
        }
        const copyPoint = { ...point };
        delete copyPoint.role;
        return copyPoint;
      });
    } catch (error) {
      setStatus('应用失败：' + error.message + '\n当前画面未改变。', 'error');
      return;
    }
    const candidate = copy(scene());
    candidate.obstacles = obstacles;
    candidate.no_fly_zones = noFly;
    candidate.no_spray_zones = noSpray;
    candidate.launch_points = launches;
    if (assignments.length) candidate.launch_assignments = assignments;
    else delete candidate.launch_assignments;
    commit(candidate, '应用 JSON 附加对象', null);
  }

  // ------------------------------------------------------------------- toolbar
  function buildToolbar() {
    const viewport = document.querySelector('.viewport');
    const bar = document.createElement('div');
    bar.id = 'editor-toolbar';
    bar.setAttribute('role', 'toolbar');
    bar.setAttribute('aria-label', '场景编辑工具');
    bar.innerHTML = `
      <button type="button" data-tool="select" aria-pressed="true" title="选择 / 移动 / 编辑顶点 (V)">选择 V</button>
      <button type="button" data-tool="rect" aria-pressed="false" title="拖拽矩形障碍 (R)">矩形障碍 R</button>
      <button type="button" data-tool="poly_no_fly" aria-pressed="false" title="逐点绘制禁飞多边形 (P)">禁飞 P</button>
      <button type="button" data-tool="poly_no_spray" aria-pressed="false" title="逐点绘制禁喷多边形 (Shift+P)">禁喷 ⇧P</button>
      <button type="button" data-tool="poly_sensitive" aria-pressed="false" title="逐点绘制敏感区；闭合后按当前风和距离生成缓冲">敏感区</button>
      <button type="button" data-tool="launch" aria-pressed="false" title="点击添加起降点 (L)">起降点 L</button>
      <button type="button" data-tool="place3d" aria-pressed="false" title="三维预设障碍放置 (O)">三维放置 O</button>
      <button type="button" id="editor-pan" title="平移 (H)">平移 H</button>
      <button type="button" id="editor-fit" title="适配视图 (F)">适配 F</button>
      <button type="button" id="editor-undo" title="撤销 (Cmd/Ctrl+Z)">撤销</button>
      <button type="button" id="editor-redo" title="重做 (Shift+Cmd/Ctrl+Z / Ctrl+Y)">重做</button>
      <button type="button" id="editor-save" title="下载场景 JSON（等同 01 面板保存场景）">保存场景</button>
      <label id="editor-snap-wrap">吸附
        <select id="editor-snap-step">
          <option value="0">关闭</option>
          <option value="0.1">0.1 m</option>
          <option value="0.5" selected>0.5 m</option>
          <option value="1">1 m</option>
          <option value="2">2 m</option>
          <option value="5">5 m</option>
        </select>
      </label>
      <span id="editor-coords">X – / Y – m</span>`;
    viewport.append(bar);
    for (const button of bar.querySelectorAll('button[data-tool]')) {
      button.onclick = () => setTool(button.dataset.tool);
    }
    $('editor-pan').onclick = () => {
      const pan = $('pan');
      if (pan) pan.click();
    };
    $('editor-fit').onclick = () => host().fit();
    $('editor-undo').onclick = undo;
    $('editor-redo').onclick = redo;
    $('editor-save').onclick = () => {
      if (commitBusy) return;
      if ($('save')) $('save').click();
    };
    $('editor-snap-step').onchange = event => {
      const value = Number(event.target.value);
      snap.enabled = value > 0;
      snap.step = value > 0 ? value : 0.5;
      updateCoordsReadout();
    };
  }

  function buildGroup() {
    const aside = document.querySelector('aside');
    const group = document.createElement('details');
    group.id = 'editor-panel';
    group.innerHTML = `
      <summary>09 · 场景编辑器</summary>
      <p>俯视为精确编辑面；三维视图用于预设障碍 ghost 放置与近似选中。所有提交先经服务端校验，失败保留原因。禁飞/禁喷多边形必须闭合（Enter、双击或点回首个顶点）才会应用；撤销/重做用工具栏按钮或 Cmd/Ctrl+Z；保存场景用工具栏“保存场景”或 01 面板。</p>
      <p><b>语义</b>：禁飞 = 不可飞越且不可喷洒；禁喷 = 可以飞越，但喷洒足迹不可进入。绿色轮廓是未闭合草稿，提交后会显示对应颜色与编号。</p>
      <h3>工具选项</h3>
      <label class="field">障碍默认高度 m<input id="editor-obstacle-height" type="number" value="3" step="0.1"></label>
      <label class="field">区域底面 m<input id="editor-zone-zmin" type="number" value="0" step="0.1"></label>
      <label class="field">区域顶面 m<input id="editor-zone-zmax" type="number" value="8" step="0.1"></label>
      <label class="field">新起降点角色<select id="editor-launch-role">
        <option value="both">both（起降）</option>
        <option value="start">start（仅起点）</option>
        <option value="return">return（仅终点）</option>
      </select></label>
      <label class="field">三维预设<select id="editor-place-preset">
        <option value="shed">棚屋 3.0×4.0×2.5</option>
        <option value="wall">墙段 0.4×6.0×2.0</option>
        <option value="container">货柜 2.4×6.0×2.6</option>
        <option value="post">立柱 0.3×0.3×3.0</option>
      </select></label>
      <label><input id="editor-place-continuous" type="checkbox" checked>连续放置（三维）</label>
      <h3>对象列表</h3>
      <div id="editor-object-list"></div>
      <h3>检查器</h3>
      <div id="editor-inspector"></div>
      <h3>随机地图</h3>
      <label class="field">样式<select id="editor-random-style">
        ${Object.entries(STYLE_LABELS)
          .map(([value, label]) => `<option value="${value}">${label}</option>`)
          .join('')}
      </select></label>
      <label class="field">seed<input id="editor-random-seed" type="number" step="1" value="1"></label>
      <label><input id="editor-random-reachable" type="checkbox">要求固定条带规划可达</label>
      <label>参数 JSON<textarea id="editor-random-params">{}</textarea></label>
      <div class="files">
        <button type="button" id="editor-random-generate">生成随机场景</button>
        <button type="button" id="editor-random-same">同 seed 重生成</button>
        <button type="button" id="editor-random-new">只换 seed</button>
      </div>
      <label><input id="editor-random-lock" type="checkbox">锁定随机结果</label>
      <p id="editor-random-info">同 seed + 同版本 + 同参数可复现；升级生成器版本后不保证一致。</p>
      <details id="editor-json">
        <summary>JSON 双向同步</summary>
        <p>障碍/禁飞/禁喷文本框在 01 面板。画布提交后会同步；修改后点击“应用附加对象”。</p>
        <label>起降点（launch_points）<textarea id="editor-launch-json">[]</textarea></label>
        <label>起降分配（launch_assignments，可空）<textarea id="editor-assignments-json">[]</textarea></label>
        <button type="button" id="editor-apply-json">应用附加对象</button>
        <p class="editor-hint">保存场景始终保存画布实际几何，不保存文本框草稿。</p>
      </details>`;
    aside.append(group);
    $('editor-place-preset').onchange = event => {
      placePreset = event.target.value;
      ghost = null;
      host().redraw();
    };
    $('editor-random-style').onchange = () => {
      $('editor-random-params').value = '{}';
      $('editor-random-info').textContent =
        '样式已切换：参数重置为 {}。需要该样式参数时填写 JSON，例如 {"rows":4,"trees_per_row":6}。';
    };
    $('editor-random-generate').onclick = () => runRandom('generate');
    $('editor-random-same').onclick = () => runRandom('same');
    $('editor-random-new').onclick = () => runRandom('new');
    $('editor-random-lock').onchange = event => {
      if (event.target.checked) {
        randomLock = true;
        setRandomButtons();
        setStatus('随机结果已锁定：重新随机按钮不可用，手工编辑仍可用');
        return;
      }
      if (!confirm('解除锁定后将允许重新随机覆盖当前几何。继续？')) {
        event.target.checked = true;
        return;
      }
      randomLock = false;
      setRandomButtons();
      setStatus('随机锁已解除');
    };
    $('editor-apply-json').onclick = applyJson;
  }

  function setRandomButtons() {
    for (const id of ['editor-random-generate', 'editor-random-same', 'editor-random-new']) {
      const button = $(id);
      if (button) button.disabled = randomLock;
    }
  }

  function setTool(next) {
    if (next === tool && next !== 'place3d') {
      cancelDraft();
      return;
    }
    if (
      draft &&
      draft.kind === 'poly' &&
      (tool === 'poly_no_fly' || tool === 'poly_no_spray' || tool === 'poly_sensitive') &&
      next !== tool
    ) {
      if (draft.vertices.length >= 3) {
        const problems = polygonProblems(draft.vertices);
        if (problems.length) {
          setStatus('当前多边形无效：' + problems[0] + '\n请先修正或按 Esc 取消，再切换工具', 'error');
          return;
        }
        closePolygon();
      } else {
        setStatus('未闭合的多边形已取消（至少需要 3 个顶点）');
      }
    }
    tool = next;
    cancelDraft();
    ghost = null;
    for (const button of document.querySelectorAll('#editor-toolbar button[data-tool]')) {
      button.setAttribute('aria-pressed', String(button.dataset.tool === tool));
    }
    if (tool === 'rect' || tool === 'poly_no_fly' || tool === 'poly_no_spray' || tool === 'poly_sensitive' || tool === 'launch') {
      if (host().getMode() !== 'top') host().setMode('top');
    } else if (tool === 'place3d') {
      if (host().getMode() !== 'iso') host().setMode('iso');
    }
    const help = {
      select: '选择：点击对象；拖动本体移动；拖动角点/边中点缩放；拖动区域顶点改形状。',
      rect: '矩形障碍：左键拖动生成；松手提交。Alt 临时关闭吸附。',
      poly_no_fly: '禁飞多边形：逐点点击；点击首点、Enter 或双击闭合；Backspace 删最后一点；Esc 取消。',
      poly_sensitive: '敏感区：逐点绘制，Enter 或点击首点闭合；按 02 当前风和缓冲距离生成保护范围。',
      poly_no_spray: '禁喷多边形：逐点点击；点击首点、Enter 或双击闭合；Backspace 删最后一点；Esc 取消。',
      launch: '起降点：点击空白处添加；选择工具可拖动。最后一个点不可删除。',
      place3d: '三维放置：移动鼠标预览 ghost；左键放置；Esc 退出；精确尺寸回二维或检查器。'
    };
    setStatus(help[tool] || '');
    host().redraw();
  }

  function cancelDraft() {
    draft = null;
    dragState = null;
    editorPointer = false;
    if (ghost) ghost = null;
    if (host() && scene()) host().redraw();
  }

  // ------------------------------------------------------------------ pointers
  function pointerDown(event) {
    if (!scene()) return false;
    if (guardBusy()) return true;
    const [sx, sy] = canvasPoint(event);
    if (tool === 'place3d') {
      if (event.button === 0 && !event.shiftKey) {
        placeGhostAt(sx, sy);
        return true;
      }
      return false;
    }
    if (event.button !== 0 || event.shiftKey || window._editorSpace) return false;
    if (host().getMode() !== 'top') {
      if (tool === 'select') return isoSelectDown(sx, sy);
      return false;
    }
    const world = snapPoint(screenToWorld(sx, sy));
    if (tool === 'rect') {
      draft = { kind: 'rect', start: world, current: world };
      editorPointer = true;
      host().redraw();
      return true;
    }
    if (tool === 'poly_no_fly' || tool === 'poly_no_spray' || tool === 'poly_sensitive') {
      const now = performance.now();
      const double =
        now - lastClick.t < 350 && Math.hypot(sx - lastClick.x, sy - lastClick.y) < 8;
      lastClick = { t: now, x: sx, y: sy };
      if (double) {
        closePolygon();
        return true;
      }
      if (!draft || draft.kind !== 'poly' || draft.zone !== tool) {
        draft = { kind: 'poly', zone: tool, vertices: [], cursor: world };
      }
      if (draft.vertices.length >= 3) {
        const first = worldToScreen([draft.vertices[0][0], draft.vertices[0][1], host().terrainHeight()]);
        if (first && screenDistance([sx, sy], first) <= 8) {
          closePolygon();
          return true;
        }
      }
      if (!draft.vertices.some(v => Math.hypot(v[0] - world[0], v[1] - world[1]) < 1e-9)) {
        draft.vertices.push(world);
      }
      draft.cursor = world;
      host().redraw();
      return true;
    }
    if (tool === 'launch') {
      addLaunch(world);
      return true;
    }
    if (tool === 'select') {
      if (event.detail >= 2) {
        const hit = hitTestTop(sx, sy);
        if (hit) {
          const found = findObject(hit.type, hit.id);
          if (found) host().focus(objectCenter(found.obj), 3);
          return true;
        }
      }
      return selectDown(sx, sy);
    }
    return false;
  }

  function pointerMove(event) {
    if (!scene()) return false;
    const [sx, sy] = canvasPoint(event);
    updateCoordsReadout(sx, sy);
    if (tool === 'place3d') {
      if ((event.buttons & 2) || (event.buttons & 4) || event.shiftKey) return false;
      if (ghost || editorPointer || event.buttons === 0) {
        updateGhost(sx, sy);
        return true;
      }
      return false;
    }
    if (!editorPointer) return false;
    const world = snapPoint(screenToWorld(sx, sy));
    if (draft && draft.kind === 'rect') {
      draft.current = world;
      host().redraw();
      return true;
    }
    if (draft && draft.kind === 'poly') {
      draft.cursor = world;
      host().redraw();
      return true;
    }
    if (dragState) {
      updateDrag(world);
      host().redraw();
      return true;
    }
    return false;
  }

  function pointerUp(event) {
    if (!scene()) return false;
    if (tool === 'place3d') {
      editorPointer = false;
      return event.button === 0;
    }
    if (!editorPointer) return false;
    editorPointer = false;
    if (draft && draft.kind === 'rect') {
      finishRect();
      return true;
    }
    if (dragState) {
      finishDrag();
      return true;
    }
    return false;
  }

  function pointerCancel() {
    editorPointer = false;
    dragState = null;
    if (draft && draft.kind === 'rect') draft = null;
    host().redraw();
  }

  function selectDown(sx, sy) {
    const handle = handleHit(sx, sy);
    if (handle) {
      startHandle(handle, sx, sy);
      return true;
    }
    const hit = hitTestTop(sx, sy);
    if (!hit) {
      selected = null;
      renderPanels();
      host().redraw();
      return false;
    }
    select(hit.type, hit.id, false);
    if (hit.type === 'tree') return true;
    startMove(hit, sx, sy);
    return true;
  }

  function isoSelectDown(sx, sy) {
    const hit = hitTest3d(sx, sy);
    if (!hit) return false;
    select(hit.type, hit.id, false);
    if (hit.type !== 'obstacle') return true;
    const world = groundPoint(sx, sy);
    if (!world) return false;
    dragState = {
      kind: 'move3d',
      type: 'obstacle',
      id: hit.id,
      startWorld: snapPoint(world),
      original: copy(hit.obj),
      preview: null,
      issues: []
    };
    editorPointer = true;
    return true;
  }

  function updateCoordsReadout(sx, sy) {
    const element = $('editor-coords');
    if (!element) return;
    const point = screenToWorld(sx, sy);
    element.textContent = point
      ? `X ${point[0].toFixed(2)} / Y ${point[1].toFixed(2)} m · 吸附 ${snap.enabled ? snap.step + ' m' : '关'}`
      : 'X – / Y – m';
  }

  window.editorPointerDown = pointerDown;
  window.editorPointerMove = pointerMove;
  window.editorPointerUp = pointerUp;
  window.editorPointerCancel = pointerCancel;

  // ----------------------------------------------------------------- keyboard
  document.addEventListener('keydown', event => {
    if (event.key === 'Alt') window._editorAlt = true;
    if (commitBusy) {
      setStatus('校验中，请稍候…');
      return;
    }
    const target = event.target;
    const editing = target && target.matches && target.matches('input, textarea, select');
    if (editing) {
      if (event.key === 'Enter' && $('editor-inspector') && $('editor-inspector').contains(target)) {
        event.preventDefault();
        applyInspector();
      }
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      if (event.shiftKey) redo();
      else undo();
      return;
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'y') {
      event.preventDefault();
      redo();
      return;
    }
    if (event.key === 'Escape') {
      if (draft) {
        cancelDraft();
        setStatus('已取消当前草稿');
      } else if (ghost) {
        ghost = null;
        host().redraw();
        setStatus('已取消三维 ghost');
      } else if (selected) {
        selected = null;
        renderPanels();
        host().redraw();
      } else if (tool === 'place3d') {
        setTool('select');
      }
      return;
    }
    if (event.key === 'Enter') {
      if (draft && draft.kind === 'poly') {
        event.preventDefault();
        closePolygon();
      }
      return;
    }
    if (event.key === 'Delete' || event.key === 'Backspace') {
      if (draft && draft.kind === 'poly' && draft.vertices.length) {
        event.preventDefault();
        draft.vertices.pop();
        host().redraw();
        return;
      }
      if (selected) {
        event.preventDefault();
        deleteSelected();
      }
      return;
    }
    if (event.key === ' ') {
      window._editorSpace = true;
      event.preventDefault();
      return;
    }
    const key = event.key.toLowerCase();
    if (key === 'v') setTool('select');
    else if (key === 'r') setTool('rect');
    else if (key === 'p') setTool(event.shiftKey ? 'poly_no_spray' : 'poly_no_fly');
    else if (key === 'l') setTool('launch');
    else if (key === 'o') setTool('place3d');
    else if (key === 'f') host().fit();
    else if (key === 'h') {
      const pan = $('pan');
      if (pan) pan.click();
    }
  });
  document.addEventListener('keyup', event => {
    if (event.key === 'Alt') window._editorAlt = false;
    if (event.key === ' ') window._editorSpace = false;
  });
  window.addEventListener('blur', () => {
    window._editorAlt = false;
    window._editorSpace = false;
  });

  // ------------------------------------------------------------------- panels
  function renderPanels() {
    renderObjectList();
    renderInspector();
  }

  function init() {
    buildToolbar();
    buildGroup();
    setRandomButtons();
    setTool('select');
    syncFromScene();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
