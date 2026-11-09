/* Bailey geometry is data, not an embedded image; all dimensions are provisional metres. */
(function(){
const PI=Math.PI;
function polar(p,g){return Math.atan2(p.y-g.centerY,p.x)}
function radius(p,g){return Math.hypot(p.x,p.y-g.centerY)}
function point(r,angle,g){return {x:r*Math.cos(angle),y:g.centerY+r*Math.sin(angle)}}
function distance(a,b){return Math.hypot(a.x-b.x,a.y-b.y)}
function clamp(x,lo,hi){return Math.max(lo,Math.min(hi,x))}
function buildSeats(g){const aisles=[0.02,...g.aisleAngles,0.98].map(v=>v*PI),all=[];
 for(const sec of g.sections){let blocks=[],sum=0;
  for(let row=0;row<sec.rows;row++){const r=sec.firstR+row*sec.step;
   for(let block=0;block<aisles.length-1;block++){const left=aisles[block],right=aisles[block+1],avail=r*(right-left)-2*g.aisleHalfWidth;
    const max=Math.max(0,Math.floor(avail/sec.pitch)+1);if(!max)continue;blocks.push({row,block,r,left,right,max});sum+=max}
  }
  if(sum<sec.capacity)throw Error('Insufficient seat space in '+sec.id+': '+sum+' < '+sec.capacity);
  let filled=0;for(const b of blocks){let exact=sec.capacity*b.max/sum;b.n=Math.floor(exact);b.frac=exact-b.n;filled+=b.n}
  for(const b of [...blocks].sort((a,b)=>b.frac-a.frac||a.row-b.row||a.block-b.block).slice(0,sec.capacity-filled))b.n++;
  let count=0;for(const b of blocks){const lo=b.left+g.aisleHalfWidth/b.r,hi=b.right-g.aisleHalfWidth/b.r;
   for(let k=0;k<b.n;k++){let theta=b.n===1?(lo+hi)/2:lo+(hi-lo)*k/(b.n-1),p=point(b.r,theta,g);
    all.push({...p,angle:theta,r:b.r,section:sec.id,floor:sec.floor,row:b.row,block:b.block,number:k+1,
      leftAisle:b.left,rightAisle:b.right,
      label:`${sec.id[0].toUpperCase()}-${String(b.row+1).padStart(2,'0')}-${b.block+1}-${k+1}`});count++}
  }
  if(count!==sec.capacity)throw Error('Seat count mismatch for '+sec.id+': '+count)
 }
 return all;
}
function makePortals(g){let portals=[];
 g.auditoriumDoors.forEach((theta,i)=>{let p=point(23.25,theta*PI,g);portals.push({id:'AUD'+i,type:'door',from:'rim',to:'corridor',floor:0,x:p.x,y:p.y,angle:theta*PI,width:1.35})});
 g.foyerDoors.forEach((theta,i)=>{let p=point(25.6,theta*PI,g);portals.push({id:'F'+i,type:'door',from:'corridor',to:'foyer',floor:0,x:p.x,y:p.y,angle:theta*PI,width:1.65})});
 for(let i=0;i<5;i++)portals.push({id:'M'+i,type:'exit',from:'foyer',floor:0,x:(i-2)*2.35,y:41.2,width:1.75,exitId:'MAIN'});
 for(const e of g.exits.filter(e=>e.type==='side')){let p=point(27,e.angle*PI,g);portals.push({id:e.id,type:'exit',from:'corridor',floor:0,x:p.x,y:p.y,angle:e.angle*PI,width:e.width,exitId:e.id})}
 for(const s of g.stairs){let p=point(23.15,s.angle*PI,g);portals.push({id:s.id,type:'stairs',from:'balcony-rim',floor:1,x:p.x,y:p.y,angle:s.angle*PI,width:s.width,length:s.length,destination:s.type})}
 return portals;
}
/* The engine applies these constraints to agent centers, not just to the drawing. */
function insideRegion(a,x,y,g){const p={x,y},r=radius(p,g),t=polar(p,g),margin=a.radius??.2;
 if(a.region==='row'){
   const currentRadius=a.seat.r,lo=a.seat.leftAisle+g.aisleHalfWidth/currentRadius,hi=a.seat.rightAisle-g.aisleHalfWidth/currentRadius;
   return Math.abs(r-currentRadius)<.07 && t>=lo-.012 && t<=hi+.012;
 }
 if(a.region==='aisle'){
   const lateral=(t-a.aisleAngle)*r;
   return Math.abs(lateral)<=g.aisleHalfWidth-margin-.02 && r>=a.seat.r-.08 && r<=(a.floor===0?g.auditoriumR:g.balconyR)+.12;
 }
 if(a.region==='rim')return r>=g.auditoriumR-.18 && r<=24.4 && t>=.012*PI&&t<=.988*PI;
 if(a.region==='balcony-rim')return r>=g.balconyR-.18&&r<=24.5&&t>=.008*PI&&t<=.992*PI;
 if(a.region==='corridor')return r>=24.0&&r<=27.65&&t>=.005*PI&&t<=.995*PI;
 if(a.region==='foyer')return x>=-12.4&&x<=12.4&&y>=32.2&&y<=41.65;
 return a.region==='stairs'||a.region==='done';
}
window.BaileyGeometry={polar,radius,point,distance,clamp,buildSeats,makePortals,insideRegion};
})();
