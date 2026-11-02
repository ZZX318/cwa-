'use strict';
const $ = id => document.getElementById(id),
  canvas = $('view'),
  ctx = canvas.getContext('2d');
let scene = null,
  config = null,
  dirty = false,
  mode = 'iso',
  yaw = -0.62,
  pitch = .67,
  zoom = 1,
  pan = [0, 0],
  scale = 1,
  center = [0, 0, 0],
  drag = null,
  panMode = false;
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
  fit();
  let s = d.summary;
  $('sceneTitle').textContent = `${s.trees} 棵 · 果园场景`;
  $('sceneInfo').textContent = `地块 ${s.plot_size.map(x=>x.toFixed(1)).join(' × ')} m  /  目标 ${s.targets} 个`;
  status(`${label} · ${s.trees} 棵树\n障碍 ${s.obstacles} / 禁飞 ${s.no_fly_zones} / 禁喷 ${s.no_spray_zones}` + (s.warnings.length ? '\n' + s.warnings.join('\n') : ''));
  draw();
}
$('config').onsubmit = async e => {
  e.preventDefault();
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
      label('H · 起降点', [...p.position.slice(0, 2), z + .1], '#77e0f0')
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
  if(typeof drawAircraft === "function") drawAircraft();
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
  canvas.setPointerCapture(e.pointerId);
  drag = {
    x: e.clientX,
    y: e.clientY,
    pan: panMode || e.button !== 0 || e.shiftKey
  };
};
canvas.onpointermove = e => {
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
canvas.onpointerup = canvas.onpointercancel = () => drag = null;
canvas.onwheel = e => {
  e.preventDefault();
  zoom = Math.max(.2, Math.min(8, zoom * Math.exp(-e.deltaY * .001)));
  draw()
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
jobPanel.innerHTML = `<h3>单机作业计划</h3><p>几何喷幅模型 · 非执行结果</p>
<label class="field">有效喷幅 m<input id="job-swath" type="number" value="2" step="0.1"></label>
<label class="field">冠顶高度差 m<input id="job-height_offset" type="number" value="2" step="0.1"></label>
<label class="field">安全净空 m<input id="job-clearance" type="number" value="0.5" step="0.1"></label>
<label class="field">目标速度 m/s<input id="job-speed" type="number" value="2" step="0.1"></label>
<label class="field">风速 m/s<input id="job-wind_speed" type="number" value="0" min="0" step="0.1"></label>
<label class="field">风向 rad<input id="job-wind_direction" type="number" value="0" step="0.1"></label>
<label class="field">风向代价<input id="job-wind_cost" type="number" value="0.25" min="0.01" step="0.05"></label>
<label class="field">转场模式<select id="job-transition_mode"><option value="fixed">固定直线</option><option value="search">净空搜索</option></select></label>
<button id="plan-generate">生成航线</button><button id="plan-save">保存计划</button><button id="plan-load">加载计划</button>
<input id="plan-file" type="file" hidden><label><input id="plan-visible" type="checkbox" checked>航线</label><p id="plan-status">尚未生成计划</p>`;
document.querySelector('aside').append(jobPanel);

function invalidatePlan() {
  if(typeof resetExecution === "function") resetExecution();
  currentPlan = null;
  if ($('plan-status')) $('plan-status').textContent = '计划已失效，请重新生成';
  if (scene) draw();
}

function jobConfig() {
  const c=Object.fromEntries(['swath', 'height_offset', 'clearance', 'speed','wind_speed','wind_direction','wind_cost'].map(k => [k, Number($('job-' + k).value)])); c.transition_mode=$('job-transition_mode').value; return c;
}
jobPanel.addEventListener('input', e => {
  if (e.target.id.startsWith('job-')) {
    invalidatePlan();
    draw();
  }
});
$('plan-visible').onchange = draw;
$('plan-generate').onclick = async () => {
  invalidatePlan();
  draw();
  if (dirty) {
    $('plan-status').textContent = '场景参数尚未生成，请先生成场景';
    return;
  }
  const reference = scene,
    values = JSON.stringify(jobConfig());
  try {
    const result = await api('/api/plan', {
      scene,
      config: jobConfig()
    });
    if (reference !== scene || values !== JSON.stringify(jobConfig()) || dirty) return;
    if (result.status !== 'success') throw Error(result.reason);
    currentPlan = result;
    if(typeof prepareExecution === "function") await prepareExecution();
    const mode = result.config.transition_mode === 'search' ? '净空搜索' : '固定直线';
    $('plan-status').textContent = `安全与任务结构通过 · ${mode} · ${result.strip_count} 带 · ${result.segments.length} 航段 · 高度 ${result.work_height.toFixed(2)} m；覆盖率未验证。青色喷洒 / 橙色虚线转场`;
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
