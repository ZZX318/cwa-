'use strict';
const $ = id => document.getElementById(id),
  canvas = $('view'),
  ctx = canvas.getContext('2d');
let scene = null,
  config = null,
  dirty = false,
  sceneEdited = false,
  mode = 'iso',
  yaw = -0.62,
  pitch = .67,
  zoom = 1,
  pan = [0, 0],
  scale = 1,
  center = [0, 0, 0],
  drag = null,
  panMode = false,
  lastView = null;
const show = {
  canopies: true,
  trunks: true,
  plot: true,
  grid: true,
  extent: true,
  targets: false,
  launch: true,
  objects: true,
  axes: true
};
const fields = [
  ['rows', '树行数', 1],
  ['trees_per_row', '每行棵数', 1],
  ['row_spacing', '行距 · m', .1],
  ['plant_spacing', '株距 · m', .1],
  ['canopy_radius', '树冠半径 · m', .1],
  ['canopy_height', '树冠高度 · m', .1],
  ['trunk_radius', '树干半径 · m', .01],
  ['trunk_height', '树干高度 · m', .1],
  ['plot_margin', '边缘留白 · m', .1],
  ['reserve', '外围预留 · m', .1],
  ['ground_z', '地面高度 · m', .1]
];
for (let i = 0; i < fields.length; i++) {
  let [key, label, step] = fields[i];
  let l = document.createElement('label');
  l.className = 'field';
  l.innerHTML = `<span>${label}</span><input id="${key}" type="number" step="${step}" required>`;
  $(i < 6 ? 'fields' : 'advanced').append(l);
}
for (const [key, label] of Object.entries({
    canopies: '树冠',
    trunks: '树干',
    plot: '地块边界',
    grid: '地面网格',
    extent: '场景范围',
    targets: '目标体积轮廓',
    launch: '起降点',
    objects: '障碍与区域',
    axes: '坐标方向'
  })) {
  let l = document.createElement('label');
  let i = document.createElement('input');
  i.type = 'checkbox';
  i.checked = show[key];
  i.id = 'layer-' + key;
  i.onchange = () => {
    show[key] = i.checked;
    draw()
  };
  l.append(i, label);
  $('layers').append(l);
}

function status(text, type = '') {
  $('status').textContent = text;
  $('status').className = type;
}

function markDirty() {
  invalidatePlan();
  dirty = true;
  status('参数已修改，尚未生成。\n当前画面仍是上一次成功的场景。', 'dirty');
}
$('config').addEventListener('input', markDirty);

function populate(c) {
  config = structuredClone(c);
  for (const [k] of fields) $(k).value = c[k];
  for (const k of ['obstacles', 'no_fly_zones', 'no_spray_zones']) $(k).value = JSON.stringify(c[k], null, 2);
}

