'use strict';
// Local playback for multi-UAV / joint results.  Every position comes from a
// timeline built by the Python executor; this file only interpolates between
// the segment endpoints with the same piecewise-constant-speed rule.
const dynamicCanvas = document.createElement('canvas');
dynamicCanvas.id = 'dynamic-layer';
dynamicCanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1;';
canvas.parentElement.insertBefore(dynamicCanvas, canvas.nextSibling);
const dctx = dynamicCanvas.getContext('2d');

function resizeDynamic() {
  const dpr = window.devicePixelRatio || 1;
  dynamicCanvas.width = canvas.clientWidth * dpr;
  dynamicCanvas.height = canvas.clientHeight * dpr;
  dctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', () => { resizeDynamic(); drawDynamic(); });
if (typeof ResizeObserver !== 'undefined') {
  new ResizeObserver(() => {
    resizeDynamic();
    if (typeof draw === 'function' && typeof scene !== 'undefined' && scene) draw();
  }).observe(canvas);
}
resizeDynamic();

function clearDynamic() {
  dctx.clearRect(0, 0, dynamicCanvas.width, dynamicCanvas.height);
}

function layerPath(points, color, width = 1, fill = null, dash = []) {
  if (!points || !points.length) return;
  dctx.beginPath();
  let a = project(points[0]);
  dctx.moveTo(...a);
  for (const p of points.slice(1)) dctx.lineTo(...project(p));
  if (fill) { dctx.closePath(); dctx.fillStyle = fill; dctx.fill(); }
  dctx.strokeStyle = color;
  dctx.lineWidth = width;
  dctx.setLineDash(dash);
  dctx.stroke();
  dctx.setLineDash([]);
}

const STATUS_LABELS = {takeoff:'起飞', transit:'转场', spray:'喷洒', landing:'降落', completed:'落地完成', 'ground-hold':'地面等待'};

function trackState(track, time) {
  const segments = track.segments || [];
  const duration = Number(track.duration) || 0;
  const numeric = Number(time);
  const t = Math.max(0, Math.min(duration, Number.isFinite(numeric) ? numeric : 0));
  const home = track.home || [0, 0, 0];
  if (!segments.length) return {time:t, position:home.slice(), segment_index:0, status:'completed', spray:false, speed:0, heading:0};
  const first = segments[0];
  if (t < first.t_start) return {time:t, position:first.start.slice(), segment_index:0, status:'ground-hold', spray:false, speed:0, heading:first.heading || 0};
  if (t === first.t_start) return {time:t, position:first.start.slice(), segment_index:0, status:first.type, spray:!!first.spray, speed:first.speed, heading:first.heading || 0};
  let index = segments.length - 1;
  for (let i = 0; i < segments.length; i++) if (t < segments[i].t_end) { index = i; break; }
  const segment = segments[index];
  if (t >= duration) return {time:t, position:segment.end.slice(), segment_index:index, status:'completed', spray:false, speed:0, heading:segment.heading || 0};
  const fraction = (t - segment.t_start) / (segment.t_end - segment.t_start);
  return {
    time:t,
    position:segment.start.map((v, k) => v + (segment.end[k] - v) * fraction),
    segment_index:index,
    status:segment.type,
    spray:!!segment.spray,
    speed:segment.speed,
    heading:segment.heading || 0
  };
}

function drawDrone(state, color, label) {
  if (!state.position || state.position.length < 3) return;
  const position = state.position;
  const heading = state.heading || 0;
  const size = 17 / Math.max(scale, 0.001), c = Math.cos(heading), s = Math.sin(heading);
  const world = (x, y) => [position[0] + size * (x * c - y * s), position[1] + size * (x * s + y * c), position[2]];
  for (const [x, y] of [[-.6, -.6], [-.6, .6], [.6, -.6], [.6, .6]]) {
    layerPath([position, world(x, y)], color, 2);
    const ring = Array.from({length:25}, (_, i) => world(x + .34 * Math.cos(i * Math.PI / 12), y + .34 * Math.sin(i * Math.PI / 12)));
    layerPath(ring, color, 1.6, '#112b3c');
  }
  layerPath([world(.95, 0), world(-.35, .3), world(-.35, -.3), world(.95, 0)], color, 1.5, color);
  const p = project(position);
  dctx.font = '11px -apple-system, sans-serif';
  dctx.fillStyle = color;
  dctx.fillText(label, p[0] + 8, p[1] - 8);
}

function drawDynamic() {
  const dpr = window.devicePixelRatio || 1;
  if (dynamicCanvas.width !== canvas.clientWidth * dpr || dynamicCanvas.height !== canvas.clientHeight * dpr) resizeDynamic();
  clearDynamic();
  if (MultiPlayback.active) {
    for (const track of MultiPlayback.active.tracks) {
      drawDrone(trackState(track, MultiPlayback.active.time), track.color, track.label);
    }
    return;
  }
  if (typeof executionState !== 'undefined' && executionState) {
    drawDrone(executionState, executionState.spray ? '#4ff4e5' : '#f2f6fa', 'UAV');
  }
}

function drawPlaybackPaths() {
  if (!MultiPlayback.active) return;
  for (const track of MultiPlayback.active.tracks) {
    for (const segment of track.segments || []) {
      path([segment.start, segment.end], track.color, segment.spray ? 2.5 : 1.5, null, segment.spray ? [] : [4, 3]);
    }
  }
}

function multiPlaybackActive() { return !!MultiPlayback.active; }

const MultiPlayback = {
  active: null,
  lastDom: 0,

  load(owner, tracks, options = {}) {
    this.clear();
    const duration = Math.max(0, ...tracks.map(track => Number(track.duration) || 0));
    this.active = {
      owner,
      tracks,
      duration,
      time: 0,
      playing: false,
      rate: 1,
      startWall: 0,
      startTime: 0,
      raf: 0,
      controls: options.controls || {},
      title: options.title || ''
    };
    if (typeof playing !== 'undefined') playing = false;
    const controls = this.active.controls;
    for (const id of [controls.timeId, controls.seekId, controls.playId, controls.pauseId, controls.resetId]) {
      if (id && $(id)) $(id).disabled = false;
    }
    if (controls.timeId && $(controls.timeId)) { $(controls.timeId).max = duration; $(controls.timeId).value = 0; }
    if (controls.seekId && $(controls.seekId)) { $(controls.seekId).max = duration; $(controls.seekId).value = 0; }
    if (controls.rateId && $(controls.rateId)) { $(controls.rateId).disabled = false; $(controls.rateId).value = '1'; }
    this.syncButtons();
    this.render(true);
    draw();
    return this.active;
  },

  syncButtons() {
    if (!this.active) return;
    const c = this.active.controls;
    if (c.playId && $(c.playId)) $(c.playId).disabled = this.active.playing;
    if (c.pauseId && $(c.pauseId)) $(c.pauseId).disabled = !this.active.playing;
    if (c.resetId && $(c.resetId)) $(c.resetId).disabled = false;
  },

  clear() {
    if (!this.active) { clearDynamic(); return; }
    cancelAnimationFrame(this.active.raf);
    const controls = this.active.controls;
    this.active = null;
    for (const id of [controls.timeId, controls.seekId, controls.playId, controls.pauseId, controls.resetId, controls.rateId]) {
      if (id && $(id)) $(id).disabled = true;
    }
    clearDynamic();
    if (typeof draw === 'function' && typeof scene !== 'undefined' && scene) draw();
  },

  play() {
    if (!this.active) return;
    if (this.active.duration <= 0) return;
    if (this.active.time >= this.active.duration) this.active.time = 0;
    this.active.playing = true;
    this.active.startTime = this.active.time;
    this.active.startWall = performance.now();
    this.syncButtons();
    this.loop();
  },

  pause(silent = false) {
    if (!this.active) return;
    cancelAnimationFrame(this.active.raf);
    this.active.playing = false;
    this.syncButtons();
    if (!silent) this.render(true);
  },

  reset() {
    if (!this.active) return;
    cancelAnimationFrame(this.active.raf);
    this.active.time = 0;
    this.active.playing = false;
    this.syncButtons();
    this.render(true);
  },

  seek(time) {
    if (!this.active) return;
    cancelAnimationFrame(this.active.raf);
    this.active.time = Math.max(0, Math.min(this.active.duration, Number(time) || 0));
    this.active.playing = false;
    this.syncButtons();
    this.render(true);
  },

  setRate(rate) {
    if (!this.active) return;
    if (this.active.playing) {
      this.active.startTime = this.active.time;
      this.active.startWall = performance.now();
    }
    this.active.rate = Number(rate) || 1;
    if (this.active.controls.infoId) this.render(true);
  },

  loop() {
    if (!this.active || !this.active.playing) return;
    const now = performance.now();
    const time = Math.min(this.active.duration, this.active.startTime + (now - this.active.startWall) / 1000 * this.active.rate);
    this.active.time = time;
    this.render(false);
    if (time >= this.active.duration) {
      this.active.playing = false;
      this.syncButtons();
      this.render(true);
      return;
    }
    this.active.raf = requestAnimationFrame(() => this.loop());
  },

  render(force) {
    if (!this.active) return;
    drawDynamic();
    const now = performance.now();
    if (!force && now - this.lastDom < 100) return;
    this.lastDom = now;
    const c = this.active.controls;
    if (c.timeId && $(c.timeId)) $(c.timeId).value = this.active.time.toFixed(2);
    if (c.seekId && $(c.seekId)) $(c.seekId).value = this.active.time;
    const states = this.active.tracks.map(track => {
      const state = trackState(track, this.active.time);
      return `${track.label} · ${STATUS_LABELS[state.status] || state.status} · 航段 ${state.segment_index + 1} · 喷洒${state.spray ? '开' : '关'} · 位置 [${state.position.map(v => v.toFixed(2)).join(', ')}] m`;
    }).join('\n');
    if (c.statesId && $(c.statesId)) $(c.statesId).textContent = states;
    if (c.infoId && $(c.infoId)) {
      $(c.infoId).textContent = `${this.active.title} · ${this.active.time.toFixed(2)} / ${this.active.duration.toFixed(2)} s · ${this.active.playing ? '播放' : '暂停'} · ${this.active.rate}×`;
    }
  }
};

document.addEventListener('visibilitychange', () => {
  if (document.hidden && MultiPlayback.active && MultiPlayback.active.playing) {
    MultiPlayback.pause();
    if (MultiPlayback.active && MultiPlayback.active.controls.infoId && $(MultiPlayback.active.controls.infoId)) {
      $(MultiPlayback.active.controls.infoId).textContent += ' · 页面隐藏，已暂停';
    }
  }
});
