/* Rendering is deliberately read-only. Edit freely; it never determines movement. */
(function(){
const G=window.BaileyGeometry,PI=Math.PI;
function draw(canvas,engine,floor,selected=null){
 const ctx=canvas.getContext('2d'),w=canvas.width,h=canvas.height,g=engine.g;
 const scale=Math.min(w/69,h/52),ox=w/2,oy=40;
 const pt=(p)=>[ox+p.x*scale,oy+p.y*scale],polar=(r,t)=>pt(G.point(r,t,g));
 function line(a,b,color,width=1){const [x,y]=pt(a),[xx,yy]=pt(b);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(xx,yy);ctx.stroke()}
 function ring(r0,r1,t0,t1,fill){ctx.beginPath();const [cx,cy]=pt({x:0,y:g.centerY});ctx.arc(cx,cy,r1*scale,t0,t1);ctx.arc(cx,cy,r0*scale,t1,t0,true);ctx.closePath();ctx.fillStyle=fill;ctx.fill()}
 function ringline(r,t0,t1,color,width=1){const [cx,cy]=pt({x:0,y:g.centerY});ctx.beginPath();ctx.arc(cx,cy,r*scale,t0,t1);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()}
 function text(message,x,y,color='#9aacc0',size=11){ctx.font=`${size}px ui-sans-serif,system-ui`;ctx.fillStyle=color;ctx.fillText(message,x,y)}
 ctx.clearRect(0,0,w,h);ctx.fillStyle='#0c1725';ctx.fillRect(0,0,w,h);
 ctx.strokeStyle='#203144';ctx.lineWidth=1;for(let xx=-30;xx<=30;xx+=5){let x=ox+xx*scale;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke()}for(let yy=0;yy<47;yy+=5){const y=oy+yy*scale;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}
 text(floor===0?'FIRST FLOOR • orchestra / loge / exits':'SECOND FLOOR • balcony',16,23,'#adc8d8',12);
 const end=PI;
 ring(0,26.9,0,end,'#142438');
 if(floor===0){
  ring(g.auditoriumR,27.5,0,end,'#243849');ring(g.auditoriumR,24.15,0,end,'#29445c');
  ring(24.15,27.5,0,end,'#23384c');
  ctx.fillStyle='#22374a';const [fx,fy]=pt({x:-12,y:32});ctx.fillRect(fx,fy,24*scale,10.3*scale);
  ctx.strokeStyle='#567287';ctx.strokeRect(fx,fy,24*scale,10.3*scale);
  ringline(g.auditoriumR,0,PI,'#5a7387',2);ringline(27.5,0,PI,'#688195',2);
  text('FOYER',ox-18,oy+38.6*scale,'#a9bcd0',12);
  text('STAGE',ox-21,oy+6*scale,'#728da4',12);
 } else {
  ring(g.balconyR,24.65,0,end,'#29445d');ringline(g.balconyR,0,PI,'#647f94',2);
  text('OPEN TO AUDITORIUM',ox-67,oy+13*scale,'#69859d',11);
 }
 // Seat rows are physical barriers: points are organized by row and block.
 for(const sec of g.sections){if(sec.floor!==floor)continue;
  for(let k=0;k<sec.rows;k++){
   const r=sec.firstR+k*sec.step;
   const aisles=[.02,...g.aisleAngles,.98].map(v=>v*PI);
   for(let i=0;i<aisles.length-1;i++){
    const lo=aisles[i]+g.aisleHalfWidth/r,hi=aisles[i+1]-g.aisleHalfWidth/r;
    if(hi>lo)ringline(r,lo,hi,'#48637b',2.4);
   }
  }
 }
 // Open aisles: a translucent corridor without a center divider.
 const aisleMax=floor===0?g.auditoriumR:g.balconyR;
 for(const angleFrac of g.aisleAngles){const theta=angleFrac*PI;
  ring(6.2,aisleMax,theta-.008,theta+.008,'#375b72');
  for(const edge of [-1,1]){
   let r0=floor===0?6.3:15.7,r1=aisleMax,a=G.point(r0,theta+edge*g.aisleHalfWidth/r0,g),b=G.point(r1,theta+edge*g.aisleHalfWidth/r1,g);
   line(a,b,'#6688a0',.7)
  }
 }
 // Individual empty seats rendered at authentic *inventory* coordinates, not random points.
 for(const s of engine.seats){if(s.floor!==floor)continue;const [x,y]=pt(s);ctx.fillStyle='#557186';ctx.fillRect(x-1.25,y-1.25,2.5,2.5)}
 for(const p of engine.portals){if(p.floor!==floor)continue;const [x,y]=pt(p);
  const isExit=p.type==='exit',isStairs=p.type==='stairs';ctx.beginPath();ctx.arc(x,y,isExit?5.2:4.3,0,2*PI);
  ctx.fillStyle=!p.enabled?'#e66d76':isExit?'#6fe3ba':isStairs?'#b19bfa':'#f8bc75';ctx.fill();
  text(p.id,x+7,y+3,p.enabled?'#cee2ef':'#ffaeb6',10);
 }
 for(const a of engine.agents){if(a.floor!==floor||a.exited)continue;const [x,y]=pt(a);
  ctx.beginPath();ctx.arc(x,y,Math.max(1.9,a.radius*scale),0,2*PI);
  ctx.fillStyle=a.region==='row'?'#f2b76a':a.region==='aisle'?'#7bd2ef':a.region==='foyer'?'#b7a5fd':a.region==='balcony-rim'?'#8ad6bd':'#63dfc4';ctx.fill();
  if(selected===a.id){ctx.strokeStyle='#fff';ctx.lineWidth=2.4;ctx.stroke()}
 }
 if(selected!==null){const a=engine.agents[selected];if(a?.floor===floor&&!a.exited){const [x,y]=pt(a);ctx.beginPath();ctx.arc(x,y,8,0,PI*2);ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke();}}
 return {scale,ox,oy};
}
window.BaileyViewer={draw};
})();
