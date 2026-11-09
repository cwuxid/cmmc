/* UI controller. No choice or motion formula lives in this file. */
(function(){
'use strict';
const $=id=>document.getElementById(id),clone=x=>JSON.parse(JSON.stringify(x));
const G=window.BaileyGeometry;let world=clone(window.BaileyConfig),policy=window.BaileyModel;
const sourceDefaults=window.BaileyModelSource,worldDefaults=clone(window.BaileyConfig);
let engine=null,playing=false,selected=null,previous=0,accum=0,frames=0,lastDraw=0;
function describeError(e){$('status').textContent='Error: '+e.message;$('status').style.color='#ff9fa8';$('error').hidden=false;$('error').textContent=e.stack||String(e);playing=false;}
function settingsFromForm(){const cfg=clone(world);cfg.population=Math.floor(+$('population').value);cfg.seed=(+$('seed').value)>>>0;cfg.dt=+$('dt').value;
  cfg.limits.hardCollisions=$('collisions').checked;cfg.limits.enforceRegions=$('regions').checked;cfg.limits.doorCapacity=$('capacity').checked;
  if(!Number.isFinite(cfg.population)||cfg.population<1||cfg.population>cfg.geometry.sections.reduce((s,x)=>s+x.capacity,0))throw Error('Population is outside seat capacity.');
  if(!Number.isFinite(cfg.dt)||cfg.dt<=0||cfg.dt>.4)throw Error('Tick size must be between 0 and 0.4 seconds.');
  return cfg;}
function formFromSettings(){ $('population').value=world.population;$('population').max=world.geometry.sections.reduce((x,s)=>x+s.capacity,0);$('seed').value=world.seed;$('dt').value=world.dt;
  $('collisions').checked=world.limits.hardCollisions;$('regions').checked=world.limits.enforceRegions;$('capacity').checked=world.limits.doorCapacity;}
function portalToggles(){const box=$('portals');box.textContent='';for(const p of engine.portals){const label=document.createElement('label');label.className='portaltoggle';const input=document.createElement('input');input.type='checkbox';input.checked=p.enabled;input.addEventListener('change',()=>{p.enabled=input.checked});label.append(input,document.createTextNode(p.id));box.append(label)}}
function reset(useForm=true){try{if(useForm)world=settingsFromForm();engine=new window.BaileyEngine(world,policy);selected=null;playing=false;accum=0;previous=0;
  $('run').textContent='▶ Run';$('status').textContent='Ready · edit policy or step through ticks';$('status').style.color='';$('error').hidden=true;
  portalToggles();refresh();}catch(e){describeError(e)}}
function renderInspector(){const el=$('inspect');if(selected===null){el.textContent='Click a pedestrian on either map to inspect its current state and sampled parameters.';return}
 const a=engine.agents[selected];if(!a){el.textContent='Agent not found';return}
 const p=Object.entries(a.params).map(([k,v])=>`${k}: ${typeof v==='number'?v.toFixed(3):String(v)}`).join('<br>');
 el.innerHTML=`<div class="inspectdetails"><strong>Agent #${a.id}</strong> · ${a.region}<br>Floor: ${a.floor}, seat: ${a.seat.label}<br>Position: (${a.x.toFixed(2)}, ${a.y.toFixed(2)}) m<br>Velocity: (${a.vx.toFixed(2)}, ${a.vy.toFixed(2)}) m/s<br>Blocked ticks: ${a.blockedTicks}<br>${p}<br><strong>Custom policy state:</strong><pre>${escapeHtml(JSON.stringify(a.data,null,2))}</pre></div>`;
}
function escapeHtml(s){return s.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function refresh(){if(!engine)return;
  window.BaileyViewer.draw($('ground'),engine,0,selected);window.BaileyViewer.draw($('upper'),engine,1,selected);
  $('time').innerHTML=engine.t.toFixed(1)+' <em>s</em>';
  $('exited').textContent=engine.done+' / '+engine.agents.length;
  $('rows').textContent=engine.agents.filter(x=>x.region==='row').length;
  $('rejections').textContent=engine.metrics.collisionRejections.toLocaleString()+' / '+engine.metrics.regionRejections.toLocaleString();
  if(engine.done===engine.agents.length){playing=false;$('run').textContent='▶ Run';$('status').textContent='All agents exited'}
  else if(engine.t>=engine.config.limits.maxSeconds){playing=false;$('status').textContent='Max simulated time reached'}
  renderInspector();
}
function step(n){try{engine.runSteps(n);refresh()}catch(e){describeError(e)}}
function animation(ts){if(!previous)previous=ts;
 const wall=Math.min(.12,(ts-previous)/1000);previous=ts;
 if(playing&&engine){accum+=wall*(+$('playback').value);let n=0;while(accum>=engine.config.dt&&n<150&&playing){engine.step();accum-=engine.config.dt;n++;if(engine.done===engine.agents.length||engine.t>=engine.config.limits.maxSeconds)playing=false}}
 if(ts-lastDraw>45){refresh();lastDraw=ts}
 requestAnimationFrame(animation);
}
function download(name,data,type='text/plain'){const blob=new Blob([data],{type}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),2500)}
function selectAgent(evt,canvas,floor){const bounds=canvas.getBoundingClientRect(),xx=(evt.clientX-bounds.left)*canvas.width/bounds.width,yy=(evt.clientY-bounds.top)*canvas.height/bounds.height;
 const scale=Math.min(canvas.width/69,canvas.height/52),wx=(xx-canvas.width/2)/scale,wy=(yy-40)/scale;
 let nearest=null,score=Infinity;for(const a of engine.agents){if(a.floor!==floor||a.exited)continue;let d=(a.x-wx)**2+(a.y-wy)**2;if(d<score){score=d;nearest=a}}
 selected=score<(1.3)**2?nearest.id:null;refresh()}
$('modelCode').value=sourceDefaults;$('worldCode').value=JSON.stringify(world,null,2);
$('run').onclick=()=>{if(!engine)return;playing=!playing;$('run').textContent=playing?'Ⅱ Pause':'▶ Run';$('status').textContent=playing?'Running custom model':'Paused';};
$('step').onclick=()=>{playing=false;$('run').textContent='▶ Run';step(1)};
$('step10').onclick=()=>{playing=false;$('run').textContent='▶ Run';step(10)};
$('reset').onclick=()=>reset(true);
$('applySettings').onclick=()=>reset(true);
$('applyCode').onclick=()=>{try{policy=window.compileBaileyModel($('modelCode').value);$('error').hidden=true;reset(false)}catch(e){describeError(e)}};
$('restoreCode').onclick=()=>{$('modelCode').value=sourceDefaults;};
$('applyWorld').onclick=()=>{try{const candidate=JSON.parse($('worldCode').value);if(!candidate.geometry||!candidate.distributions||!candidate.limits)throw Error('World JSON must include geometry, distributions, and limits.');world=candidate;formFromSettings();reset(false)}catch(e){describeError(e)}};
$('resetWorld').onclick=()=>{world=clone(worldDefaults);$('worldCode').value=JSON.stringify(world,null,2);formFromSettings();reset(false)};
$('csv').onclick=()=>download('bailey_agents.csv',engine.agentsCSV(),'text/csv');
$('exportWorld').onclick=()=>download('world.json',JSON.stringify(world,null,2),'application/json');
$('exportCode').onclick=()=>download('user-model.js','window.BaileyModelSource='+JSON.stringify($('modelCode').value)+';\nwindow.compileBaileyModel = '+window.compileBaileyModel.toString()+';\nwindow.BaileyModel=window.compileBaileyModel(window.BaileyModelSource);\n','text/javascript');
$('ground').addEventListener('click',e=>selectAgent(e,$('ground'),0));
$('upper').addEventListener('click',e=>selectAgent(e,$('upper'),1));
formFromSettings();reset(false);requestAnimationFrame(animation);
window.BaileyDev={get engine(){return engine},get model(){return policy},get config(){return world},reset,step};
})();
