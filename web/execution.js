'use strict';
// Browser owns only the playback clock. All physical state is queried from Python.
let timeline = null, executionState = null, evaluationState = null, playing = false;
let playTime = 0, clockStart = 0, modelStart = 0, playbackRate = 1, requestVersion = 0;
let lastDomUpdate = 0, evaluationTimer = 0;
const STATUS_NAMES = {takeoff:'起飞',transit:'转场',spray:'喷洒',landing:'降落',completed:'落地完成','ground-hold':'地面等待'};

function statusName(type) { return STATUS_NAMES[type] || type; }

// Local mirror of execution.state_at: piecewise constant speed, exact boundaries.
function localStateAt(reference, time) {
  const segments = reference.segments;
  const numeric = Number(time);
  const t = Math.max(0, Math.min(reference.duration, Number.isFinite(numeric) ? numeric : 0));
  if (!segments.length) return {time:t, position:[], segment_index:0, segment_type:'completed', status:'completed', spray:false, speed:0, heading:0};
  if (t < segments[0].t_start) return {time:t, position:segments[0].start.slice(), segment_index:0, segment_type:'ground-hold', status:'ground-hold', spray:false, speed:0, heading:segments[0].heading || 0};
  if (t === segments[0].t_start) return {time:t, position:segments[0].start.slice(), segment_index:0, segment_type:segments[0].type, status:segments[0].type, spray:!!segments[0].spray, speed:segments[0].speed, heading:segments[0].heading || 0};
  let index = segments.length - 1;
  for (let i = 0; i < segments.length; i++) if (t < segments[i].t_end) { index = i; break; }
  const segment = segments[index];
  if (t >= reference.duration) return {time:t, position:segment.end.slice(), segment_index:index, segment_type:segment.type, status:'completed', spray:false, speed:0, heading:segment.heading || 0};
  const fraction = (t - segment.t_start) / (segment.t_end - segment.t_start);
  return {time:t, position:segment.start.map((v,k)=>v+(segment.end[k]-v)*fraction), segment_index:index, segment_type:segment.type, status:segment.type, spray:!!segment.spray, speed:segment.speed, heading:segment.heading || 0};
}

function updateExecutionDom(state, force) {
  const now = performance.now();
  if (!force && now - lastDomUpdate < 100) return;
  lastDomUpdate = now;
  $('execution-seek').value = state.time;
  $('execution-time').value = state.time.toFixed(2);
  const z = state.position[2] ?? 0, maxZ = timeline.maxZ ?? z;
  $('execution-info').textContent = `${state.time.toFixed(2)} / ${timeline.duration.toFixed(2)} s · ${statusName(state.status)}\n航段 ${state.segment_index+1} · 喷洒${state.spray?'开':'关'} · 模型速度 ${state.speed.toFixed(2)} m/s\n位置 [${state.position.map(v=>v.toFixed(2)).join(', ')}] m · 高度 ${z.toFixed(2)} / 最高 ${maxZ.toFixed(2)} m`;
}

async function updateEvaluation(time) {
  if (!timeline || !currentPlan) return;
  const reference = timeline;
  try {
    const ev = await api('/api/evaluation',{scene,plan:currentPlan,timeline,time});
    if (reference !== timeline) return;
    evaluationState = ev;
    const stat = ev.evaluation || ev;
    const missed = ev.missed_targets ?? stat.missed_targets ?? [];
    const repeated = ev.repeated_targets ?? stat.repeated_targets ?? [];
    $('evaluation-info').textContent = `目标覆盖 ${(ev.coverage*100).toFixed(1)}% · 漏喷目标 ${missed.length} · 重复目标 ${repeated.length} · 喷洒 ${ev.spray_seconds.toFixed(2)} s · 估算量 ${(ev.total_spray_amount??stat.total_spray_amount??0).toFixed(2)}（网格近似）`;
    draw();
  } catch (error) {
    if (reference === timeline) $('evaluation-info').textContent = '覆盖评价失败：' + error.message;
  }
}
const aside = document.querySelector('aside');
const sceneGroup = document.createElement('details');
sceneGroup.innerHTML = '<summary>01 · 场景与图层</summary>';
for (const child of [...aside.children]) if(child !== jobPanel) sceneGroup.append(child);
aside.prepend(sceneGroup);
const jobGroup = document.createElement('details');
jobGroup.innerHTML = '<summary>02 · 单机作业计划</summary>';
jobGroup.append(jobPanel); aside.append(jobGroup); jobGroup.open = true;
const playbackGroup = document.createElement('details');
playbackGroup.open = true;
playbackGroup.innerHTML = `<summary>03 · 时间模型与回放</summary>
<p>分段恒速运动学 · 非真实动力学</p>
<button id="execution-prepare">准备回放</button><button id="execution-play" disabled>播放</button>
<button id="execution-pause" disabled>暂停</button><button id="execution-reset" disabled>重置</button>
<label>倍速 <select id="execution-rate"><option value="0.5">0.5×</option><option selected value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label>
<label>仿真时间 s<input id="execution-seek" type="range" min="0" max="0" step="any" value="0" disabled></label>
<label class="field">定位时间 s<input id="execution-time" type="number" step="0.1" value="0" disabled></label>
<button id="execution-save" disabled>保存时间模型</button>
<p id="execution-info" role="status">无有效时间模型</p><p id="evaluation-info">覆盖评价未运行</p><label><input id="coverage-visible" type="checkbox" checked>覆盖图层（网格近似）</label><small>图标尺寸仅供辨识，不表示机体物理尺寸。+X 为初始机头方向。</small>`;
aside.append(playbackGroup);

