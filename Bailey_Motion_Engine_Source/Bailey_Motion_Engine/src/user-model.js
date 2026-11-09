
/*
 * Bailey Hall user model — manuscript-based experimental policy (v2)
 *
 * Edit this file directly in VS Code. The HTML editor displays the source
 * inside BaileyModelSource below; click "Apply code + reset" after pasting.
 *
 * DECISIONS: U(i,k,t) = distanceScore + crowdScore + behavioralScore
 *                     + panicShock + residualShock.
 * behavioralScore = -wT*T + wH*H + wP*P - wN*N - wS*C.
 * (wT,wH,wP,wN,wS) follow a correlated, unit-mean lognormal law.
 *
 * MOTION: dv/dt = (v0*u - v)/tau + a_obstacles + a_interactions.
 * All values and coefficients below are editable assumptions, NOT calibrated
 * claims about real pedestrians or Bailey Hall.
 *
 * This policy fits the existing Bailey engine API, including physical row
 * constraints, region transitions, hard collisions and portal processing.
 */
window.BaileyModelSource = `({
  settings: {
    // BEHAVIOR: Sigma = sigma^2 * ((1-rho)*I + rho*11^T).
    weightSigma: 1.2,
    weightRho: -0.15,                   // must lie strictly between -0.25 and 1
    timeScale: 10,                     // tau_0, seconds, normalizes perceived time
    decisionInterval: 1.5,            // seconds between reconsidering a route
    noiseInterval: 15,                // panic and residual shocks refresh every 15 s
    shockSD: 0.20,                    // manuscript: delta, epsilon ~ N(0, .2^2)
    panicMean: 0.45,                  // illustrative Beta distribution for rho_i
    panicSD: 0.20,
    observeRadius: 4.0,               // metres for perceived peer behavior
    discoveryRadius: 2.2,             // learn a closed door when near it
    // MOTION (acceleration expressed in m/s^2).
    relaxationTime: 0.65,            // tau, seconds
    obstacleStrength: 0.8,           // scale not specified in manuscript
    comfortDistance: 0.15,           // r_0, metres
    interactionStrength: 0.4,       // scale not specified in manuscript
    interactionRange: 2.6,           // metres
    interactionLambda: 0.25,         // lambda, seconds/metre
    interactionN: 1.0,               // n in angular attenuation
    interactionNPrime: 1.0,          // n' in angular attenuation
    maxSpeedFactor: 1.35,            // upper bound on speed / preferred speed
    // The source does not provide actual arrival paths. Until we have them,
    // treat the main foyer route as familiar, and the closest aisle as the
    // familiar way out of a seating row.
    familiarBuildingExit: 'MAIN'
  },

  clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); },
  length(x, y) { return Math.hypot(x, y); },
  angleDifference(a, b) { return Math.atan2(Math.sin(a-b), Math.cos(a-b)); },

  // Sample z~N(mu,Sigma), w_j=exp(z_j). mu_j=-Sigma_jj/2 implies E[w_j]=1.
  // The off-diagonal entries of Sigma are sigma^2*rho (NOT the correlations
  // of the final exponentiated weights).
  sampleWeights(api) {
    const sigma=this.settings.weightSigma, rho=this.settings.weightRho;
    if(!(sigma>0 && rho>-.25 && rho<1)) throw Error('Invalid weightSigma/weightRho');
    if(!this._cholesky || this._choleskySigma!==sigma || this._choleskyRho!==rho) {
      const covariance=Array.from({length:5},(_,i)=>
        Array.from({length:5},(_,j)=>sigma*sigma*(i===j?1:rho)));
      const L=Array.from({length:5},()=>Array(5).fill(0));
      for(let i=0;i<5;i++) for(let j=0;j<=i;j++) {
        let v=covariance[i][j];
        for(let k=0;k<j;k++) v-=L[i][k]*L[j][k];
        L[i][j]=i===j?Math.sqrt(Math.max(v,0)):v/L[j][j];
      }
      this._cholesky=L;this._choleskySigma=sigma;this._choleskyRho=rho;
    }
    const z=Array.from({length:5},()=>api.normal()), names=['T','H','P','N','S'];
    const w={};
    for(let i=0;i<5;i++) {
      let latent=-(sigma*sigma)/2;
      for(let k=0;k<=i;k++) latent+=this._cholesky[i][k]*z[k];
      w[names[i]]=Math.exp(latent);
    }
    return w;
  },

  setup(a,api) {
    a.data.weights=this.sampleWeights(api);
    // Use the engine's existing seeded distributions where possible.
    a.data.betaDistance=this.clamp(a.params.sanity??0.75,0,1);
    // Positive = follows crowds, negative = prefers less crowded options.
    a.data.betaCrowd=this.clamp(2*(a.params.groupthink??0.5)-1,-1,1);
    a.data.panicSensitivity=this.clamp(
      a.params.panic??api.sample({type:'beta',mean:this.settings.panicMean,
        sd:this.settings.panicSD}),0,1);
    a.data.noiseCache={};
    a.data.knownBlocked=[];
    a.data.portal=null;
    a.data.exitChoice=null;
    a.data.started=false;
    a.data.nextDecision=0;
    const s=a.seat, left=s.leftAisle, right=s.rightAisle;
    const leftDistance=s.r*(s.angle-left),rightDistance=s.r*(right-s.angle);
    // This stand-in for a known entrance path can later be replaced by data.
    a.data.familiarRowSide=leftDistance<=rightDistance?'ROW_LEFT':'ROW_RIGHT';
    const rowChoices=[
      {id:'ROW_LEFT',angle:left,distance:leftDistance,habit:a.data.familiarRowSide==='ROW_LEFT'?1:0},
      {id:'ROW_RIGHT',angle:right,distance:rightDistance,habit:a.data.familiarRowSide==='ROW_RIGHT'?1:0}
    ];
    const chosen=leftDistance<=rightDistance
    ? rowChoices[0]
    : rowChoices[1];
    a.data.side=chosen.id==='ROW_LEFT'?1:-1;
    a.aisleAngle=chosen.angle;
    a.data.rowEndAngle=a.aisleAngle+a.data.side*(api.geometry.aisleHalfWidth/s.r);
    // Small offset keeps the waypoint inside the selected aisle, with no
    // fictitious central barrier or enforced two-file queue.
    a.data.aisleOffset=a.data.side*0.20;
    a.data.rowSideChoice=chosen.id;
  },

  // Freeze each shock for a 15-second window; refresh separately by option.
  shock(a,api,choiceId,kind) {
    const bucket=Math.floor(api.t/this.settings.noiseInterval);
    const key=kind+':'+choiceId;
    const old=a.data.noiseCache[key];
    if(old && old.bucket===bucket) return old.value;
    const value=this.settings.shockSD*api.normal();
    a.data.noiseCache[key]={bucket,value};
    return value;
  },

  // n_k^t: number of people committed to an option at the previous tick.
  beforeTick(api) {
    const counts=Object.create(null);
    for(const a of api.agents) if(!a.exited) {
      for(const k of [a.data.exitChoice,a.data.portal,a.data.rowSideChoice])
        if(k) counts[k]=(counts[k]||0)+1;
    }
    this._counts=counts;
  },

  peerShare(a,api,id,kind) {
    const near=api.neighbors(a,this.settings.observeRadius);
    if(!near.length) return 0;
    let following=0;
    for(const b of near) {
      const bChoice=kind==='exit'?b.data.exitChoice:
        kind==='row'?b.data.rowSideChoice:b.data.portal;
      if(bChoice===id) following++;
    }
    return following/near.length;
  },

  // Experimental proxy: opposing flows make passing/overtaking less polite.
  // Replace with a better observational definition when available.
  normViolation(a,api,choice) {
    const near=api.neighbors(a,this.settings.observeRadius);
    if(!near.length) return 0;
    const target=Number.isFinite(choice.angle)?
      api.point(api.radius(a),choice.angle):{x:choice.x??a.x,y:choice.y??a.y};
    const dx=target.x-a.x,dy=target.y-a.y,L=Math.hypot(dx,dy)||1;
    let opposed=0,moving=0;
    for(const b of near) {
      const speed=Math.hypot(b.vx,b.vy);
      if(speed<0.12) continue;
      moving++;
      if((b.vx*dx+b.vy*dy)/(speed*L)<-0.15) opposed++;
    }
    return moving?opposed/moving:0;
  },

  // U_(i,k)^t from the manuscript, including the five-component dot product.
  choose(a,api,options,kind,currentId=null) {
    if(!options.length) return null;
    const minDistance=Math.min(...options.map(o=>Math.max(0,o.distance)));
    const counts=options.map(o=>this._counts?.[o.id]||0);
    const minCount=Math.min(...counts),maxCount=Math.max(...counts);
    const wd=a.data.weights, betaD=a.data.betaDistance,
          betaN=a.data.betaCrowd;
    let chosen=null,best=-Infinity;
    for(let i=0;i<options.length;i++) {
      const o=options[i],d=Math.max(0,o.distance);
      const normalizedCount=maxCount>minCount?
        (counts[i]-minCount)/(maxCount-minCount):null;
      // At betaN=0, an option receives no extra crowd reward.
      let crowd=0;
      if(normalizedCount!==null && Math.abs(betaN)>1e-8) {
        crowd=betaN>0?Math.pow(normalizedCount,betaN):
          Math.pow(1-normalizedCount,-betaN);
      }
      const time=(o.estimatedTime??(d/Math.max(0.35,a.params.speed||1.2))) /
        this.settings.timeScale;
      const habit=o.habit??0;
      const peers=this.peerShare(a,api,o.id,kind);
      const norms=this.normViolation(a,api,o);
      const switching=currentId!==null && o.id!==currentId?1:0;
      const behavioral=-wd.T*time+wd.H*habit+wd.P*peers-
        wd.N*norms-wd.S*switching;
      const distanceScore=Math.pow((minDistance+1)/(d+1),betaD);
      const panic=a.data.panicSensitivity*(1-Math.exp(-api.t/60))*
        this.shock(a,api,o.id,'panic');
      const residual=this.shock(a,api,o.id,'residual');
      const utility=distanceScore+crowd+behavioral+panic+residual;
      if(utility>best) {best=utility;chosen=o;}
    }
    a.data.lastUtility=best;
    return chosen;
  },

  // Approximate path distance along a curved circulation track.
  arcDistance(a,api,p,trackR) {
    return trackR*Math.abs(this.angleDifference(api.polar(a),p.angle));
  },

  // Local decision at the end of an aisle: choose an auditorium door or stair.
  selectPortal(a,api) {
    let options;
    if(a.region==='rim') options=api.portals.filter(p=>p.from==='rim');
    else if(a.region==='balcony-rim') options=api.portals.filter(p=>p.from==='balcony-rim');
    else if(a.region==='foyer') options=api.portals.filter(p=>p.from==='foyer');
    else return null;
    options=options.filter(p=>!a.data.knownBlocked.includes(p.id));
    const track=a.region==='balcony-rim'?23.15:a.region==='rim'?23.15:0;
    const actions=options.map(p=>({id:p.id,angle:p.angle,
      x:p.x,y:p.y,
      distance:a.region==='foyer'?api.distance(a,p):this.arcDistance(a,api,p,track),
      // The balcony foyer stairs are more familiar than stage emergency stairs.
      habit:a.region==='balcony-rim'?(p.id.startsWith('BACK_')?1:0):
        a.region==='rim'?(Math.abs(p.angle-a.aisleAngle)<.23?1:0):1}));
    const pick=this.choose(a,api,actions,'portal',a.data.portal);
    return pick?.id??null;
  },

  // Egress option k, chosen when the person enters the surrounding corridor.
  // MAIN means reach a foyer door first, then select one of the five M doors.
  pickExit(a,api) {
    const g=api.geometry,angle=api.polar(a);
    const options=[];
    for(const e of g.exits) {
      if(a.data.knownBlocked.includes(e.id)) continue;
      if(e.id==='MAIN') {
        const foyer=api.portals.filter(p=>p.from==='corridor'&&
          !a.data.knownBlocked.includes(p.id));
        if(!foyer.length) continue;
        const distance=Math.min(...foyer.map(p=>
          g.corridorR*Math.abs(angle-p.angle)))+7.5;
        options.push({id:'MAIN',angle:e.angle*Math.PI,distance,
          habit:a.data.familiarBuildingExit==='MAIN'?1:0});
      } else {
        const p=api.portal(e.id);
        if(!p) continue;
        options.push({id:e.id,angle:p.angle,
          distance:g.corridorR*Math.abs(angle-p.angle)+1.8,
          habit:a.data.familiarBuildingExit===e.id?1:0});
      }
    }
    return this.choose(a,api,options,'exit',a.data.exitChoice)?.id??null;
  },

  routeFromCorridor(a,api) {
    const selected=this.pickExit(a,api);
    if(!selected) {a.data.portal=null;return;}
    a.data.exitChoice=selected;
    if(selected==='MAIN') {
      const entries=api.portals.filter(p=>p.from==='corridor'&&
        !a.data.knownBlocked.includes(p.id));
      entries.sort((p,q)=>this.arcDistance(a,api,p,api.geometry.corridorR)-
        this.arcDistance(a,api,q,api.geometry.corridorR));
      a.data.portal=entries[0]?.id??null;
    } else a.data.portal=selected;
    a.data.nextDecision=api.t+this.settings.decisionInterval;
  },

  // The local waypoint is not a globally known shortest path. It is a request
  // to move along the legal row/aisle/circulation network toward the next door.
  goal(a,api) {
    const g=api.geometry,pt=api.point,theta=api.polar(a),r=api.radius(a);
    if(a.region==='row') return pt(a.seat.r,a.data.rowEndAngle);
    if(a.region==='aisle') {
      const targetR=a.floor===0?g.auditoriumR:g.balconyR;
      return pt(targetR,a.aisleAngle+a.data.aisleOffset/targetR);
    }
    if(['rim','balcony-rim','corridor'].includes(a.region)) {
      const p=api.portal(a.data.portal);
      if(!p) return {x:a.x,y:a.y};
      const trackR=a.region==='corridor'?25.5:23.15;
      const delta=this.angleDifference(p.angle,theta);

    // Once aligned with the doorway, approach it directly.
    // Do not return to the circulation track.
    if(Math.abs(delta)<=.055){
      return {x:p.x,y:p.y};
    }

    if(Math.abs(r-trackR)>.22){
      return pt(trackR,theta);
    }

    return pt(
      trackR,
      theta+this.clamp(delta,-.065,.065)
    );
    }
    if(a.region==='foyer') {
      const p=api.portal(a.data.portal);
      return p?{x:p.x,y:p.y}:{x:a.x,y:a.y};
    }
    return {x:a.x,y:a.y};
  },

  // Approximate wall normal fields from the current geometric region.
  // The engine has no wall-query API; these are analytical proxies, whereas
  // engine.js enforces the ACTUAL region validity and hard-body exclusion.
  obstacleAcceleration(a,api) {
    const g=api.geometry,r=api.radius(a),theta=api.polar(a),
      erx=Math.cos(theta),ery=Math.sin(theta),
      etx=-Math.sin(theta),ety=Math.cos(theta);
    let ax=0,ay=0;
    const strength=this.settings.obstacleStrength,
      r0=Math.max(.05,this.settings.comfortDistance);
    const push=(distance,nx,ny)=>{
      const mag=strength*Math.exp(-Math.max(0,distance)/r0);
      ax+=mag*nx;ay+=mag*ny;
    };
    if(a.region==='aisle') {
      const lateral=this.angleDifference(theta,a.aisleAngle)*r;
      const clearHalf=Math.max(.05,g.aisleHalfWidth-a.radius-.02);
      push(clearHalf-lateral,-etx,-ety);
      push(clearHalf+lateral,etx,ety);
      // At a row end the person can no longer move toward smaller radii.
      push(r-(a.seat.r-.08),erx,ery);
    } else if(a.region==='rim' || a.region==='balcony-rim' ||
              a.region==='corridor') {
      const lower=a.region==='corridor'?24.0:
        a.region==='rim'?g.auditoriumR-.18:g.balconyR-.18;
      const upper=a.region==='corridor'?27.65:
        a.region==='rim'?24.4:24.5;
      push(r-lower,erx,ery);
      push(upper-r,-erx,-ery);
    } else if(a.region==='foyer') {
      push(a.x+12.4,1,0);push(12.4-a.x,-1,0);
      push(a.y-32.2,0,1);push(41.65-a.y,0,-1);
    }
    return {x:ax,y:ay};
  },

  // Manuscript interaction force (D_ij, signed theta_ij, N_ij).
  // We must multiply by an adjustable acceleration scale because the paper's
  // bare exponentials are dimensionless. Hard collisions remain in engine.js.
  interactionAcceleration(a,api,neighbors) {
    let ax=0,ay=0;
    const lambda=this.settings.interactionLambda,
      n=this.settings.interactionN,nPrime=this.settings.interactionNPrime;
    for(const b of neighbors) {
      const x=b.x-a.x,y=b.y-a.y,d=Math.hypot(x,y);
      if(d<1e-8) continue;
      const hx=x/d,hy=y/d;
      const Dx=hx+lambda*(a.vx-b.vx),
        Dy=hy+lambda*(a.vy-b.vy);
      const D=Math.max(1e-5,Math.hypot(Dx,Dy)),
        ux=Dx/D,uy=Dy/D;
      const theta=Math.atan2(Dx*hy-Dy*hx,Dx*hx+Dy*hy);
      // A normal perpendicular to the interaction direction.
      const nx=-uy,ny=ux;
      const strength=this.settings.interactionStrength*
        (0.75+0.5*(a.params.norms??0.5));
      const atten=Math.exp(-d/D),
        longitudinal=Math.exp(-Math.pow(nPrime*theta*D,2)),
        sideways=Math.exp(-Math.pow(n*theta*D,2));
      const signed=Math.sign(theta);
      ax-=strength*atten*(longitudinal*ux+signed*sideways*nx);
      ay-=strength*atten*(longitudinal*uy+signed*sideways*ny);
    }
    return {x:ax,y:ay};
  },

  computeVelocity(a,api,waypoint) {
    const dx=waypoint.x-a.x,dy=waypoint.y-a.y,L=Math.hypot(dx,dy);
    if(L<0.025) return {vx:0,vy:0};
    const speed=a.params.speed||1.2,
      desiredX=speed*dx/L,desiredY=speed*dy/L;
    const tau=Math.max(.05,this.settings.relaxationTime);
    const obstacles=this.obstacleAcceleration(a,api);
    const interactions=this.interactionAcceleration(a,api,
      api.neighbors(a,this.settings.interactionRange));
    const ax=(desiredX-a.vx)/tau+obstacles.x+interactions.x,
      ay=(desiredY-a.vy)/tau+obstacles.y+interactions.y;
    let vx=a.vx+api.dt*ax,vy=a.vy+api.dt*ay;
    const magnitude=Math.hypot(vx,vy);
    const maxSpeed=this.settings.maxSpeedFactor*speed;
    if(magnitude>maxSpeed) {vx*=maxSpeed/magnitude;vy*=maxSpeed/magnitude;}
    // Don't fly past a nearby waypoint in a single tick.
    const limit=L/api.dt;
    if(Math.hypot(vx,vy)>limit) {
      const cap=limit/Math.hypot(vx,vy);vx*=cap;vy*=cap;
    }
    return {vx,vy};
  },

  observeClosures(a,api) {
    const id=a.data.portal,p=id?api.portal(id):null;
    if(!p || p.enabled || api.distance(a,p)>this.settings.discoveryRadius ||
       a.data.knownBlocked.includes(id)) return;
    a.data.knownBlocked.push(id);
    if(a.region==='corridor') this.routeFromCorridor(a,api);
    else a.data.portal=this.selectPortal(a,api);
    a.data.nextDecision=api.t+this.settings.decisionInterval;
  },

  decide(a,api) {
    if(api.t<(a.params.reaction||0)) return {vx:0,vy:0};
    a.data.started=true;
    this.observeClosures(a,api);
    if(a.region==='corridor' && api.t>=a.data.nextDecision)
      this.routeFromCorridor(a,api);
    // These zones acquire their next local target on entry; recover if absent.
    if(['rim','balcony-rim','foyer'].includes(a.region) && !a.data.portal)
      a.data.portal=this.selectPortal(a,api);
    return this.computeVelocity(a,api,this.goal(a,api));
  },

  afterMove(a,api) {
    if(!a.data.started) return;
    const g=api.geometry,pt=api.point;
    if(a.region==='row') {
      if(Math.abs(this.angleDifference(api.polar(a),a.data.rowEndAngle))*a.seat.r>.07)
        return;
      const angle=a.aisleAngle+a.data.side*
        (g.aisleHalfWidth-a.radius-.06)/a.seat.r;
      const p=pt(a.seat.r,angle);
      api.setRegion(a,'aisle',p.x,p.y);
      return;
    }
    if(a.region==='aisle') {
      const limit=a.floor===0?g.auditoriumR:g.balconyR;
      if(api.radius(a)<limit-.16)return;
      if(api.setRegion(a,a.floor===0?'rim':'balcony-rim')) {
        a.data.portal=this.selectPortal(a,api);
        a.data.nextDecision=api.t+this.settings.decisionInterval;
      }
      return;
    }
    if(['rim','balcony-rim','corridor','foyer'].includes(a.region) && a.data.portal)
      api.usePortal(a,a.data.portal);
  },

  onPortal(a,portal,api) {
    if(a.region==='corridor') this.routeFromCorridor(a,api);
    else if(a.region==='foyer') a.data.portal=this.selectPortal(a,api);
  },

  onStairsComplete(a,portal,api) {
    a.data.portal=this.selectPortal(a,api);
  }
})`;

window.compileBaileyModel = function(source) {
  const p=Function('"use strict";return ('+source+');')();
  if(!p || typeof p.decide!=='function')
    throw Error('Your model must implement decide(agent, api).');
  return p;
};
window.BaileyModel=window.compileBaileyModel(window.BaileyModelSource);