function readConfig() {
  let c = {};
  for (const [k] of fields) c[k] = $(k).value.trim() === '' ? null : Number($(k).value);
  for (const k of ['obstacles', 'no_fly_zones', 'no_spray_zones']) {
    try {
      c[k] = JSON.parse($(k).value)
    } catch (e) {
      throw Error(k + '：JSON 语法错误，' + e.message)
    }
  }
  return c;
}
async function api(path, data) {
  let r = await fetch(path, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
  let d = await r.json();
  if (!r.ok) throw Error(d.error);
  return d;
}

function accept(d, label) {
  invalidatePlan();
  scene = d.scene;
  dirty = false;
  sceneEdited = false;
  fit();
  let s = d.summary;
  $('sceneTitle').textContent = `${s.trees} 棵 · 果园场景`;
  $('sceneInfo').textContent = `地块 ${s.plot_size.map(x=>x.toFixed(1)).join(' × ')} m  /  目标 ${s.targets} 个`;
  status(`${label} · ${s.trees} 棵树\n障碍 ${s.obstacles} / 禁飞 ${s.no_fly_zones} / 禁喷 ${s.no_spray_zones}` + (s.warnings.length ? '\n' + s.warnings.join('\n') : ''));
  draw();
  if (typeof syncEditorFromScene === 'function') syncEditorFromScene();
  if ($('buffer-sources')) {
    $('buffer-sources').value = JSON.stringify(scene.wind_buffer?.sources || [], null, 2);
    if (scene.wind_buffer) $('buffer-distance').value = scene.wind_buffer.distance;
  }
}
$('config').onsubmit = async e => {
  e.preventDefault();
  if (sceneEdited && !confirm('场景已有手动或随机编辑，重新生成会替换当前几何。继续？')) return;
  try {
    let c = readConfig();
    let d = await api('/api/generate', c);
    config = c;
    accept(d, '生成成功')
  } catch (e) {
    status('生成失败：' + e.message + '\n当前画面仍是上一次成功的场景。', 'error')
  }
};
$('save').onclick = async () => {
  try {
    let d = await api('/api/save', scene),
      url = URL.createObjectURL(new Blob([d.serialized], {
        type: 'application/json'
      }));
    let a = document.createElement('a');
    a.href = url;
    a.download = 'orchard.scene.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    status('已保存当前画面对应的场景。' + (dirty ? '\n未生成的参数未写入文件。' : ''), dirty ? 'dirty' : '')
  } catch (e) {
    status('保存失败：' + e.message, 'error')
  }
};
$('load').onclick = () => $('file').click();
$('file').onchange = async () => {
  try {
    let f = $('file').files[0];
    if (!f) return;
    if (sceneEdited && !confirm('场景已有手动或随机编辑，加载会替换当前几何。继续？')) return;
    let d = await api('/api/load', JSON.parse(await f.text()));
    if (d.scene.source.kind === 'regular_orchard') populate({
      ...config,
      ...d.scene.source.parameters
    });
    accept(d, '加载成功（保留文件实际几何）：' + f.name);
    status($('status').textContent + '\n输入框是来源参数；重新生成会替换已加载几何。')
  } catch (e) {
    status('加载失败：' + e.message + '\n当前画面仍是上一次成功的场景。', 'error')
  } finally {
    $('file').value = ''
  }
};
$('defaults').onclick = async () => {
  if (sceneEdited && !confirm('场景已有手动或随机编辑，恢复默认会替换当前几何。继续？')) return;
  try {
    let d = await (await fetch('/api/default')).json();
    populate(d.config);
    accept(await api('/api/load', d.scene), '已恢复默认')
  } catch (e) {
    status(e.message, 'error')
  }
};

function setMode(m) {
  panMode = false;
  $('pan').classList.remove('selected');
  $('pan').setAttribute('aria-pressed', 'false');
  mode = m;
  yaw = m === 'top' ? 0 : -.62;
  pitch = m === 'top' ? Math.PI / 2 : .67;
  fit();
  $('iso').classList.toggle('selected', m === 'iso');
  $('top').classList.toggle('selected', m === 'top');
  draw()
}
$('pan').onclick = () => {
  panMode = !panMode;
  $('pan').classList.toggle('selected', panMode);
  $('pan').setAttribute('aria-pressed', String(panMode))
};
$('iso').onclick = () => setMode('iso');
$('top').onclick = () => setMode('top');
$('reset').onclick = () => setMode(mode);
$('opacity').oninput = draw;

function fit() {
  if (!scene) return;
  let b = scene.extent;
  center = b.min.map((v, i) => (v + b.max[i]) / 2);
  center[2] = scene.terrain.height + (b.max[2] - b.min[2]) * .18;
  zoom = 1;
  pan = [0, 0];
}

function basis(p) {
  let x = p[0] - center[0],
    y = p[1] - center[1],
    z = p[2] - center[2],
    cy = Math.cos(yaw),
    sy = Math.sin(yaw),
    cp = Math.cos(pitch),
    sp = Math.sin(pitch);
  return [cy * x - sy * y, sp * (sy * x + cy * y) + cp * z, -cp * (sy * x + cy * y) + sp * z]
}

function project(p) {
  let b = basis(p);
  return [canvas.clientWidth / 2 + b[0] * scale + pan[0], canvas.clientHeight / 2 - b[1] * scale + pan[1]]
}

function path(points, color, width = 1, fill = null, dash = []) {
  if (!points.length) return;
  ctx.beginPath();
  let a = project(points[0]);
  ctx.moveTo(...a);
  for (let p of points.slice(1)) ctx.lineTo(...project(p));
  if (fill) {
    ctx.closePath();
    ctx.fillStyle = fill;
    ctx.fill()
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.setLineDash(dash);
  ctx.stroke();
  ctx.setLineDash([])
}

function rectangle(b, z, color, fill = null, dash = []) {
  let [x, y] = b.min, [X, Y] = b.max;
  path([
    [x, y, z],
    [X, y, z],
    [X, Y, z],
    [x, Y, z],
    [x, y, z]
  ], color, 1, fill, dash)
}

function polygon(p, z, color, fill = null, dash = []) {
  let vs = p.vertices.map(v => [...v, z]);
  path([...vs, vs[0]], color, 1, fill, dash)
}

function circleAt(center, radius, fill, stroke, width = 1) {
  let p = project([center[0], center[1], scene.terrain.height]);
  ctx.beginPath();
  ctx.arc(p[0], p[1], Math.max(.6, radius * scale), 0, Math.PI * 2);
  if (fill) {
    ctx.fillStyle = fill;
    ctx.fill();
  }
  if (stroke) {
    ctx.strokeStyle = stroke;
    ctx.lineWidth = width;
    ctx.stroke();
  }
}

function label(text, p, color = '#95afbd') {
  let a = project(p);
  ctx.font = '11px -apple-system, sans-serif';
  ctx.fillStyle = color;
  ctx.fillText(text, a[0] + 7, a[1] - 7)
}

function ring(g, z) {
  return Array.from({
    length: 32
  }, (_, i) => [g.center[0] + g.radius * Math.cos(i * Math.PI / 16), g.center[1] + g.radius * Math.sin(i * Math.PI / 16), z])
}

function cylinderFaces(g, color, alpha = 1, wire = false) {
  let bottom = ring(g, g.z_min),
    top = ring(g, g.z_max),
    faces = [];
  for (let i = 0; i < 32; i++) {
    let j = (i + 1) % 32;
    let shade = .66 + .28 * (Math.cos(i * Math.PI / 16 - 1) + 1) / 2;
    let col = color.map(v => Math.round(v * shade));
    faces.push({
      points: [bottom[i], bottom[j], top[j], top[i]],
      fill: `rgba(${col},${alpha})`,
      stroke: wire ? '#65c7b4' : `rgba(${col},${alpha})`
    })
  }
  faces.push({
    points: top,
    fill: `rgba(${color.map(v=>Math.min(255,v+20))},${alpha})`,
    stroke: wire ? '#65c7b4' : `rgba(${color},${alpha})`
  });
  return faces;
}

function boxFaces(b, color) {
  let [x, y, z] = b.min, [X, Y, Z] = b.max;
  let p = [
    [x, y, z],
    [X, y, z],
    [X, Y, z],
    [x, Y, z],
    [x, y, Z],
    [X, y, Z],
    [X, Y, Z],
    [x, Y, Z]
  ];
  return [
    [0, 1, 5, 4],
    [1, 2, 6, 5],
    [2, 3, 7, 6],
    [3, 0, 4, 7],
    [4, 5, 6, 7]
  ].map(idx => ({
    points: idx.map(i => p[i]),
    fill: color + '25',
    stroke: color
  }));
}

function prismFaces(o, color) {
  let lo = o.footprint.vertices.map(v => [...v, o.z_min]),
    hi = o.footprint.vertices.map(v => [...v, o.z_max]);
  return [...lo.map((p, i) => ({
    points: [p, lo[(i + 1) % lo.length], hi[(i + 1) % lo.length], hi[i]],
    fill: color + '20',
    stroke: color
  })), {
    points: hi,
    fill: color + '30',
    stroke: color
  }]
}

function draw() {
  if (!scene) return;
  const W = canvas.clientWidth,
    H = canvas.clientHeight;
  ctx.clearRect(0, 0, W, H);
  let b = scene.extent,
    z = scene.terrain.height;
  // Fit projected extent corners, preserving one common metric scale on all axes.
  let corners = [];
  for (let x of [b.min[0], b.max[0]])
    for (let y of [b.min[1], b.max[1]])
      for (let zz of [z, Math.max(z + 1, ...scene.trees.map(t => t.canopy.z_max), ...scene.targets.map(t => t.geometry.z_max), ...scene.obstacles.map(o => o.max[2]), ...scene.no_fly_zones.map(o => o.z_max), ...scene.no_spray_zones.map(o => o.z_max))]) corners.push(basis([x, y, zz]));
  let xs = corners.map(p => p[0]),
    ys = corners.map(p => p[1]);
  scale = Math.min((W - 95) / (Math.max(...xs) - Math.min(...xs)), (H - 195) / (Math.max(...ys) - Math.min(...ys))) * zoom;
  lastView = {
    W,
    H,
    scale,
    center: center.slice(),
    pan: pan.slice(),
    yaw,
    pitch,
    mode,
    zoom
  };
  rectangle(b, z, '#274353', '#10212b');
  polygon(scene.plot, z, '#34483b', '#22352e');
  let step = Math.max(1, Math.pow(10, Math.floor(Math.log10(Math.max(b.max[0] - b.min[0], b.max[1] - b.min[1]) / 10))));
  if (Math.max(b.max[0] - b.min[0], b.max[1] - b.min[1]) / step > 30) step *= 2;
  if (show.grid) {
    for (let x = Math.ceil(b.min[0] / step) * step; x <= b.max[0]; x += step) path([
      [x, b.min[1], z],
      [x, b.max[1], z]
    ], '#34505a', .5);
    for (let y = Math.ceil(b.min[1] / step) * step; y <= b.max[1]; y += step) path([
      [b.min[0], y, z],
      [b.max[0], y, z]
    ], '#34505a', .5)
  }
  if (show.extent) rectangle(b, z, '#557082', null, [5, 6]);
  if (show.plot) polygon(scene.plot, z, '#ccad78', null, [7, 4]);
  if (mode === 'top') {
    // Lightweight plan-view: circles and flat footprints, no cylinder faces.
    let canopyAlpha = Number($('opacity').value);
    for (let t of scene.trees) {
      if (show.trunks) circleAt(t.trunk.center, t.trunk.radius, '#946f45', '#74552f', .6);
      if (show.canopies) circleAt(t.canopy.center, t.canopy.radius, `rgba(86,150,98,${canopyAlpha})`, '#5f9e6b', .8);
    }
    if (show.objects)
      for (let [key, color] of [
          ['obstacles', '#ed9b68'],
          ['no_fly_zones', '#c58cf2'],
          ['no_spray_zones', '#edc96c']
        ])
        for (let o of scene[key]) {
          if (o.kind === 'box') rectangle(o, z, color, color + '25');
          else polygon(o.footprint, z, color, color + '20');
        }
  } else {
    let faces = [];
    for (let t of scene.trees) {
      if (show.trunks) faces.push(...cylinderFaces(t.trunk, [148, 111, 69]));
      if (show.canopies) faces.push(...cylinderFaces(t.canopy, [86, 150, 98], Number($('opacity').value)));
    }
    if (show.objects)
      for (let [key, color] of [
          ['obstacles', '#ed9b68'],
          ['no_fly_zones', '#c58cf2'],
          ['no_spray_zones', '#edc96c']
        ])
        for (let o of scene[key]) faces.push(...(o.kind === 'box' ? boxFaces(o, color) : prismFaces(o, color)));
    faces.sort((a, b) => {
      let depth = f => f.points.reduce((v, p) => v + basis(p)[2], 0) / f.points.length;
      return depth(a) - depth(b)
    });
    for (let f of faces) path(f.points, f.stroke, .5, f.fill);
  }
  if (show.objects && scene.wind_buffer)
    for (const source of scene.wind_buffer.sources) {
      polygon(source.footprint, z + .03, '#ff7777', null, [5, 3]);
      label('敏感区 ' + source.id, [...source.footprint.vertices[0], z + .05], '#ffaaaa');
    }
  if ($('job-wind_direction')) {
    const a=Number($('job-wind_direction').value), speed=Number($('job-wind_speed').value);
    const origin=[W-95,H-65], p0=project(center),p1=project([center[0]-Math.cos(a),center[1]-Math.sin(a),center[2]]);
    const dx=p1[0]-p0[0],dy=p1[1]-p0[1],length=Math.hypot(dx,dy)||1;
    const end=[origin[0]+35*dx/length,origin[1]+35*dy/length];
    ctx.save();ctx.strokeStyle='#7edcff';ctx.fillStyle='#7edcff';ctx.lineWidth=2;
    ctx.beginPath();ctx.moveTo(...origin);ctx.lineTo(...end);ctx.stroke();
    const angle=Math.atan2(end[1]-origin[1],end[0]-origin[0]);
    ctx.beginPath();ctx.moveTo(...end);ctx.lineTo(end[0]-9*Math.cos(angle-.45),end[1]-9*Math.sin(angle-.45));ctx.lineTo(end[0]-9*Math.cos(angle+.45),end[1]-9*Math.sin(angle+.45));ctx.closePath();ctx.fill();
    ctx.font='12px sans-serif';ctx.fillText('风吹向 '+speed+' m/s',W-155,H-22);ctx.restore();
  }
  if (show.targets)
    for (let t of scene.targets) {
      let g = t.geometry;
      let r = ring(g, g.z_max),
        lo = ring(g, g.z_min);
      path([...r, r[0]], '#6debd6', 1, null, [3, 3]);
      path([...lo, lo[0]], '#6debd6', 1, null, [3, 3]);
      for (let i of [0, 8, 16, 24]) path([lo[i], r[i]], '#6debd6', 1, null, [3, 3]);
    }
  if (show.launch)
    for (let p of scene.launch_points) {
      let g = {
        center: p.position.slice(0, 2),
        radius: .7
      };
      let r = ring(g, z + .025);
      path([...r, r[0]], '#56d9ee', 2, '#164b5d');
      let role = p.role || '';
      let text = role === 'start' ? 'S · ' + p.id : role === 'return' ? 'R · ' + p.id : role === 'both' ? 'H · ' + p.id : 'H · 起降点';
      label(text, [...p.position.slice(0, 2), z + .1], '#77e0f0')
    }
  if (show.objects)
    for (let k of ['obstacles', 'no_fly_zones', 'no_spray_zones'])
      for (let o of scene[k]) label(o.id, o.kind === 'box' ? o.max : [...o.footprint.vertices[0], o.z_max]);
  if (show.axes) {
    let o = [b.min[0] + 1, b.min[1] + 1, z],
      len = 3;
    for (let [i, col, txt] of [
        [0, '#ed9484', '+X'],
        [1, '#8ccf9f', '+Y'],
        [2, '#7dbbea', '+Z']
      ]) {
      let end = [...o];
      end[i] += len;
      path([o, end], col, 2);
      label(txt, end, col)
    }
  }
  drawPlan();
  if(typeof drawCoverage === "function") drawCoverage();
  if(typeof drawPlaybackPaths === "function") drawPlaybackPaths();
  if(typeof drawDynamic === "function") drawDynamic();
  else if(typeof drawAircraft === "function") drawAircraft();
  if (typeof drawEditor === 'function') drawEditor();
  $('scale').textContent = `网格 ${step} m · 正交投影 · 局部坐标 / m`;
  // A real metric scale bar, independent of scene orientation.
  ctx.strokeStyle = '#8da6b7';
  ctx.lineWidth = 1;
  ctx.beginPath();
  let bx = W - 130,
    by = H - 90,
    metres = step * 2;
  ctx.moveTo(bx, by);
  ctx.lineTo(bx + metres * scale, by);
  ctx.stroke();
  ctx.fillStyle = '#8da6b7';
  ctx.font = '10px sans-serif';
  ctx.fillText(metres + ' m', bx, by - 7);
}

function resize() {
  let dpr = window.devicePixelRatio || 1;
  canvas.width = canvas.clientWidth * dpr;
  canvas.height = canvas.clientHeight * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  draw()
}
new ResizeObserver(resize).observe(canvas);
canvas.oncontextmenu = e => e.preventDefault();
canvas.onpointerdown = e => {
  if (typeof editorPointerDown === 'function' && editorPointerDown(e)) {
    try {
      canvas.setPointerCapture(e.pointerId);
    } catch (_) {}
    return;
  }
  canvas.setPointerCapture(e.pointerId);
  drag = {
    x: e.clientX,
    y: e.clientY,
    pan: panMode || e.button !== 0 || e.shiftKey || !!window._editorSpace
  };
};
canvas.onpointermove = e => {
  if (typeof editorPointerMove === 'function' && editorPointerMove(e)) return;
  if (!drag) return;
  let dx = e.clientX - drag.x,
    dy = e.clientY - drag.y;
  drag.x = e.clientX;
  drag.y = e.clientY;
  if (drag.pan) {
    pan[0] += dx;
    pan[1] += dy
  } else if (mode !== 'top') {
    yaw += dx * .008;
    pitch = Math.max(.12, Math.min(1.48, pitch + dy * .007))
  }
  draw()
};
canvas.onpointerup = e => {
  if (typeof editorPointerUp === 'function' && editorPointerUp(e)) {
    drag = null;
    return;
  }
  drag = null;
};
canvas.onpointercancel = e => {
  if (typeof editorPointerCancel === 'function') editorPointerCancel(e);
  drag = null;
};
canvas.onwheel = e => {
  e.preventDefault();
  let rect = canvas.getBoundingClientRect(),
    sx = e.clientX - rect.left,
    sy = e.clientY - rect.top,
    anchor = typeof screenToWorld === 'function' ? screenToWorld(sx, sy) : null;
  zoom = Math.max(.2, Math.min(8, zoom * Math.exp(-e.deltaY * .001)));
  draw();
  if (anchor && typeof worldToScreen === 'function') {
    let after = worldToScreen(anchor);
    if (after) {
      pan[0] += sx - after[0];
      pan[1] += sy - after[1];
      draw();
    }
  }
};
(async () => {
  try {
    let d = await (await fetch('/api/initial')).json();
    populate({
      ...d.config,
      ...(d.scene.source.kind === 'regular_orchard' ? d.scene.source.parameters : {})
    });
    accept(await api('/api/load', d.scene), '启动场景已就绪');
    resize()
  } catch (e) {
    status('初始化失败：' + e.message, 'error')
  }
})();

// Job settings and plans are independent of orchard generator settings.
let currentPlan = null;
const jobPanel = document.createElement('section');
jobPanel.innerHTML = `<h3>单机作业计划</h3><p>几何喷幅与分段运动模型。默认 CAW：三维绕障＋最近邻与 2-opt 顺序优化。固定 Y 仅作直线基线，实际冲突时报错。场景编辑后必须重新“生成航线”。</p>
<label class="field">规划方法<select id="job-algorithm"><optgroup label="主要算法"><option value="caw-a*-3d-wind" selected>CAW 顺序优化（默认主方法）</option></optgroup><optgroup label="基础对照与消融"><option value="fixed-y-boustrophedon">固定 Y：直线基线，冲突报错</option><option value="caw-a*-fixed-order">CAW 固定顺序（消融）</option><option value="caw-a*-nn">CAW 仅最近邻（消融）</option><option value="naive-target-order">逐目标直线（弱对照）</option></optgroup></select></label>
<label class="field">目标口径<select id="job-objective"><option value="time">时间</option><option value="energy">能量代理（CAW）</option></select></label>
<label class="field" id="job-caw-only">顺序策略<select id="job-order_strategy"><option value="nn+2opt">NN + 2-opt</option><option value="nn">最近邻</option><option value="fixed">固定 Y 顺序</option></select></label>
<label class="field" id="job-caw-grid">网格步长 m<select id="job-step_xy"><option value="0.5">0.5</option><option value="1" selected>1.0</option><option value="2">2.0</option></select></label>
<label class="field">有效喷幅 m<input id="job-swath" type="number" value="2" step="0.1"></label>
<label class="field">航带向 +X 平移 m（小于喷幅）<input id="job-lane_phase" type="number" value="0" min="0" step="0.01"></label>
<label class="field">冠顶高度差 m<input id="job-height_offset" type="number" value="2" step="0.1"></label>
<label class="field">安全净空 m<input id="job-clearance" type="number" value="0.5" step="0.1"></label>
<label class="field">目标速度 m/s<input id="job-speed" type="number" value="2" step="0.1"></label>
<label class="field">风速 m/s<input id="job-wind_speed" type="number" value="0" min="0" step="0.1"></label>
<label class="field">风吹向<select id="wind-preset"><option value="3.141592653589793">从左向右 →（来自 −X）</option><option value="0" selected>从右向左 ←（来自 +X）</option><option value="1.5707963267948966">从上向下 ↓（来自 +Y）</option><option value="4.71238898038469">从下向上 ↑（来自 −Y）</option><option value="custom">自定义来向</option></select></label>
<label class="field">风向（来向） rad<input id="job-wind_direction" type="number" value="0" step="0.1"></label>
<label class="field">风向代价<input id="job-wind_cost" type="number" value="0.25" min="0.01" step="0.05"></label>
<input id="job-transition_mode" type="hidden" value="fixed">
<button id="plan-generate">生成航线</button><button id="plan-save">保存计划</button><button id="plan-load">加载计划</button>
<button id="plan-nofly-example">加载禁飞验证样例（替换当前场景）</button>
<button id="plan-nospray-example">加载禁喷切段样例（替换当前场景）</button>
<button id="plan-obstacle-example">加载障碍绕行样例（替换当前场景）</button>
<p>CAW 按禁飞范围切开喷洒段，转场三维绕行；固定 Y 不绕障，冲突报错。区内树冠可能漏喷。禁飞高度限制飞行，水平范围同时禁止喷洒。生成后可在 03 面板点“查看最终覆盖”。</p>
<p>禁喷区允许关喷飞越。与喷幅冲突的区间会自动切开，越过后继续喷洒；评价同时显示可喷树冠覆盖和约束外额外漏喷面积。</p>
<p>CAW 会切除碰到实体障碍净空的喷洒区间，转场遇阻时搜索三维路径。障碍物是具有底高和顶高的三维实体；满足净空时可以绕侧或越顶。起降点被挡或完全无路可走时会提示原因。CAW 的转场由其自身规划器处理。</p>
<details><summary>风与敏感区缓冲</summary>
<p>优先点击地图工具栏“敏感区”，逐点绘制后按 Enter 闭合；系统自动生成缓冲。下方 JSON 为高级编辑入口，不会改动已有手工禁喷区。来向 0 = 从 +X 吹来，3.141592653589793 = 从 −X 吹来。缓冲朝来向扩展。</p>
<label class="field">敏感区 JSON<textarea id="buffer-sources" rows="5">[]</textarea></label>
<label class="field">缓冲距离 m（实验输入）<input id="buffer-distance" type="number" min="0" step="0.1" value="3.5"></label>
<button id="buffer-apply">按当前风重新生成缓冲</button>
<p id="buffer-status">距离从喷洒足迹边缘计；静风不新增缓冲。斜风/非矩形使用保守包围盒，未建立真实漂移模型。改变风或距离后需重新应用。</p></details>
<button id="recover-coverage">计算区外漏喷恢复方案</button><p id="recover-status">区内树冠必须关喷；区外仍需喷洒。可比较候选航带相位，选择减少额外漏喷的方案，并显示时间代价。</p>
<label class="field">额外时间上限 s<input id="recovery-budget" type="number" min="0" value="60" step="5"></label>
<button id="recover-options">比较整体平移与局部边带</button>
<p>按当前场景和相位建立 CAW 默认参数对照。保护范围不变；局部方案最多补4段，可能增加重复喷洒。修改场景或参数后需重新比较。</p>
<div id="recovery-options"></div>
<button id="plan-multi-sensitive-example">加载多敏感区密植样例（替换当前场景）</button>
<button id="plan-wind-example">加载侧风压树样例（替换当前场景）</button>
<p>红色虚线为原始敏感区，黄色为含缓冲的最终禁喷范围。禁飞是规定的三维禁入体积，实体障碍是实际占用空间，两者与允许关喷飞越的敏感区不同。区内关喷，区外额外漏喷单独评价。航带平移可作相位对照；喷头仍按航段即时开关，尚未模拟滞后。</p>
<input id="plan-file" type="file" hidden><label><input id="plan-visible" type="checkbox" checked>航线</label><p id="plan-status">尚未生成计划</p>`;
document.querySelector('aside').append(jobPanel);

function invalidatePlan() {
  if(typeof resetExecution === "function") resetExecution();
  currentPlan = null;
  if ($('plan-status')) $('plan-status').textContent = '计划已失效，请重新生成';
  if (scene) draw();
}

function jobConfig() {
  if (scene?.wind_buffer && (Number($('buffer-distance').value) !== scene.wind_buffer.distance ||
      JSON.stringify(JSON.parse($('buffer-sources').value)) !== JSON.stringify(scene.wind_buffer.sources)))
    throw Error('敏感区设置已修改，请先重新生成缓冲');
  const c=Object.fromEntries(['swath', 'height_offset', 'clearance', 'speed','wind_speed','wind_direction','wind_cost','lane_phase'].map(k => [k, Number($('job-' + k).value)])); c.transition_mode=$('job-transition_mode').value; return c;
}
function plannerMethod() { return $('job-algorithm').value; }
function plannerOptions() {
  const method = plannerMethod();
  if (method.startsWith('caw')) {
    return {step_xy:Number($('job-step_xy').value), order_strategy:$('job-order_strategy').value, objective:$('job-objective').value, max_expansions:200000, max_grid_nodes:2000000};
  }
  if (method === 'naive-target-order') return {transition:'straight'};
  return {};
}
function syncCawFields() {
  syncWindPreset();
  const caw = plannerMethod().startsWith('caw');
  if ($('job-caw-only')) $('job-caw-only').style.display = caw ? '' : 'none';
  if ($('job-caw-grid')) $('job-caw-grid').style.display = caw ? '' : 'none';
  if ($('job-objective')) {
    for (const option of $('job-objective').options) {
      if (option.value === 'energy') option.disabled = !caw;
    }
    if (!caw) $('job-objective').value = 'time';
  }
}
syncCawFields();
jobPanel.addEventListener('input', e => {
  if (e.target.id.startsWith('job-')) {
    if (e.target.id === 'job-algorithm') syncCawFields();
    invalidatePlan();
    draw();
  }
});
$('plan-visible').onchange = draw;
function syncWindPreset() {
 const a=Number($('job-wind_direction').value);
 const option=[...$('wind-preset').options].find(o=>o.value!=='custom'&&Math.abs(Number(o.value)-a)<1e-6);
 $('wind-preset').value=option?option.value:'custom';
}
$('wind-preset').onchange = async () => {
 if ($('wind-preset').value==='custom') return;
 $('job-wind_direction').value=$('wind-preset').value; invalidatePlan(); draw();
 if (scene?.wind_buffer) {try {await applyWindBuffer();}catch(e){$('buffer-status').textContent=e.message;}}
};
$('job-wind_direction').addEventListener('change',async()=>{syncWindPreset();if(scene?.wind_buffer){try{await applyWindBuffer();}catch(e){$('buffer-status').textContent=e.message;}}});
$('job-wind_speed').addEventListener('change',async()=>{if(scene?.wind_buffer){try{await applyWindBuffer();}catch(e){$('buffer-status').textContent=e.message;}}});
$('recover-coverage').onclick=async()=>{
 try {
  if(dirty) throw Error('请先生成场景');
  const reference=scene, config=jobConfig(), signature=JSON.stringify(config);
  $('recover-status').textContent='正在比较候选相位的合法覆盖、安全与时间…';
  const r=await api('/api/recover-coverage',{scene,config,resolution:Number($('evaluation-resolution').value)});
  if(scene!==reference||signature!==JSON.stringify(jobConfig()))return;
  $('recover-status').textContent=r.message;
  if(r.improved){$('job-lane_phase').value=r.recommended.phase;invalidatePlan();$('job-algorithm').value='caw-a*-3d-wind';$('job-order_strategy').value='nn+2opt';$('job-objective').value='time';$('job-step_xy').value='1';syncCawFields();$('plan-generate').click();}
 }catch(e){$('recover-status').textContent='恢复方案失败：'+e.message;}
};
const recoveryNames={'baseline':'原相位','global-phase':'整体平移','local-border':'局部边带'};
let recoveryRequest=0;
$('recover-options').onclick=async()=>{
 const token=++recoveryRequest, host=$('recovery-options');
 try {
  if(dirty)throw Error('请先生成场景');
  const reference=scene, config=jobConfig(), signature=JSON.stringify(config);
  const resolution=Number($('evaluation-resolution').value), budget=Number($('recovery-budget').value);
  const unchanged=()=>token===recoveryRequest&&scene===reference&&!dirty&&signature===JSON.stringify(jobConfig())&&resolution===Number($('evaluation-resolution').value)&&budget===Number($('recovery-budget').value);
  host.textContent='正在实际规划并比较覆盖、时间与保护约束…';
  const r=await api('/api/recover-coverage-options',{scene,config,resolution,time_budget:budget});
  if(!unchanged()){if(token===recoveryRequest)host.textContent='输入已改变，请重新比较';return;}
  host.replaceChildren();
  if(r.status!=='success'){host.textContent=r.message;return;}
  const note=document.createElement('p');note.textContent=`额外时间上限 ${budget} s；网格 ${resolution} m。推荐 ${recoveryNames[r.recommended]}。`;host.append(note);
  for(const row of r.alternatives){
   const p=document.createElement('p');
   p.textContent=`${recoveryNames[row.strategy]}：漏喷 ${row.extra_miss.toFixed(2)} m²；恢复 ${row.restored_area.toFixed(2)} m²；时间 ${row.duration.toFixed(2)} s（增加 ${row.added_seconds.toFixed(2)} s）；重复覆盖 ${row.repeated_area.toFixed(2)} m²·次；估算喷量 ${row.spray_amount.toFixed(2)}（模型量）；受限 ${row.restricted_area.toFixed(2)} m²；违规 ${row.illegal_count}。`;
   const button=document.createElement('button');button.textContent='应用并回放';
   button.onclick=async()=>{try{
    if(!unchanged())throw Error('输入已改变，请重新比较');
    const plan=await api('/api/plan-check',{scene,plan:row.plan});
    if(!unchanged())throw Error('检查期间输入已改变，请重新比较');
    invalidatePlan();$('job-lane_phase').value=plan.config.lane_phase;
    $('job-algorithm').value='caw-a*-3d-wind';$('job-order_strategy').value='nn+2opt';$('job-objective').value='time';$('job-step_xy').value='1';syncCawFields();
    currentPlan=plan;if(typeof prepareExecution==='function')await prepareExecution();
    $('plan-status').textContent=`已应用${recoveryNames[row.strategy]}，完整航线已通过安全复核；时间 ${row.duration.toFixed(2)} s，区外漏喷 ${row.extra_miss.toFixed(2)} m²。请到03查看最终覆盖；保存计划会保留补喷段。`;
    host.append(Object.assign(document.createElement('p'),{textContent:'已应用方案；再次选用其他方案请重新比较。'}));draw();
    ++recoveryRequest;
   }catch(e){$('plan-status').textContent=e.message;}};
   p.append(button);host.append(p);
  }
  host.append(Object.assign(document.createElement('p'),{textContent:r.note}));
  const save=document.createElement('button');save.textContent='保存恢复比较结果';
  save.onclick=()=>{if(!unchanged()){host.textContent='输入已改变，请重新比较后保存';return;}
   const url=URL.createObjectURL(new Blob([JSON.stringify(r,null,2)],{type:'application/json'}));
   const a=document.createElement('a');a.href=url;a.download='orchard.recovery-comparison.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };host.append(save);
 }catch(e){if(token===recoveryRequest)host.textContent='比较失败：'+e.message;}
};
$('plan-multi-sensitive-example').onclick=async()=>{
 if((sceneEdited||dirty)&&!confirm('样例会替换当前场景，继续？'))return;
 try{
  const result=await api('/api/generate',{rows:4,trees_per_row:5,row_spacing:4,plant_spacing:3});
  populate(result.scene.source.parameters);accept(result,'多敏感区密植样例');
  for(const [k,v] of Object.entries({swath:2,height_offset:2,clearance:.5,speed:2,wind_speed:2,wind_direction:Math.PI,wind_cost:.25,lane_phase:0,transition_mode:'fixed'}))$('job-'+k).value=v;
  $('job-algorithm').value='caw-a*-3d-wind';syncCawFields();
  const source=(id,x0,y0,x1,y1)=>({id,kind:'polygon_prism',footprint:{kind:'polygon',vertices:[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]},z_min:0,z_max:8});
  $('buffer-sources').value=JSON.stringify([source('sensitive-a',9.8,0,10.5,6.5),source('sensitive-b',14,7.5,14.7,16)],null,2);
  $('buffer-distance').value=1.3;await applyWindBuffer();setMode('top');
  $('plan-status').textContent='两个敏感区，行距4 m、株距3 m。缓冲1.3 m为演示输入。点击“比较整体平移与局部边带”，查看同一保护范围内的覆盖和时间取舍；不是实际密植果园验证。';
 }catch(e){$('plan-status').textContent='样例加载失败：'+e.message;}
};
async function loadRestrictionExample(kind) {
  if ((sceneEdited || dirty) && !confirm('当前场景有编辑，加载样例会替换当前几何。继续？')) return;
  const nofly = kind === 'no_fly_zones';
  const obstacle = kind === 'obstacles';
  const label = obstacle ? '障碍绕行' : nofly ? '禁飞验证' : '禁喷切段';
  try {
    const object = obstacle
      ? {id: 'obstacle-example', kind: 'box', min: [1.8,5.8,5.7], max: [2.2,7.2,6.7]}
      : {id: nofly ? 'no-fly-example' : 'no-spray-example', kind: 'polygon_prism',
          footprint: {kind: 'polygon', vertices: nofly
            ? [[0.5,12.5],[10.5,12.5],[10.5,20.5],[0.5,20.5]]
            : [[1.8,6.2],[3.2,6.2],[3.2,6.8],[1.8,6.8]]},
          z_min: 0, z_max: 8};
    const example = await api('/api/generate', {
      rows: 4, trees_per_row: 5,
      [kind]: [object]
    });
    populate(example.scene.source.parameters);
    accept(example, '已加载' + label + '样例');
    $('job-algorithm').value = 'caw-a*-3d-wind';
    for (const [key, value] of Object.entries({swath:2, height_offset:2, clearance:0.5, speed:2,
      wind_speed:0, wind_direction:0, wind_cost:0.25, lane_phase:0, transition_mode:'fixed'})) {
      $('job-' + key).value = value;
    }
    syncCawFields();
    setMode('top');
    if (obstacle) {
      $('plan-status').textContent = '样例已就绪：一个悬空障碍挡住喷洒高度。点击“生成航线”，查看切段、自动三维绕行与最终覆盖；切换“固定 Y”重新生成，应提示实际冲突。';
    } else {
      $('plan-status').textContent = nofly
        ? '样例已就绪：20 棵树，禁飞区覆盖其中一部分。点击“生成航线”，再点 03 面板“查看最终覆盖”，检查绕行、关喷与漏喷目标。'
        : '样例已就绪：一棵树的中间部分与禁喷区重叠。点击“生成航线”，回放时应先喷洒、关喷穿过该段、再恢复喷洒；查看最终覆盖中的额外漏喷面积。';
    }
  } catch (error) {
    $('plan-status').textContent = '样例加载失败：' + error.message;
  }
}
$('plan-nofly-example').onclick = () => loadRestrictionExample('no_fly_zones');
$('plan-nospray-example').onclick = () => loadRestrictionExample('no_spray_zones');
$('plan-obstacle-example').onclick = () => loadRestrictionExample('obstacles');
async function applyWindBuffer() {
  if (dirty) throw Error('请先生成场景，再应用缓冲');
  const reference = scene;
  const inputs = JSON.stringify([$ ('buffer-sources').value, $('buffer-distance').value, $('job-wind_speed').value, $('job-wind_direction').value]);
  const result = await api('/api/wind-buffer', {scene, sources:JSON.parse($('buffer-sources').value),
    distance:Number($('buffer-distance').value), wind_speed:Number($('job-wind_speed').value), wind_direction:Number($('job-wind_direction').value)});
  if (scene !== reference || inputs !== JSON.stringify([$ ('buffer-sources').value, $('buffer-distance').value, $('job-wind_speed').value, $('job-wind_direction').value])) return;
  accept(result, '已更新敏感区缓冲');
  sceneEdited = true;
  $('buffer-status').textContent = `已应用：风 ${result.report.wind_speed} m/s，来向 ${result.report.wind_direction.toFixed(3)} rad，实际扩展 ${result.report.effective_distance} m。黄色禁喷，红色原区；区内不喷，区外额外漏喷见 03。`;
}
$('buffer-apply').onclick = async () => {try {await applyWindBuffer();} catch(e) {$('buffer-status').textContent = e.message;}};
for (const id of ['buffer-sources','buffer-distance']) $(id).addEventListener('input', () => {invalidatePlan(); $('buffer-status').textContent='设置已修改，请重新生成缓冲。';});
$('plan-wind-example').onclick = async () => {
  if ((sceneEdited || dirty) && !confirm('加载侧风样例会替换当前几何。继续？')) return;
  try {
    const result = await api('/api/generate', {rows:4, trees_per_row:5});
    populate(result.scene.source.parameters); accept(result, '侧风样例');
    for (const [k,v] of Object.entries({swath:2,height_offset:2,clearance:.5,speed:2,wind_speed:2,wind_direction:Math.PI,wind_cost:.25,lane_phase:0,transition_mode:'fixed'})) $('job-'+k).value=v;
    $('job-algorithm').value='caw-a*-3d-wind'; syncCawFields();
    $('buffer-sources').value=JSON.stringify([{id:'sensitive-east',kind:'polygon_prism',footprint:{kind:'polygon',vertices:[[23,0],[24,0],[24,22],[23,22]]},z_min:0,z_max:8}],null,2);
    $('buffer-distance').value=3.5;
    await applyWindBuffer(); setMode('top');
    $('plan-status').textContent='西风向东：敏感区从 x=23 向西扩到 x=19.5，压到最后一排树冠。先以平移 0 生成并查看最终覆盖，再改平移 0.49 m 重跑，对比同一禁喷范围外的额外漏喷。距离 3.5 m 为演示假设。';
  } catch(e) {$('plan-status').textContent='侧风样例失败：'+e.message;}
};

$('plan-generate').onclick = async () => {
  if (typeof sceneEditorHasDraft === 'function' && sceneEditorHasDraft()) {
    const what = typeof sceneEditorDraftDescription === 'function' ? sceneEditorDraftDescription() : '多边形草稿';
    $('plan-status').textContent = `存在未闭合的${what}：请按 Enter/双击/点回首点闭合后再生成航线`;
    return;
  }
  invalidatePlan();
  draw();
  if (dirty) {
    $('plan-status').textContent = '场景参数尚未生成，请先生成场景';
    return;
  }
  try {
  const reference = scene,
    request = {scene, config: jobConfig(), method: plannerMethod(), options: plannerOptions()},
    values = JSON.stringify({config: request.config, method: request.method, options: request.options});
  $('plan-status').textContent = '正在生成航线并检查净空、喷洒足迹与任务结构…';
    const result = await api('/api/plan', request);
    if (reference !== scene || values !== JSON.stringify({config: jobConfig(), method: plannerMethod(), options: plannerOptions()}) || dirty) return;
    if (result.status !== 'success') throw Error((result.stage ? result.stage + '：' : '') + result.reason);
    currentPlan = result;
    if(typeof prepareExecution === "function") await prepareExecution();
    const planner = result.planner || result.method;
    const spray = result.segments.filter(s => s.spray).length;
    const zs = result.segments.map(s => s.start[2]).concat(result.segments.map(s => s.end[2]));
    const transitZ = result.segments.filter(s => s.type === 'transit').flatMap(s => [s.start[2], s.end[2]]);
    const zText = transitZ.length ? `转场高度 ${Math.min(...transitZ).toFixed(2)}–${Math.max(...transitZ).toFixed(2)} m` : '无转场';
    const search = result.search ? ` · ${result.search.model === 'layered-3d-clearance-a-star' ? '三维绕行' : '转场搜索'} · 搜索节点 ${result.search.expanded ?? result.search.nodes ?? '-'} · 网格 ${result.search.step_xy ?? result.search.step ?? '-'} m` : ' · 转场直线';
    const order = result.order ? ` · 顺序 [${result.order.join(', ')}]` : '';
    const orderSearch = result.order_search ? ` · 顺序策略 ${result.order_search.strategy}${result.order_search.matrix_mode ? ' · 矩阵 ' + result.order_search.matrix_mode : ''}${result.order_search.lower_bound != null ? ' · 相对下界 ' + result.order_search.lower_bound.toFixed(2) + ' s' : ''}` : '';
    const run = (typeof timeline !== 'undefined' && timeline) ? ` · 路径 ${timeline.segments.reduce((v, s) => v + s.length, 0).toFixed(2)} m · 时长 ${timeline.duration.toFixed(2)} s` : '';
    const wind = `风 ${result.config.wind_speed.toFixed(1)} m/s @ ${result.config.wind_direction.toFixed(2)} rad`;
    const objValue = result.objective_value == null ? '' : ` · 目标值 ${result.objective_value.toFixed(2)}${result.objective === 'energy' ? ' eu（代理）' : ' s'}`;
    const associated = new Set(result.segments.flatMap(s => s.target_ids || []));
    const skipped = scene.targets.filter(t => !associated.has(t.id));
    $('plan-status').textContent = `安全与任务结构通过 · ${planner} · v${result.version} · 目标 ${result.objective || 'time'}${objValue} · ${result.segments.length} 航段（喷洒 ${spray}）· 高度 ${result.work_height.toFixed(2)} m · ${zText}${search}${order}${orderSearch}${run} · ${wind} · 指纹 ${(result.plan_hash || '').slice(0,8) || '-'} / 配置 ${(result.config_hash || '').slice(0,8)}\n覆盖率为网格近似，见 03/04 面板；青色喷洒 / 橙色虚线转场`;
    if (scene.no_fly_zones.length || scene.no_spray_zones.length || scene.obstacles.length) {
      $('plan-status').textContent += `\n障碍及区域约束已处理 · ${skipped.length} 个目标没有合法喷洒关联，仍计入总漏喷。其余目标也可能只喷到一部分，请查看最终覆盖。`;
    }
  } catch (e) {
    $('plan-status').textContent = '规划失败：' + e.message;
  }
  draw();
};
$('plan-save').onclick = async () => {
  if (!currentPlan) {
    $('plan-status').textContent = '无有效计划可保存';
    return;
  }
  try {
    const result = await api('/api/plan-check', {
      scene,
      plan: currentPlan
    });
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], {
      type: 'application/json'
    }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'orchard.plan.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    invalidatePlan();
    $('plan-status').textContent = e.message;
    draw();
  }
};
$('plan-load').onclick = () => $('plan-file').click();
$('plan-file').onchange = async () => {
  invalidatePlan();
  draw();
  try {
    const candidate = JSON.parse(await $('plan-file').files[0].text());
    const reference = scene;
    const result = await api('/api/plan-check', {
      scene,
      plan: candidate
    });
    if (reference !== scene || dirty) throw Error('场景已变化');
    for (const [k, v] of Object.entries(result.config)) {
      const field = $('job-' + k);
      if (field) field.value = v;
    }
    if (result.planner || result.method) {
      const name = result.planner || result.method;
      if ([...$('job-algorithm').options].some(o => o.value === name)) $('job-algorithm').value = name;
    }
    if (result.planner_options) {
      if (result.planner_options.step_xy != null) $('job-step_xy').value = String(result.planner_options.step_xy);
      if (result.planner_options.order_strategy) $('job-order_strategy').value = result.planner_options.order_strategy;
    }
    syncCawFields();
    currentPlan = result;
    if(typeof prepareExecution === "function") await prepareExecution();
    $('plan-status').textContent = '已加载匹配计划：安全与任务结构通过，覆盖率未验证';
  } catch (e) {
    $('plan-status').textContent = '加载失败：' + e.message;
  }
  $('plan-file').value = '';
  draw();
};

function drawPlan() {
  if (typeof multiPlaybackActive === "function" && multiPlaybackActive()) return;
  if (!currentPlan || !$('plan-visible').checked) return;
  for (const segment of currentPlan.segments) {
    const color = segment.spray ? '#41e6ed' : segment.type === 'transit' ? '#ffa34e' : '#d6b0ff';
    path([segment.start, segment.end], color, 2, null, segment.spray ? [] : [5, 4]);
    const a = project(segment.start),
      b = project(segment.end),
      dx = b[0] - a[0],
      dy = b[1] - a[1],
      length = Math.hypot(dx, dy);
    if (length > 8) {
      const x = (a[0] + b[0]) / 2,
        y = (a[1] + b[1]) / 2;
      ctx.beginPath();
      ctx.moveTo(x, y);
      ctx.lineTo(x - 6 * dx / length + 3 * dy / length, y - 6 * dy / length - 3 * dx / length);
      ctx.lineTo(x - 6 * dx / length - 3 * dy / length, y - 6 * dy / length + 3 * dx / length);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
    }
    if (segment.type === 'takeoff') label('起飞 / 返回降落', segment.end, color);
  }
}

// Minimal host surface for the optional editor script (web/editor.js).
window.sceneEditorHost = {
  getScene: () => scene,
  setScene: s => {
    scene = s;
  },
  getView: () => lastView,
  project: p => project(p),
  redraw: () => draw(),
  fit: () => {
    fit();
    draw();
  },
  focus: (point, zoomLevel = 2) => {
    if (!scene) return;
    center[0] = point[0];
    center[1] = point[1];
    zoom = zoomLevel;
    pan = [0, 0];
    draw();
  },
  setMode: m => setMode(m),
  getMode: () => mode,
  invalidatePlan: () => invalidatePlan(),
  api: (path, data) => api(path, data),
  status: (text, type) => status(text, type),
  markSceneEdited: () => {
    sceneEdited = true;
    if ($('buffer-sources')) {
      $('buffer-sources').value=JSON.stringify(scene.wind_buffer?.sources||[],null,2);
      if(scene.wind_buffer)$('buffer-distance').value=scene.wind_buffer.distance;
    }
  },
  isSceneEdited: () => sceneEdited,
  clearSceneEdited: () => {
    sceneEdited = false;
  },
  getConfig: () => config,
  setConfig: c => {
    config = c;
  },
  accept: (d, label) => accept(d, label),
  terrainHeight: () => (scene ? scene.terrain.height : 0),
  isDirty: () => dirty
};
window.addEventListener('beforeunload', event => {
  if ((typeof dirty !== 'undefined' && dirty) || (typeof currentPlan !== 'undefined' && currentPlan)) {
    event.preventDefault();
    event.returnValue = '';
  }
});