function playbackButtons(enabled) {
  for(const id of ['execution-play','execution-pause','execution-reset','execution-seek','execution-time','execution-save']) $(id).disabled = !enabled;
}
function resetExecution() {
  requestVersion++; clearTimeout(evaluationTimer); playing = false; timeline = null; executionState = null; evaluationState = null; playTime = 0;
  playbackButtons(false); $('execution-seek').value = '0'; $('execution-time').value = '0';
  $('execution-info').textContent = '回放已失效：请先生成有效计划';
  $('evaluation-info').textContent = '覆盖评价未运行';
  if (typeof clearDynamic === 'function') clearDynamic();
}
async function prepareExecution() {
  resetExecution();
  if(typeof MultiPlayback !== 'undefined') MultiPlayback.clear();
  if(!currentPlan || dirty) return;
  const version = requestVersion, reference = currentPlan;
  try {
    const result = await api('/api/execution',{scene,plan:reference});
    if(version !== requestVersion || reference !== currentPlan) return;
    result.maxZ = Math.max(0, ...result.segments.flatMap(s => [s.start[2], s.end[2]]));
    timeline = result; $('execution-seek').max = result.duration; $('execution-time').max = result.duration;
    playbackButtons(true); await queryTime(0, true);
  } catch(error) { if(version === requestVersion) $('execution-info').textContent = error.message; }
}
function desiredTime() {
  return Math.min(timeline.duration, modelStart + (performance.now()-clockStart)/1000*playbackRate);
}
async function queryTime(time, evaluate = false) {
  if(!timeline) return;
  const state = localStateAt(timeline, time);
  executionState = state; playTime = state.time;
  if(state.status === 'completed') playing = false;
  updateExecutionDom(state, state.status === 'completed' || !playing || evaluate);
  if(typeof drawDynamic === 'function') drawDynamic();
  if(evaluate){
    clearTimeout(evaluationTimer);
    evaluationTimer = setTimeout(() => updateEvaluation(state.time), 120);
  }
}
async function animate() {
  if(!playing || !timeline) return;
  await queryTime(desiredTime());
  if(playing) requestAnimationFrame(animate);
}
document.addEventListener('visibilitychange', () => {
  if(document.hidden && playing && timeline){
    const time = desiredTime();
    playing = false;
    playTime = time;
    executionState = localStateAt(timeline, time);
    updateExecutionDom(executionState, true);
    if(typeof drawDynamic === 'function') drawDynamic();
    $('execution-info').textContent += ' · 页面隐藏，已暂停';
  }
});
$('execution-prepare').onclick = prepareExecution;
$('execution-play').onclick = () => {
  if(!timeline || playing) return;
  if(typeof MultiPlayback !== 'undefined') MultiPlayback.clear();
  if(playTime >= timeline.duration) playTime = 0;
  playing = true; modelStart = playTime; clockStart = performance.now(); requestAnimationFrame(animate);
};
$('execution-pause').onclick = () => {
  if(!timeline) return;
  const time = playing ? desiredTime() : playTime;
  playing = false; queryTime(time, true);
};
$('execution-reset').onclick = () => {playing = false; if(timeline) queryTime(0, true);};
function handleSeekInput(event) {
  if(!timeline) return;
  playing = false;
  const value=Math.max(0,Math.min(timeline.duration,Number(event.target.value)));
  $('execution-seek').value=value; $('execution-time').value=value;
  queryTime(value, true);
}
$('execution-seek').oninput = handleSeekInput;
$('execution-seek').onchange = handleSeekInput;
$('execution-time').onchange = () => {playing = false; queryTime(Number($('execution-time').value), true);};
$('execution-time').oninput = () => {playing = false; queryTime(Number($('execution-time').value), true);};
$('execution-rate').onchange = () => {
  if(playing){modelStart=desiredTime();clockStart=performance.now();}
  playbackRate=Number($('execution-rate').value);
};
$('execution-save').onclick = () => {
  if(!timeline) return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(timeline,null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='orchard.execution.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};

function drawCoverage() {
  if(!evaluationState || !$('coverage-visible').checked) return;
  const ev=evaluationState,e=ev.evaluation;
  for(const cell of e.cells){const [tid,ix,iy]=cell;const hit=ev.coverage_cells.some(x=>x[0]===tid&&x[1]===ix&&x[2]===iy);if(!hit)continue;const x=(ix+.5)*e.resolution,y=(iy+.5)*e.resolution;const a=project([x-e.resolution/2,y-e.resolution/2,scene.terrain.height+.03]),b=project([x+e.resolution/2,y-e.resolution/2,scene.terrain.height+.03]),c=project([x+e.resolution/2,y+e.resolution/2,scene.terrain.height+.03]),d=project([x-e.resolution/2,y+e.resolution/2,scene.terrain.height+.03]);ctx.fillStyle='#38c88866';ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.lineTo(...c);ctx.lineTo(...d);ctx.closePath();ctx.fill();}
}
function drawAircraft() {
  if(!executionState) return;
  const position=executionState.position, heading=executionState.heading;
  // Fixed screen-size symbol placed/oriented in the horizontal world plane.
  const size=17/Math.max(scale,0.001), c=Math.cos(heading),s=Math.sin(heading);
  const world=(x,y)=>[position[0]+size*(x*c-y*s),position[1]+size*(x*s+y*c),position[2]];
  const color=executionState.spray?'#4ff4e5':'#f2f6fa';
  for(const [x,y] of [[-.6,-.6],[-.6,.6],[.6,-.6],[.6,.6]]) {
    path([position,world(x,y)],color,2);
    const ring=Array.from({length:25},(_,i)=>world(x+.34*Math.cos(i*Math.PI/12),y+.34*Math.sin(i*Math.PI/12)));
    path(ring,color,1.6,'#112b3c');
  }
  path([world(.95,0),world(-.35,.3),world(-.35,-.3),world(.95,0)],color,1.5,color);
}

const comparisonGroup=document.createElement('details');comparisonGroup.innerHTML=`<summary>04 · 真实算法对照</summary><label>方法 <select id="compare-method"><option value="all">三种（fixed-y / naive / caw）</option><option value="both">fixed-y + naive（旧 both）</option><option value="fixed-y-boustrophedon">fixed-y</option><option value="naive-target-order">naive</option><option value="caw-a*-3d-wind">caw-a*</option></select></label><button id="compare-run">运行比较</button><p id="compare-info">同一场景、配置、执行器与评价器；安全列为独立检查结果</p><div id="compare-table"></div>`;aside.append(comparisonGroup);
let comparison=null;
function clearComparison(){comparison=null;if($('compare-info'))$('compare-info').textContent='比较结果已失效，请重新运行';if($('compare-table'))$('compare-table').innerHTML='';}
const oldInvalidate=invalidatePlan;invalidatePlan=function(){oldInvalidate();clearComparison();};
const cell=(v,d=2)=>v==null?'-':Number(v).toFixed(d);
$('compare-run').onclick=async()=>{if(dirty){$('compare-info').textContent='场景参数尚未生成';return;}try{
  comparison=await api('/api/compare',{scene,config:jobConfig(),method:$('compare-method').value,resolution:.5});
  const rows=comparison.results;
  const same=(a,b)=>a&&b&&a.status==='success'&&b.status==='success'&&a.path_length===b.path_length&&a.duration===b.duration&&a.coverage===b.coverage;
  const fx=rows.find(r=>r.method==='fixed-y-boustrophedon'),nv=rows.find(r=>r.method==='naive-target-order');
  $('compare-info').textContent='网格近似评价；结果不代表实测作物效果或普遍算法优劣'+(same(fx,nv)?' · 警告：fixed-y 与 naive 数值相同，疑似同一计划':'');
  $('compare-table').innerHTML='<table><thead><tr><th>方法</th><th>状态/原因</th><th>版本</th><th>路径 m</th><th>转场 m</th><th>时间 s</th><th>喷洒 s</th><th>覆盖率</th><th>漏喷目标</th><th>重复目标</th><th>安全</th><th>搜索节点</th><th>顺序/矩阵</th></tr></thead><tbody>'+rows.map(r=>{
    const status=r.status==='success'?'成功':`失败 [${r.stage||'-'}]：${r.reason||''}`;
    const safety=r.status==='success'?'pass':(r.safety==='failed'?'failed':r.safety||'not_run');
    return `<tr><td>${r.method}</td><td>${status}</td><td>${r.plan_version||'-'}</td><td>${cell(r.path_length)}</td><td>${cell(r.transition_length)}</td><td>${cell(r.duration)}</td><td>${cell(r.spray_seconds)}</td><td>${r.coverage==null?'-':(r.coverage*100).toFixed(1)+'%'}</td><td>${r.missed_targets??'-'}</td><td>${r.repeated_targets??'-'}</td><td>${safety}</td><td>${r.search_nodes??'-'}</td><td>${r.order?'['+r.order.join(',')+']':'无顺序'}${r.matrix_mode?' · '+r.matrix_mode:''}${r.lower_bound!=null?' · LB '+r.lower_bound.toFixed(2):''}</td></tr>`;
  }).join('')+'</tbody></table>';
}catch(e){$('compare-info').textContent='比较失败：'+e.message;}}

const multiGroup=document.createElement('details');multiGroup.innerHTML=`<summary>05 · 多机协同</summary>
<label>无人机数量 <input id="multi-uavs" type="number" min="1" max="32" value="2"></label>
<label>多机算法 <select id="multi-algorithm"><option value="fixed-y">fixed-y 连续分块（默认）</option><option value="caw">caw 三维净空联合</option></select></label>
<label>最小机间距 m <input id="coord-min-distance" type="number" min="0.1" step="0.1" value="1"></label>
<label>最大地面等待 s <input id="coord-max-delay" type="number" min="0" step="1" value="120"></label>
<button id="multi-run">生成多机基线</button><button id="coord-run">协调（连续时间）</button>
<p id="multi-info">连续作业带分块；结果仅为规划与网格评价</p>
<p id="coord-info" style="white-space: pre-line">连续时间 CPA · 地面等待/错时 · 只有 conflicts_after=0 才算成功</p>
<div id="multi-table"></div><div id="coord-table"></div>
<label>回放来源 <select id="multi-playback-source"><option value="baseline">多机基线</option><option value="coord">协调结果</option></select></label>
<button id="multi-playback-prepare">准备回放</button>
<button id="multi-playback-play" disabled>播放</button><button id="multi-playback-pause" disabled>暂停</button><button id="multi-playback-reset" disabled>重置</button>
<label>倍速 <select id="multi-playback-rate" disabled><option value="0.5">0.5×</option><option selected value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label>
<label>回放时间 s<input id="multi-playback-time" type="number" step="0.1" value="0" disabled></label>
<input id="multi-playback-seek" type="range" min="0" max="0" step="any" value="0" disabled>
<p id="multi-playback-info" style="white-space: pre-line">回放未准备</p>
<p id="multi-playback-states" style="white-space: pre-line"></p>`;aside.append(multiGroup);
let coordPlayback=null, multiPlaybackKind=null;
function stopMultiPlayback(text){
  if(typeof MultiPlayback!=='undefined' && MultiPlayback.active && MultiPlayback.active.owner==='multi') MultiPlayback.clear();
  multiPlaybackKind=null;
  if(text && $('multi-playback-info')) $('multi-playback-info').textContent=text;
  if($('multi-playback-states')) $('multi-playback-states').textContent='';
}
function clearMulti(){if($('multi-info'))$('multi-info').textContent='场景或参数变化后结果已失效';if($('multi-table'))$('multi-table').innerHTML='';if($('coord-info'))$('coord-info').textContent='场景或参数变化后协调结果已失效，请重新协调';if($('coord-table'))$('coord-table').innerHTML='';coordPlayback=null;stopMultiPlayback('场景或参数变化后回放已失效');}
function clearCoord(text){if($('coord-info'))$('coord-info').textContent=text||'最小间距或最大等待变化后协调结果已失效，请重新协调';if($('coord-table'))$('coord-table').innerHTML='';coordPlayback=null;if(multiPlaybackKind==='coord')stopMultiPlayback('协调结果变化后回放已失效');}
const oldInvalidate2=invalidatePlan;invalidatePlan=function(){oldInvalidate2();clearComparison();clearMulti();};
function multiAlgorithm(){return $('multi-algorithm').value;}
function multiOptions(){
  if(multiAlgorithm()!=='caw')return undefined;
  return {step_xy:Number($('job-step_xy').value),order_strategy:$('job-order_strategy').value,objective:$('job-objective').value};
}
function multiRequest(){
  const extra={};
  if(multiAlgorithm()==='caw'){extra.algorithm='caw';extra.options=multiOptions();}
  return extra;
}
$('multi-run').onclick=async()=>{
  if(dirty){$('multi-info').textContent='场景参数尚未生成';return;}
  $('multi-info').textContent='计算中…';$('multi-table').innerHTML='';
  const algorithm=multiAlgorithm();
  try{
    const r=await api('/api/multi',Object.assign({scene,config:jobConfig(),uavs:Number($('multi-uavs').value)},multiRequest()));
    if(r.status==='success'){
      const note=(algorithm==='caw'?'各机独立 CAW 三维净空计划；未模拟运动协同':'各机独立 fixed-y 计划；未模拟运动协同')+'；覆盖为每机对全场景目标的平均值，非机队并集';
      $('multi-info').textContent=note;
      $('multi-table').innerHTML=`<table><thead><tr><th>UAV</th><th>状态</th><th>起点 → 终点</th><th>版本</th><th>路径 m</th><th>时长 s</th><th>覆盖</th></tr></thead><tbody>${r.uavs.map(x=>{
        const state=x.status==='success'?'成功'+(x.idle?'（无作业航段）':''):`失败 [${x.stage||'-'}]：${x.reason||''}`;
        const points=x.start_point_id?`${x.start_point_id} → ${x.end_point_id}`:'-';
        return `<tr><td>${x.uav}</td><td>${state}</td><td>${points}</td><td>${x.plan_version||'-'}</td><td>${x.path_length==null?'-':x.path_length.toFixed(2)}</td><td>${x.duration==null?'-':x.duration.toFixed(2)}</td><td>${x.coverage==null?'-':(x.coverage*100).toFixed(1)+'%'}</td></tr>`;
      }).join('')}</tbody></table>`;
    }else{
      $('multi-info').textContent=`生成失败 [${r.stage||'-'}]：${r.reason||'未知原因'}`;
      $('multi-table').innerHTML='';
    }
  }catch(e){$('multi-info').textContent='生成失败：'+e.message;$('multi-table').innerHTML='';}
};
$('coord-min-distance').addEventListener('input',()=>clearCoord());
$('coord-max-delay').addEventListener('input',()=>clearCoord());
$('multi-uavs').addEventListener('input',()=>{if($('multi-info'))$('multi-info').textContent='无人机数量变化后结果已失效，请重新运行';if($('multi-table'))$('multi-table').innerHTML='';clearCoord('无人机数量变化后协调结果已失效，请重新协调');stopMultiPlayback('无人机数量变化后回放已失效');});
$('multi-algorithm').addEventListener('change',()=>{clearMulti();clearCoord('多机算法变化后协调结果已失效，请重新协调');});
$('multi-playback-source').addEventListener('change',()=>{if(multiPlaybackKind)stopMultiPlayback('回放来源变化，请重新准备');});
$('coord-run').onclick=async()=>{
  if(dirty){$('coord-info').textContent='场景参数尚未生成，请先生成场景';return;}
  if(multiPlaybackKind==='coord')stopMultiPlayback('协调重新计算，回放已停止');
  coordPlayback=null;
  const params=Object.assign({scene,config:jobConfig(),uavs:Number($('multi-uavs').value),min_distance:Number($('coord-min-distance').value),max_delay:Number($('coord-max-delay').value),max_attempts:200},multiRequest());
  if(params.min_distance<=0){$('coord-info').textContent='最小机间距必须为正';return;}
  try{
    const r=await api('/api/coordinate',params);
    const offsets=(r.uavs||[]).map(u=>`UAV ${u.uav} 等待 ${u.offset_seconds.toFixed(2)} s · 时长 ${u.plan_duration.toFixed(2)} s`).join('\n');
    const fmt=v=>v==null?'-':Number(v).toFixed(2);
    $('coord-table').innerHTML=(r.uavs||[]).length?`<table><thead><tr><th>UAV</th><th>等待 s</th><th>时长 s</th><th>冲突对</th></tr></thead><tbody>${r.uavs.map(u=>`<tr><td>${u.uav}</td><td>${u.offset_seconds.toFixed(2)}</td><td>${u.plan_duration.toFixed(2)}</td><td>${u.conflicts}</td></tr>`).join('')}</tbody></table>`:'';
    if(r.status==='success'){
      const separation=r.min_separation==null?'无同时空中重叠（串行）':r.min_separation.toFixed(2)+' m';
      const algorithm=r.algorithm==='caw'?'caw 多机':'fixed-y 多机';
      $('coord-info').textContent=`协调成功 · ${algorithm} · 连续 CPA · 冲突 ${r.conflicts_before} → ${r.conflicts_after} · 最小间距 ${separation} · 等待合计 ${fmt(r.waiting_seconds)} s · makespan ${fmt(r.makespan)} s · 尝试 ${r.attempts}\n${offsets}\n安全：conflicts_after=0 · 场景 ${(r.scene_hash||'').slice(0,8)} · 配置 ${(r.config_hash||'').slice(0,8)}`;
    }else{
      $('coord-info').textContent=`协调失败 [${r.stage||'-'}] · ${r.reason}\n冲突 ${r.conflicts_before} → ${r.conflicts_after==null?'-':r.conflicts_after} · 尝试 ${r.attempts} · 等待合计 ${fmt(r.waiting_seconds)} s\n${offsets}`;
    }
    coordPlayback=(r.status==='success'&&r.playback)?Object.assign({status:'success'},r.playback):null;
    if(coordPlayback){
      $('multi-playback-source').value='coord';
      $('multi-playback-info').textContent=`协调结果可回放 · ${coordPlayback.tracks.length} 机 · ${fmt(coordPlayback.duration)} s · 点击“准备回放”`;
    }else{
      $('multi-playback-info').textContent=r.status==='success'?'协调结果没有可回放时间线（计划未生成）':'协调失败，回放不可用（需先消解冲突）';
    }
  }catch(e){$('coord-info').textContent='协调请求失败：'+e.message;$('coord-table').innerHTML='';}
};
const MULTI_PLAYBACK_CONTROLS={timeId:'multi-playback-time',seekId:'multi-playback-seek',playId:'multi-playback-play',pauseId:'multi-playback-pause',resetId:'multi-playback-reset',rateId:'multi-playback-rate',infoId:'multi-playback-info',statesId:'multi-playback-states'};
$('multi-playback-prepare').onclick=async()=>{
  if(dirty){$('multi-playback-info').textContent='场景参数尚未生成，请先生成场景';return;}
  const source=$('multi-playback-source').value;
  try{
    let payload;
    if(source==='baseline'){
      payload=await api('/api/multi-playback',Object.assign({scene,config:jobConfig(),uavs:Number($('multi-uavs').value)},multiRequest()));
    }else{
      if(!coordPlayback){$('multi-playback-info').textContent='请先完成一次协调，或切换到多机基线';return;}
      payload=coordPlayback;
    }
    if(!payload || !Array.isArray(payload.tracks) || !payload.tracks.length){
      $('multi-playback-info').textContent='回放准备失败：'+(payload?.reason||'没有时间线');
      return;
    }
    multiPlaybackKind=source;
    const idle=(payload.idle&&payload.idle.length)?` · 无作业航段：${payload.idle.join(', ')}`:'';
    const title=source==='coord'?'协调结果回放':(multiAlgorithm()==='caw'?'多机 CAW 回放':'多机基线回放');
    MultiPlayback.load('multi',payload.tracks,{title:title+idle,controls:MULTI_PLAYBACK_CONTROLS});
  }catch(e){$('multi-playback-info').textContent='回放准备失败：'+e.message;}
};
$('multi-playback-play').onclick=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='multi')MultiPlayback.play();};
$('multi-playback-pause').onclick=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='multi')MultiPlayback.pause();};
$('multi-playback-reset').onclick=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='multi')MultiPlayback.reset();};
$('multi-playback-rate').onchange=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='multi')MultiPlayback.setRate(Number($('multi-playback-rate').value));};
function multiPlaybackSeek(value){if(MultiPlayback.active&&MultiPlayback.active.owner==='multi')MultiPlayback.seek(Number(value));}
$('multi-playback-seek').oninput=e=>multiPlaybackSeek(e.target.value);
$('multi-playback-seek').onchange=e=>multiPlaybackSeek(e.target.value);
$('multi-playback-time').oninput=e=>multiPlaybackSeek(e.target.value);
$('multi-playback-time').onchange=e=>multiPlaybackSeek(e.target.value);
const expGroup=document.createElement('details');expGroup.innerHTML=`<summary>06 · 实验统计</summary><button id="experiment-run">运行默认实验</button><p id="experiment-info">多 seed、多方法描述性统计；失败进入分母；确定性方法 runs=1、std=None</p>`;aside.append(expGroup);$('experiment-run').onclick=async()=>{try{const r=await api('/api/experiment',{seeds:[0,1],methods:['fixed-y','multi'],uavs:[1,2],config:jobConfig()});$('experiment-info').textContent=r.summary.map(x=>`${x.method}/${x.uavs}机：覆盖 ${x.coverage_mean==null?'-':(x.coverage_mean*100).toFixed(1)+'%'} ± ${x.coverage_std==null?'n/a':(x.coverage_std*100).toFixed(1)+'%'} · 可行 ${(x.feasibility_rate*100).toFixed(0)}% (${x.successes}/${x.attempts}) · runs ${x.runs}`).join('；')+'；覆盖口径为每机平均（非机队并集）\n'+r.seed_note;}catch(e){$('experiment-info').textContent='实验失败：'+e.message;}};
function clearExperiment(){if($('experiment-info'))$('experiment-info').textContent='场景或参数变化后实验统计已失效，请重新运行';}
const oldInvalidateExperiment=invalidatePlan;invalidatePlan=function(){oldInvalidateExperiment();clearExperiment();};
const routeGroup=document.createElement('details');routeGroup.innerHTML=`<summary>07 · 转场搜索诊断</summary><button id="route-run">二维基线</button><button id="route3d-run">三维净空 A*</button><p id="route-info">二维基线只避障碍；三维分层图避树冠/障碍/禁飞，并含风场时间代价</p>`;aside.append(routeGroup);
function routeEndpoints(){const home=scene.launch_points[0].position;const height=currentPlan?.work_height??scene.terrain.height;const target=currentPlan?.segments?.find(s=>s.type==='spray')?.start||[home[0],home[1],height];return {start:[home[0],home[1],height],goal:target};}
$('route-run').onclick=async()=>{if(!currentPlan){$('route-info').textContent='请先在 02 面板生成计划';return;}try{const {start,goal}=routeEndpoints();const r=await api('/api/route',{scene,start:start.slice(0,2).concat(scene.terrain.height),goal:goal.slice(0,2).concat(scene.terrain.height),step:1,clearance:jobConfig().clearance});$('route-info').textContent=`二维基线 · `+(r.status==='success'?`可行 · ${r.length.toFixed(2)} m · 搜索节点 ${r.expanded}`:`失败：${r.reason}`);}catch(e){$('route-info').textContent='搜索失败：'+e.message;}};
$('route3d-run').onclick=async()=>{if(!currentPlan){$('route-info').textContent='请先在 02 面板生成计划';return;}try{const {start,goal}=routeEndpoints();const r=await api('/api/route3d',{scene,config:jobConfig(),start,goal,step_xy:Number($('job-step_xy').value)});if(r.status==='success'){const zs=r.path.map(p=>p[2]);$('route-info').textContent=`三维净空 A* · 可行 · ${r.length.toFixed(2)} m · 时间 ${r.time.toFixed(2)} s · 高度 ${Math.min(...zs).toFixed(2)}–${Math.max(...zs).toFixed(2)} m · 展开 ${r.expanded} · 网格 ${r.grid.layers} 层 · ${r.grid.hash.slice(0,8)}`;}else{$('route-info').textContent=`三维净空 A* · 失败 [${r.stage}]：${r.reason} · 展开 ${r.expanded}`;}}catch(e){$('route-info').textContent='搜索失败：'+e.message;}};
const jointGroup=document.createElement('details');
jointGroup.id='joint-panel';
jointGroup.innerHTML=`<summary>08 · 联合作业顺序</summary>
<label class="field">转场<select id="joint-transition"><option value="fixed">固定直线</option><option value="search">旧二维净空搜索</option><option value="caw">三维净空 A*</option></select></label>
<label class="field">模式<select id="joint-mode"><option value="exact">精确穷举（小规模）</option><option value="heuristic">启发式（NN+2-opt）</option></select></label>
<label class="field">顺序策略<select id="joint-strategy"><option value="nn+2opt">NN + 2-opt</option><option value="nn">最近邻</option><option value="fixed">固定</option></select></label>
<label class="field">网格步长 m<select id="joint-step"><option value="0.5">0.5</option><option value="1" selected>1.0</option><option value="2">2.0</option></select></label>
<label class="field">穷举上限（航段）<input id="joint-limit" type="number" min="1" max="8" value="6"></label>
<button id="joint-run">计算顺序</button>
<p id="joint-info" style="white-space: pre-line">精确穷举给出 gap=0；启发式只报告 J_heur、LB 与“相对下界”差距，不保证最优；超过上限时 unsupported</p>
<button id="joint-playback-prepare" disabled>准备回放（最优/基准）</button>
<button id="joint-playback-play" disabled>播放</button><button id="joint-playback-pause" disabled>暂停</button><button id="joint-playback-reset" disabled>重置</button>
<label>倍速 <select id="joint-playback-rate" disabled><option value="0.5">0.5×</option><option selected value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label>
<label>回放时间 s<input id="joint-playback-time" type="number" step="0.1" value="0" disabled></label>
<input id="joint-playback-seek" type="range" min="0" max="0" step="any" value="0" disabled>
<p id="joint-playback-info" style="white-space: pre-line">回放未准备</p>
<p id="joint-playback-states" style="white-space: pre-line"></p>`;
aside.append(jointGroup);
let jointResult=null, jointResultOptions=null;
function stopJointPlayback(text){if(typeof MultiPlayback!=='undefined'&&MultiPlayback.active&&MultiPlayback.active.owner==='joint')MultiPlayback.clear();if(text&&$('joint-playback-info'))$('joint-playback-info').textContent=text;if($('joint-playback-states'))$('joint-playback-states').textContent='';}
function clearJoint(){if($('joint-info'))$('joint-info').textContent='场景或参数变化后结果已失效';jointResult=null;jointResultOptions=null;if($('joint-playback-prepare'))$('joint-playback-prepare').disabled=true;stopJointPlayback('场景或参数变化后回放已失效');}
const oldInvalidate3=invalidatePlan;invalidatePlan=function(){oldInvalidate3();clearJoint();};
for(const id of ['joint-limit','joint-transition','joint-mode','joint-strategy','joint-step']) $(id).addEventListener('input',clearJoint);
function jointOptions(){return {transition:$('joint-transition').value,step_xy:Number($('joint-step').value),objective:'time'};}
$('joint-run').onclick=async()=>{
  if(dirty){$('joint-info').textContent='场景参数尚未生成，请先生成场景';return;}
  if(MultiPlayback.active&&MultiPlayback.active.owner==='joint')stopJointPlayback('重新计算，回放已停止');
  jointResult=null; jointResultOptions=null; $('joint-playback-prepare').disabled=true;
  const mode=$('joint-mode').value;
  try{
    if(mode==='heuristic'){
      const r=await api('/api/order',{scene,config:jobConfig(),strategy:$('joint-strategy').value,step_xy:Number($('joint-step').value)});
      if(r.status==='success'){
        const lb=r.lower_bound==null?'不可用（存在不可行边）':r.lower_bound.toFixed(2)+' s';
        const gap=r.gap_to_bound_abs==null?'-':`${r.gap_to_bound_abs.toFixed(2)} s（${r.gap_to_bound_rel==null?'-':(r.gap_to_bound_rel*100).toFixed(1)+'%'}）`;
        $('joint-info').textContent=`启发式 · ${r.strategy} · 顺序 [${r.order.join(', ')}] · J_heur ${r.order_cost.toFixed(2)} s · LB ${lb} · 相对下界差距 ${gap}\n相对下界，不保证最优 · 矩阵 ${r.matrix_mode} · 评估 ${r.evaluated} · 搜索边 ${r.routes_computed} · 场景 ${(r.scene_hash||'').slice(0,8)}`;
        $('joint-playback-info').textContent='启发式结果没有精确最优回放（请切回精确模式）';
      }else{
        const shown=(r.route_failures||[]).slice(0,2).map(x=>`${x.stage}: ${x.reason}`).join('；');
        $('joint-info').textContent=`启发式失败：${r.reason}${shown?'\n不可行边：'+shown:''}`;
        $('joint-playback-info').textContent='失败结果没有可回放轨迹';
      }
      return;
    }
    const r=await api('/api/joint',{scene,config:jobConfig(),limit:Number($('joint-limit').value),options:jointOptions()});
    if(r.status==='success'){
      const base=r.baseline||{},imp=r.improvement;
      const trans=r.transition==='caw'?'三维净空 A*':(r.transition==='search'?'旧二维净空搜索':'固定直线');
      const nodes=r.search_nodes?` · 搜索节点 ${r.search_nodes}`:'';
      const improve=imp?`\n较基准 ${imp.total_time_saved.toFixed(2)} s（${imp.total_time_pct.toFixed(1)}%）；路径缩短 ${imp.total_path_length_saved.toFixed(2)} m`:(base.status!=='success'?'\n基准直线计划失败，无改善量（增量仅描述性）':'');
      const rejected=r.rejected_total?` · 不可行 ${r.rejected_total}${r.rejected_note?'（'+r.rejected_note+'）':''}`:'';
      $('joint-info').textContent=`精确最优 · ${trans} · gap=0 · 顺序 [${r.order.join(', ')}] · 转场 ${r.transition_length.toFixed(2)} m · 路径 ${r.total_path_length.toFixed(2)} m · 时间 ${r.total_time.toFixed(2)} s · 扩展 ${r.expanded}/${r.orders_total}${nodes} · 安全通过${rejected}${improve}\n基准顺序 [${(base.order||[]).join(', ')}] · ${base.status==='success'?'时间 '+base.total_time.toFixed(2)+' s':'失败 '+base.reason} · 可行 ${r.feasible_orders} · 场景 ${(r.scene_hash||'').slice(0,8)} · 配置 ${(r.config_hash||'').slice(0,8)}`;
      jointResult=r; jointResultOptions=jointOptions(); $('joint-playback-prepare').disabled=false;
      $('joint-playback-info').textContent='最优/基准轨迹可回放 · 点击“准备回放”';
    }else if(r.status==='unsupported'){
      $('joint-info').textContent=`unsupported：${r.reason}`;
      jointResult=null; $('joint-playback-prepare').disabled=true; $('joint-playback-info').textContent='unsupported 结果没有可回放轨迹';
    }else{
      const shown=(r.rejected||[]).slice(0,2).map(x=>`${x.stage}: ${x.reason}`).join('；');
      const count=r.rejected_total?`（显示 ${Math.min(2,r.rejected_total)}/${r.rejected_total} 条失败候选）`:'';
      $('joint-info').textContent=`failed：${r.reason}${shown?'\n候选失败：'+shown+count:''}${r.rejected_note?'\n'+r.rejected_note:''}`;
      jointResult=null; $('joint-playback-prepare').disabled=true; $('joint-playback-info').textContent='failed 结果没有可回放轨迹';
    }
  }catch(e){$('joint-info').textContent='联合优化失败：'+e.message;}
};
const JOINT_PLAYBACK_CONTROLS={timeId:'joint-playback-time',seekId:'joint-playback-seek',playId:'joint-playback-play',pauseId:'joint-playback-pause',resetId:'joint-playback-reset',rateId:'joint-playback-rate',infoId:'joint-playback-info',statesId:'joint-playback-states'};
$('joint-playback-prepare').onclick=async()=>{
  if(!jointResult){$('joint-playback-info').textContent='请先计算成功的联合顺序';return;}
  try{
    const payload=await api('/api/joint-playback',{scene,config:jobConfig(),order:jointResult.order,options:jointResultOptions});
    if(!payload || !Array.isArray(payload.tracks) || !payload.tracks.length){
      $('joint-playback-info').textContent='回放准备失败：'+(payload?.reason||'没有时间线');return;
    }
    MultiPlayback.load('joint',payload.tracks,{title:'联合最优/基准回放',controls:JOINT_PLAYBACK_CONTROLS});
  }catch(e){$('joint-playback-info').textContent='回放准备失败：'+e.message;}
};
$('joint-playback-play').onclick=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='joint')MultiPlayback.play();};
$('joint-playback-pause').onclick=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='joint')MultiPlayback.pause();};
$('joint-playback-reset').onclick=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='joint')MultiPlayback.reset();};
$('joint-playback-rate').onchange=()=>{if(MultiPlayback.active&&MultiPlayback.active.owner==='joint')MultiPlayback.setRate(Number($('joint-playback-rate').value));};
function jointPlaybackSeek(value){if(MultiPlayback.active&&MultiPlayback.active.owner==='joint')MultiPlayback.seek(Number(value));}
$('joint-playback-seek').oninput=e=>jointPlaybackSeek(e.target.value);
$('joint-playback-seek').onchange=e=>jointPlaybackSeek(e.target.value);
$('joint-playback-time').oninput=e=>jointPlaybackSeek(e.target.value);
$('joint-playback-time').onchange=e=>jointPlaybackSeek(e.target.value);

