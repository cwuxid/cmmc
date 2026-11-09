/*
 * BaileyMotionEngine — model-agnostic tick engine.
 * It NEVER selects an exit, computes desired velocities, optimizes routes, or
 * chooses an agent's actions. All those decisions belong to user-model.js.
 * Responsibilities: seeded populations, time, integration, region boundaries,
 * disc collisions, stair transfers, portal throughput, state and telemetry.
 */
(function(){
const G=window.BaileyGeometry, RNG=window.BaileyRNG, PI=Math.PI;
const clone=x=>JSON.parse(JSON.stringify(x));
class BaileyEngine {
 constructor(config,policy){
  this.config=clone(config);this.policy=policy;this.rng=new RNG(this.config.seed);
  this.g=this.config.geometry;this.t=0;this.tick=0;this.done=0;this.events=[];this.history=[];this.agents=[];
  this.portals=G.makePortals(this.g).map(x=>({...x,enabled:true,tokens:Math.max(1,x.width*1.2),passed:0}));
  this.portalMap=Object.fromEntries(this.portals.map(x=>[x.id,x]));
  this.metrics={blockedMoves:0,portalWaits:0,regionRejections:0,collisionRejections:0};
  this.seats=G.buildSeats(this.g);this._spawn();this._rebuildIndex();
  for(const a of this.agents)this._call('setup',a,this.context(a));
  this._pushHistory();
 }
 _spawn(){
  const n=Math.min(this.seats.length,Math.max(1,Math.floor(this.config.population)));
  const s=this.g.sections,total=s.reduce((x,v)=>x+v.capacity,0),quota=s.map(v=>Math.floor(n*v.capacity/total));
  let remains=n-quota.reduce((a,b)=>a+b,0);
  for(const i of s.map((v,i)=>({i,frac:n*v.capacity/total-quota[i]})).sort((a,b)=>b.frac-a.frac).slice(0,remains))quota[i.i]++;
  let selection=[];
  for(let j=0;j<s.length;j++)selection.push(...this.rng.shuffle(this.seats.filter(x=>x.section===s[j].id)).slice(0,quota[j]));
  // Stable IDs and a complete accessible state, with no preassigned routes.
  this.agents=selection.map((seat,id)=>{
   let params={};for(const [key,p] of Object.entries(this.config.distributions))params[key]=this.rng.sample(p);
   return {id,x:seat.x,y:seat.y,vx:0,vy:0,floor:seat.floor,region:'row',seat:clone(seat),
     aisleAngle:null,params,radius:params.radius??.2,active:true,exited:false,exitAt:null,exitId:null,
     stairUntil:null,stairPortal:null,blockedTicks:0,data:{}};
  });
 }
 _call(hook,...args){const fn=this.policy?.[hook];if(typeof fn==='function')return fn.call(this.policy,...args)}
 _key(f,x,y){return f+':'+Math.floor(x/1.3)+':'+Math.floor(y/1.3)}
 _rebuildIndex(){this.grid=new Map();for(const a of this.agents)if(a.floor>=0&&!a.exited)this._indexAdd(a)}
 _indexAdd(a){const k=this._key(a.floor,a.x,a.y);if(!this.grid.has(k))this.grid.set(k,new Set());this.grid.get(k).add(a)}
 _indexRemove(a){this.grid.get(this._key(a.floor,a.x,a.y))?.delete(a)}
 neighbors(a,range=2.5,x=a.x,y=a.y){const res=[],i=Math.floor(x/1.3),j=Math.floor(y/1.3),n=Math.ceil(range/1.3);
  for(let u=-n;u<=n;u++)for(let v=-n;v<=n;v++){
   let cell=this.grid.get(a.floor+':'+(i+u)+':'+(j+v));if(!cell)continue;
   for(const other of cell)if(other.id!==a.id&&G.distance({x,y},other)<=range)res.push(other);
  }
  return res;
 }
 _clear(a,x,y,region=a.region){
  if(this.config.limits.enforceRegions){const check={...a,region};if(!G.insideRegion(check,x,y,this.g)){this.metrics.regionRejections++;return false}}
  if(this.config.limits.hardCollisions){for(const b of this.neighbors(a,a.radius+.9,x,y)){
    if((x-b.x)**2+(y-b.y)**2 < (a.radius+b.radius)**2*1.005){this.metrics.collisionRejections++;return false}
  }}
  return true;
 }
 context(a=null){const self=this;return {
  get t(){return self.t},get tick(){return self.tick},get dt(){return self.config.dt},
  get config(){return self.config},get geometry(){return self.g},get agents(){return self.agents},get portals(){return self.portals},get current(){return a},
  random:()=>self.rng.uniform(),normal:()=>self.rng.normal(),sample:p=>self.rng.sample(p),
  point:(r,theta)=>G.point(r,theta,self.g),polar:p=>G.polar(p,self.g),radius:p=>G.radius(p,self.g),distance:G.distance,
  portal:id=>self.portalMap[id],neighbors:(agent,range=2.5)=>self.neighbors(agent,range),
  clear:(agent,x,y,region=agent.region)=>self._clear(agent,x,y,region),
  setRegion:(agent,region,x=agent.x,y=agent.y,extras={})=>self.setRegion(agent,region,x,y,extras),
  usePortal:(agent,id)=>self.usePortal(agent,id),
  exit:(agent,id='CUSTOM')=>self.exit(agent,id),
  log:(message)=>self.log(message)
 }}
 setRegion(a,region,x=a.x,y=a.y,extras={}){
  const trial={...a,...extras,region};if(!this._clear(trial,x,y,region))return false;
  this._indexRemove(a);a.x=x;a.y=y;a.region=region;Object.assign(a,extras);this._indexAdd(a);return true;
 }
 usePortal(a,id){const p=this.portalMap[id];if(!p||!p.enabled||a.region!==p.from||a.floor!==p.floor)return false;
  if(G.distance(a,p)>.94)return false;
  if(this.config.limits.doorCapacity&&p.tokens<1){this.metrics.portalWaits++;return false}
  let dest=null,newRegion=null;
  if(p.type==='door'){
  newRegion=p.to;

  // Try multiple landing positions within the doorway width.
  // Every candidate must satisfy region and collision constraints.
  const lateralOffsets=[0,-.20,.20,-.35,.35]
    .map(f=>f*p.width);

  const depths=[0,.35,.70,1.05];

  for(const depth of depths){
    for(const lateral of lateralOffsets){
      let candidate;

      if(newRegion==='corridor'){
        const r=24.66+depth;
        candidate=G.point(
          r,
          p.angle+lateral/r,
          this.g
        );
      } else {
        candidate={
          x:p.x+lateral,
          y:Math.max(32.8,p.y+.45)+depth
        };
      }

      if(this._clear(
        a,
        candidate.x,
        candidate.y,
        newRegion
      )){
        dest=candidate;
        break;
      }
    }

    if(dest)break;
  }

  if(!dest){
    this.metrics.portalWaits++;
    return false;
  }
}
  if(this.config.limits.doorCapacity)p.tokens-=1;p.passed++;
  if(p.type==='exit'){this.exit(a,p.exitId);this._call('onPortal',a,p,this.context(a));return true}
  this._indexRemove(a);
  if(p.type==='stairs'){
   a.region='stairs';a.floor=-1;a.stairPortal=p.id;
   a.stairUntil=this.t+p.length/Math.max(.4,(a.params.speed||1.2)*.7);a.vx=0;a.vy=0;
  } else {a.x=dest.x;a.y=dest.y;a.region=newRegion;a.vx=0;a.vy=0;this._indexAdd(a)}
  this._call('onPortal',a,p,this.context(a));return true;
 }
 _finishStairs(a){const p=this.portalMap[a.stairPortal];if(!p)return;
  if(p.destination==='outside'){this.exit(a,p.id);return}
  const x=p.id.endsWith('_E')?10.6:-10.6,y=35.3;
  if(!this._clear({...a,floor:0,region:'foyer'},x,y,'foyer')){a.stairUntil+=this.config.dt;return}
  a.floor=0;a.region='foyer';a.x=x;a.y=y;a.vx=0;a.vy=0;a.stairUntil=null;this._indexAdd(a);
  this._call('onStairsComplete',a,p,this.context(a));
 }
 exit(a,id='CUSTOM'){
  if(a.exited)return;
  this._indexRemove(a);a.active=false;a.exited=true;a.floor=-2;a.region='done';a.vx=a.vy=0;
  a.exitId=id;a.exitAt=this.t;this.done++;this._call('onExit',a,this.context(a));
 }
 log(message){this.events.push({time:this.t,message:String(message)});if(this.events.length>150)this.events.shift()}
 _pushHistory(){this.history.push({t:this.t,exited:this.done});if(this.history.length>2000)this.history.shift()}
 _move(a,command){
  if(!command)return;let vx=Number(command.vx??0),vy=Number(command.vy??0);
  if(!Number.isFinite(vx)||!Number.isFinite(vy))throw Error('Invalid velocity from model for agent '+a.id);
  let dt=this.config.dt,dx=vx*dt,dy=vy*dt,dist=Math.hypot(dx,dy),max=.7;
  if(dist>max){dx*=max/dist;dy*=max/dist} // Maximum substep for safe collision checking, not a walking speed model.
  let nx=a.x+dx,ny=a.y+dy;
  if(a.region==='row'){
   // Hard geometric constraint: seat rows are circular 1D tracks, never cross-row shortcuts.
   const theta=G.polar(a,this.g),sgn=Math.cos(theta)*dy-Math.sin(theta)*dx;
   const desired=theta+sgn/a.seat.r;
   const lo=a.seat.leftAisle+this.g.aisleHalfWidth/a.seat.r,
         hi=a.seat.rightAisle-this.g.aisleHalfWidth/a.seat.r;
   const pp=G.point(a.seat.r,G.clamp(desired,lo,hi),this.g);nx=pp.x;ny=pp.y;
  }
  let accepted=this._clear(a,nx,ny);
  if(!accepted&&a.region!=='row'){
   // Slide only as an integration convenience; movement priorities remain the user's.
   for(const [mx,my] of [[a.x+dx*.5,a.y+dy*.5],[a.x+dx,a.y],[a.x,a.y+dy]]){
    if(this._clear(a,mx,my)){nx=mx;ny=my;accepted=true;break}
   }
  }
  if(accepted){this._indexRemove(a);const ox=a.x,oy=a.y;a.x=nx;a.y=ny;a.vx=(nx-ox)/dt;a.vy=(ny-oy)/dt;this._indexAdd(a);a.blockedTicks=0}
  else {a.vx=0;a.vy=0;a.blockedTicks++;this.metrics.blockedMoves++}
 }
 step(){if(this.done===this.agents.length||this.t>=this.config.limits.maxSeconds)return;
  this.t+=this.config.dt;this.tick++;
  for(const p of this.portals)if(p.enabled)p.tokens=Math.min(Math.max(1,p.width*1.35),p.tokens+p.width*1.3*this.config.dt);
  this._call('beforeTick',this.context());
  const order=this.rng.shuffle(this.agents.map(a=>a.id));
  for(const i of order){const a=this.agents[i];if(a.exited)continue;
   if(a.region==='stairs'){if(this.t>=a.stairUntil)this._finishStairs(a);continue}
   const api=this.context(a),command=this._call('decide',a,api);
   this._move(a,command);
   this._call('afterMove',a,api);
  }
  this._call('afterTick',this.context());
  if(this.tick%10===0)this._pushHistory();
 }
 runSteps(n){for(let j=0;j<n;j++){if(this.done===this.agents.length||this.t>=this.config.limits.maxSeconds)break;this.step()}}
 agentsCSV(){const columns=['id','floor','region','section','row','block','seat','x','y','radius','speed','sanity','groupthink','pack','norms','reaction','exited','exitId','exitAt'];
  const v=x=>x===null||x===undefined?'':String(x);return [columns.join(','),...this.agents.map(a=>[a.id,a.floor,a.region,a.seat.section,a.seat.row+1,a.seat.block+1,a.seat.number,a.x.toFixed(3),a.y.toFixed(3),a.radius,...['speed','sanity','groupthink','pack','norms','reaction'].map(k=>a.params[k]),a.exited,a.exitId,a.exitAt].map(v).join(','))].join('\n')}
}
window.BaileyEngine=BaileyEngine;
})();
