'use strict';
// Browser owns only the playback clock. All physical state is queried from Python.
let timeline = null, executionState = null, evaluationState = null, playing = false;
let playTime = 0, clockStart = 0, modelStart = 0, playbackRate = 1, requestVersion = 0;
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
  requestVersion++; playing = false; timeline = null; executionState = null; evaluationState = null; playTime = 0;
  playbackButtons(false); $('execution-seek').value = '0'; $('execution-time').value = '0';
  $('execution-info').textContent = '回放已失效：请先生成有效计划';
  $('evaluation-info').textContent = '覆盖评价未运行';
}
async function prepareExecution() {
  resetExecution();
  if(!currentPlan || dirty) return;
  const version = requestVersion, reference = currentPlan;
  try {
    const result = await api('/api/execution',{scene,plan:reference});
    if(version !== requestVersion || reference !== currentPlan) return;
    timeline = result; $('execution-seek').max = result.duration; $('execution-time').max = result.duration;
    playbackButtons(true); await queryTime(0);
  } catch(error) { if(version === requestVersion) $('execution-info').textContent = error.message; }
}
function desiredTime() {
  return Math.min(timeline.duration, modelStart + (performance.now()-clockStart)/1000*playbackRate);
}
async function queryTime(time) {
  const version = ++requestVersion, reference = timeline;
  if(!reference) return;
  try {
    const state = await api('/api/state',{execution_id:reference.execution_id,time});
    if(version !== requestVersion || reference !== timeline) return;
    executionState = state; playTime = state.time;
    const ev = await api('/api/evaluation',{scene,plan:currentPlan,timeline, time});
    evaluationState = ev;
    const stat=ev.evaluation||ev;
    $('evaluation-info').textContent = `目标覆盖 ${(ev.coverage*100).toFixed(1)}% · 漏喷目标 ${(stat.missed_targets||[]).length} · 重复目标 ${(stat.repeated_targets||[]).length} · 喷洒 ${ev.spray_seconds.toFixed(2)} s · 估算量 ${(ev.total_spray_amount??stat.total_spray_amount??0).toFixed(2)}（网格近似）`;
    $('execution-seek').value = state.time; $('execution-time').value = state.time;
    const names = {takeoff:'起飞',transit:'转场',spray:'喷洒',landing:'降落',completed:'落地完成'};
    $('execution-info').textContent = `${state.time.toFixed(2)} / ${timeline.duration.toFixed(2)} s · ${names[state.status]}\n航段 ${state.segment_index+1} · 喷洒${state.spray?'开':'关'} · 模型速度 ${state.speed.toFixed(2)} m/s\n位置 [${state.position.map(v=>v.toFixed(2)).join(', ')}] m`;
    if(state.status === 'completed') playing = false;
    draw();
  } catch(error) {
    if(version !== requestVersion) return;
    playing = false; $('execution-info').textContent = '时间查询失败：'+error.message;
  }
}
async function animate() {
  if(!playing || !timeline) return;
  await queryTime(desiredTime());
  if(playing) requestAnimationFrame(animate);
}
$('execution-prepare').onclick = prepareExecution;
$('execution-play').onclick = () => {
  if(!timeline || playing || playTime === timeline.duration) return;
  playing = true; modelStart = playTime; clockStart = performance.now(); requestAnimationFrame(animate);
};
$('execution-pause').onclick = () => {
  if(!timeline) return;
  const time = playing ? desiredTime() : playTime;
  playing = false; queryTime(time);
};
$('execution-reset').onclick = () => {playing = false; if(timeline) queryTime(0);};
function handleSeekInput(event) {
  if(!timeline) return;
  playing = false;
  const value=Math.max(0,Math.min(timeline.duration,Number(event.target.value)));
  $('execution-seek').value=value; $('execution-time').value=value;
  queryTime(value);
}
$('execution-seek').oninput = handleSeekInput;
$('execution-seek').onchange = handleSeekInput;
$('execution-time').onchange = () => {playing = false; queryTime(Number($('execution-time').value));};
$('execution-time').oninput = () => {playing = false; queryTime(Number($('execution-time').value));};
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