// ---------------------------------------------------------- depot optimization
let depotResult = null;
const depotGroup = document.createElement('details');
depotGroup.innerHTML = `<summary>10 · 起降点优化</summary>
<label>候选<select id="depot-candidates"><option value="launch">场景起降点</option><option value="grid">网格候选</option></select></label>
<label>网格 <input id="depot-grid" type="number" min="2" max="12" value="3"></label>
<label>预算 <input id="depot-budget" type="number" min="1" value="64"></label>
<label>无人机 <input id="depot-uavs" type="number" min="1" max="32" value="1"></label>
<label>目标<select id="depot-objective"><option value="time">时间</option><option value="energy">能耗代理</option></select></label>
<label>能耗口径<select id="depot-energy-profile"><option value="motion-only">仅运动项</option><option value="mission-proxy">任务代理（未标定）</option></select></label>
<label><input id="depot-coordinate" type="checkbox">协调后 makespan</label>
<label>最小间距 m <input id="depot-min-distance" type="number" min="0.1" step="0.1" value="1"></label>
<label>Wh/eu <input id="depot-wh-per-eu" type="number" step="any" placeholder="可选"></label>
<label>标定编号 <input id="depot-calibration-id" type="text" placeholder="可选"></label>
<button id="depot-run">优化起降点</button><button id="depot-apply" disabled>应用选中点</button>
<p id="depot-info">候选枚举；能耗单位 eu（代理值，非电池）</p><div id="depot-table"></div>`;
document.querySelector('aside').append(depotGroup);
function clearDepot(){depotResult=null;if($('depot-apply'))$('depot-apply').disabled=true;if($('depot-info'))$('depot-info').textContent='场景或参数变化后起降点结果已失效';if($('depot-table'))$('depot-table').innerHTML='';}
const oldInvalidateDepot=invalidatePlan;invalidatePlan=function(){oldInvalidateDepot();clearDepot();};
(()=>{
  $('depot-run').onclick=async()=>{
    if(dirty){$('depot-info').textContent='场景参数尚未生成';return;}
    const uavs=Number($('depot-uavs').value);
    let planner=typeof plannerMethod==='function'?plannerMethod():'fixed-y';
    if(uavs>1)planner='fixed-y';
    const energy={profile:$('depot-energy-profile').value};
    if($('depot-wh-per-eu').value!=='')energy.wh_per_eu=Number($('depot-wh-per-eu').value);
    if($('depot-calibration-id').value.trim()!=='')energy.calibration_id=$('depot-calibration-id').value.trim();
    const options={candidates:$('depot-candidates').value,grid:Number($('depot-grid').value),budget:Number($('depot-budget').value),uavs,objective:$('depot-objective').value,planner,planner_options:typeof plannerOptions==='function'?plannerOptions():{},energy,coordinate:$('depot-coordinate').checked,min_distance:Number($('depot-min-distance').value)};
    $('depot-info').textContent='优化中…';
    try{
      const r=await api('/api/depot',{scene,config:jobConfig(),options});
      if(r.status!=='success'){depotResult=null;$('depot-apply').disabled=true;$('depot-info').textContent='优化失败：'+(r.reason||'无可行候选');$('depot-table').innerHTML='';return;}
      depotResult=r;const s=r.selected;
      const lb=r.lower_bound==null?'-':r.lower_bound.toFixed(2);
      const gap=r.gap==null?'-':(r.gap*100).toFixed(1)+'%';
      const wh=s.energy_wh==null?'':' · '+s.energy_wh.toFixed(2)+' Wh';
      const coord=s.coordinated?` · 协调等待 ${s.waiting_seconds.toFixed(2)} s / 冲突 ${s.conflicts_after}`:'';
      $('depot-info').textContent=`${r.exact?'精确枚举':'预算受限'} · ${r.evaluated}/${r.candidates_total} · ${r.objective} · 选中 [${s.depot.map(v=>v.toFixed(2)).join(', ')}] · makespan ${s.makespan.toFixed(2)} s · 总时间 ${s.total_time.toFixed(2)} s · 能耗 ${s.energy_eu.toFixed(2)} eu${wh}${coord} · 下界 ${lb} · gap ${gap}${s.coverage_note?' · '+s.coverage_note:''} · 场景 ${(r.scene_hash||'').slice(0,8)}`;
      $('depot-apply').disabled=false;
      const selectedKey=r.selected?JSON.stringify(r.selected.depot):null;
      $('depot-table').innerHTML=`<p>显示 ${r.rows.length}/${r.candidates_total} 个候选${r.truncated?'（后端仅保留前 50 行）':''}；选中行已高亮</p>`+'<table><thead><tr><th>起降点</th><th>状态</th><th>时间 s</th><th>能耗 eu</th><th>覆盖</th><th>原因</th></tr></thead><tbody>'+r.rows.map(x=>{const hit=JSON.stringify(x.depot)===selectedKey;return `<tr${hit?' style="background:#123244"':''}><td>[${x.depot.map(v=>v.toFixed(2)).join(', ')}]</td><td>${x.status}</td><td>${x.makespan==null?'-':x.makespan.toFixed(2)}</td><td>${x.energy_eu==null?'-':x.energy_eu.toFixed(2)}</td><td>${x.coverage==null?'-':(x.coverage*100).toFixed(1)+'%'}</td><td>${x.reason||''}</td></tr>`;}).join('')+'</tbody></table>';
    }catch(e){depotResult=null;$('depot-apply').disabled=true;$('depot-info').textContent='优化失败：'+e.message;}
  };
  const sortieGroup=document.createElement('details');
  sortieGroup.innerHTML=`<summary>11 · 多批次（载药）</summary>
<label>载药上限 kg <input id="sortie-capacity" type="number" min="0.001" step="0.1" value="0.5"></label>
<label>流量 kg/s <input id="sortie-flow" type="number" min="0.0001" step="0.001" value="0.01"></label>
<label>Wh/eu <input id="sortie-wh-per-eu" type="number" step="any" placeholder="可选"></label>
<label>标定编号 <input id="sortie-calibration-id" type="text" placeholder="可选"></label>
<label>补药间隔 s <input id="sortie-refill" type="number" min="0" step="1" value="0"></label>
<label>换电间隔 s <input id="sortie-recharge" type="number" min="0" step="1" value="0"></label>
<button id="sortie-run">生成多批次</button>
<p id="sortie-info">按载药量贪心切分；补药/换电为固定间隔，默认 0</p><div id="sortie-table"></div>`;
document.querySelector('aside').append(sortieGroup);
function clearSortie(){if($('sortie-info'))$('sortie-info').textContent='场景或参数变化后多批次结果已失效';if($('sortie-table'))$('sortie-table').innerHTML='';}
const oldInvalidateSortie=invalidatePlan;invalidatePlan=function(){oldInvalidateSortie();clearSortie();};
window.addEventListener('load',()=>{
  const aside=document.querySelector('aside');
  if(!aside)return;
  const editor=[...aside.querySelectorAll('details')].find(d=>d.textContent.includes('09 · 场景编辑器'));
  if(editor)editor.after(depotGroup);else aside.append(depotGroup);
  depotGroup.after(sortieGroup);
});
$('sortie-run').onclick=async()=>{
  if(dirty){$('sortie-info').textContent='场景参数尚未生成';return;}
  $('sortie-info').textContent='计算中…';$('sortie-table').innerHTML='';
  try{
    const energy={profile:'motion-only'};
    if($('sortie-wh-per-eu').value!=='')energy.wh_per_eu=Number($('sortie-wh-per-eu').value);
    if($('sortie-calibration-id').value.trim()!=='')energy.calibration_id=$('sortie-calibration-id').value.trim();
    const r=await api('/api/sorties',{scene,config:jobConfig(),options:{payload_capacity_kg:Number($('sortie-capacity').value),flow_rate_kg_per_s:Number($('sortie-flow').value),refill_seconds:Number($('sortie-refill').value),recharge_seconds:Number($('sortie-recharge').value),energy}});
    if(r.status!=='success'){$('sortie-info').textContent=`多批次失败 [${r.stage||'-'}]：`+(r.reason||'');$('sortie-table').innerHTML='';return;}
    const gap=r.total_gap_seconds??0;
    const wh=r.total_energy_wh==null?'':` · ${r.total_energy_wh.toFixed(2)} Wh`;
    $('sortie-info').textContent=`${r.sortie_count} 批 · 总时间 ${r.total_time.toFixed(2)} s（飞行 ${r.total_flight_time.toFixed(2)} s + 间隔 ${gap.toFixed(2)} s）· 总载药 ${r.total_payload_kg.toFixed(3)} kg · 能耗 ${r.total_energy_eu.toFixed(2)} eu${wh} · 起点 ${r.start_point_id} → 终点 ${r.end_point_id}`;
    $('sortie-table').innerHTML='<table><thead><tr><th>批次</th><th>航段</th><th>间隔 s</th><th>飞行 s</th><th>载药 kg</th><th>安全</th></tr></thead><tbody>'+r.sorties.map(x=>`<tr><td>${x.index}</td><td>${x.lane_indices.join(',')}</td><td>${(x.gap_before_seconds??0).toFixed(2)}</td><td>${x.duration.toFixed(2)}</td><td>${x.payload_kg.toFixed(3)}</td><td>${x.safety}</td></tr>`).join('')+'</tbody></table>';
  }catch(e){$('sortie-info').textContent='多批次失败：'+e.message;$('sortie-table').innerHTML='';}
};
for(const id of ['sortie-capacity','sortie-flow','sortie-refill','sortie-recharge','sortie-wh-per-eu','sortie-calibration-id']) $(id).addEventListener('input',()=>{if($('sortie-table'))$('sortie-table').innerHTML='';if($('sortie-info'))$('sortie-info').textContent='批次参数变化后结果已失效，请重新生成';});
  $('depot-apply').onclick=async()=>{
    if(!depotResult||!depotResult.selected)return;
    const point=depotResult.selected.depot;
    const candidate=structuredClone(scene);
    candidate.launch_points=[{id:'launch-1',position:point,role:'both'}];
    delete candidate.launch_assignments;
    try{
      const d=await api('/api/load',candidate);
      if(typeof accept==='function')accept(d,'应用起降点');
      else{scene=d.scene;invalidatePlan();draw();}
      clearDepot();
      $('depot-info').textContent='已应用选中起降点；请重新生成计划、执行与评价';
    }catch(e){$('depot-info').textContent='应用失败：'+e.message;}
  };
})();
