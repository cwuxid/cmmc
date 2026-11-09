/* Small seeded RNG; every random draw flows through this object. */
(function(){
class RNG {
  constructor(seed=2026){this.s=seed>>>0||1;this.spare=null}
  uniform(){let t=this.s+=0x6D2B79F5;t=Math.imul(t^(t>>>15),t|1);t^=t+Math.imul(t^(t>>>7),t|61);return ((t^(t>>>14))>>>0)/4294967296}
  normal(){if(this.spare!==null){let z=this.spare;this.spare=null;return z}let u=Math.max(1e-12,this.uniform()),r=Math.sqrt(-2*Math.log(u)),a=2*Math.PI*this.uniform();this.spare=r*Math.sin(a);return r*Math.cos(a)}
  gamma(k){if(k<1)return this.gamma(k+1)*Math.pow(Math.max(this.uniform(),1e-12),1/k);let d=k-1/3,c=1/Math.sqrt(9*d);for(let i=0;i<1000;i++){let x=this.normal(),v=1+c*x;if(v<=0)continue;v=v*v*v;let u=this.uniform();if(u<1-.0331*x*x*x*x||Math.log(Math.max(u,1e-14))<.5*x*x+d*(1-v+Math.log(v)))return d*v}return k}
  sample(p){const m=+p.mean,s=Math.max(0,+p.sd||0);if(s<1e-10)return m;let value;
    if(p.type==='beta'){const v=Math.max(0.02,m*(1-m)/(s*s)-1),a=Math.max(.15,m*v),b=Math.max(.15,(1-m)*v),x=this.gamma(a),y=this.gamma(b);value=x/(x+y)}
    else if(p.type==='lognormal'){const q=Math.log(1+(s/m)**2);value=Math.exp(Math.log(m)-q/2+Math.sqrt(q)*this.normal())}
    else value=m+s*this.normal();
    if(Number.isFinite(p.min))value=Math.max(p.min,value);if(Number.isFinite(p.max))value=Math.min(p.max,value);
    return value;
  }
  shuffle(items){for(let i=items.length-1;i>0;i--){const j=Math.floor(this.uniform()*(i+1));[items[i],items[j]]=[items[j],items[i]]}return items}
}
window.BaileyRNG=RNG;
})();