const comparisonGroup=document.createElement('details');comparisonGroup.innerHTML=`<summary>05 · 基线对照</summary><label>方法 <select id="compare-method"><option value="both">两者</option><option value="fixed-y-boustrophedon">当前方法</option><option value="naive-target-order">朴素基线</option></select></label><button id="compare-run">运行比较</button><p id="compare-info">尚未运行</p><div id="compare-table"></div>`;aside.append(comparisonGroup);
let comparison=null;
function clearComparison(){comparison=null;if($('compare-info'))$('compare-info').textContent='比较结果已失效，请重新运行';if($('compare-table'))$('compare-table').innerHTML='';}
const oldInvalidate=invalidatePlan;invalidatePlan=function(){oldInvalidate();clearComparison();};
$('compare-run').onclick=async()=>{if(dirty){$('compare-info').textContent='场景参数尚未生成';return;}try{comparison=await api('/api/compare',{scene,config:jobConfig(),method:$('compare-method').value,resolution:.5});$('compare-info').textContent='网格近似评价；结果不代表实测作物效果';$('compare-table').innerHTML='<table><thead><tr><th>方法</th><th>状态</th><th>路径 m</th><th>时间 s</th><th>喷洒 s</th><th>覆盖率</th><th>漏喷</th><th>重复</th><th>违规</th></tr></thead><tbody>'+comparison.results.map(r=>`<tr><td>${r.method}</td><td>${r.status==='success'?'成功':r.reason}</td><td>${r.path_length?.toFixed(2)??'-'}</td><td>${r.duration?.toFixed(2)??'-'}</td><td>${r.spray_seconds?.toFixed(2)??'-'}</td><td>${r.coverage==null?'-':(r.coverage*100).toFixed(1)+'%'}</td><td>${r.missed??'-'}</td><td>${r.repeated??'-'}</td><td>${r.violation?'是':'否'}</td></tr>`).join('')+'</tbody></table>';}catch(e){$('compare-info').textContent='比较失败：'+e.message;}}

const multiGroup=document.createElement('details');multiGroup.innerHTML=`<summary>06 · 多机协同</summary><label>无人机数量 <input id="multi-uavs" type="number" min="1" max="32" value="2"></label><button id="multi-run">生成多机基线</button><p id="multi-info">连续作业带分块；结果仅为规划与网格评价</p><div id="multi-table"></div>`;aside.append(multiGroup);
function clearMulti(){if($('multi-info'))$('multi-info').textContent='场景或参数变化后结果已失效';if($('multi-table'))$('multi-table').innerHTML='';}
const oldInvalidate2=invalidatePlan;invalidatePlan=function(){oldInvalidate2();clearComparison();clearMulti();};
$('multi-run').onclick=async()=>{if(dirty){$('multi-info').textContent='场景参数尚未生成';return;}try{const r=await api('/api/multi',{scene,config:jobConfig(),uavs:Number($('multi-uavs').value)});$('multi-info').textContent=r.status==='success'?'已生成各机独立计划；未模拟运动协同':'生成失败：'+r.reason;$('multi-table').innerHTML=r.uavs?r.uavs.map(x=>`<div>UAV ${x.uav} · ${x.status} · ${x.path_length?.toFixed(2)??'-'} m · 覆盖 ${(x.coverage*100).toFixed(1)}%</div>`).join(''):'';}catch(e){$('multi-info').textContent='生成失败：'+e.message;}};
const expGroup=document.createElement('details');expGroup.innerHTML=`<summary>07 · 实验统计</summary><button id="experiment-run">运行默认实验</button><p id="experiment-info">多 seed、多方法描述性统计；不代表训练效果</p>`;aside.append(expGroup);$('experiment-run').onclick=async()=>{try{const r=await api('/api/experiment',{seeds:[0,1],methods:['fixed-y','multi'],uavs:[1,2]});$('experiment-info').textContent=r.summary.map(x=>`${x.method}/${x.uavs}机：覆盖 ${(x.coverage_mean*100).toFixed(1)}% ± ${(x.coverage_std*100).toFixed(1)}%`).join('；');}catch(e){$('experiment-info').textContent='实验失败：'+e.message;}};
const routeGroup=document.createElement('details');routeGroup.innerHTML=`<summary>08 · 三维转场搜索</summary><button id="route-run">检查起降直线/网格路径</button><p id="route-info">净空搜索基线；不替换当前固定转场</p>`;aside.append(routeGroup);$('route-run').onclick=async()=>{try{const home=scene.launch_points[0].position;const target=currentPlan?.segments?.find(s=>s.type==='spray')?.start||home;const r=await api('/api/route',{scene,start:home,goal:target,step:1,clearance:jobConfig().clearance});$('route-info').textContent=r.status==='success'?`可行 · ${r.length.toFixed(2)} m · 搜索节点 ${r.expanded}`:`失败：${r.reason}`;}catch(e){$('route-info').textContent='搜索失败：'+e.message;}};
const jointGroup=document.createElement('details');jointGroup.innerHTML=`<summary>09 · 联合作业顺序</summary><button id="joint-run">计算小规模最优顺序</button><p id="joint-info">穷举基准；超过上限时明确拒绝</p>`;aside.append(jointGroup);$('joint-run').onclick=async()=>{try{const r=await api('/api/joint',{scene,config:jobConfig(),limit:8});$('joint-info').textContent=r.status==='success'?`最优基准 · 转场 ${r.transition_length.toFixed(2)} m · 扩展 ${r.expanded}`:`${r.status}：${r.reason}`;}catch(e){$('joint-info').textContent='联合优化失败：'+e.message;}};
