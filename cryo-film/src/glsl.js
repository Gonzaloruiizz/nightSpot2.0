// Shared GLSL snippets (prefixed to avoid clashes with three.js chunks)
export const NOISE = /* glsl */`
vec3 nz_m289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 nz_m289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 nz_perm(vec4 x){return nz_m289(((x*34.0)+10.0)*x);}
vec4 nz_tis(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
  i=nz_m289(i);
  vec4 p=nz_perm(nz_perm(nz_perm(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=nz_tis(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(0.5-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
  return 105.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
float fbm3(vec3 p){ float a=0.5,s=0.0; for(int i=0;i<4;i++){ s+=a*snoise(p); p=p*2.03+vec3(1.7,9.2,3.1); a*=0.5;} return s; }
vec3 nz_hash3(vec3 p){ p=vec3(dot(p,vec3(127.1,311.7,74.7)),dot(p,vec3(269.5,183.3,246.1)),dot(p,vec3(113.5,271.9,124.6))); return fract(sin(p)*43758.5453123); }
// x: F1, y: F2, z: cell random
vec3 voronoi3(vec3 x){
  vec3 p=floor(x); vec3 f=fract(x); float f1=8.0,f2=8.0,id=0.0;
  for(int k=-1;k<=1;k++)for(int j=-1;j<=1;j++)for(int i=-1;i<=1;i++){
    vec3 b=vec3(float(i),float(j),float(k)); vec3 hh=nz_hash3(p+b); vec3 r=b-f+hh; float d=dot(r,r);
    if(d<f1){f2=f1;f1=d;id=hh.x;} else if(d<f2){f2=d;}
  }
  return vec3(sqrt(f1),sqrt(f2),id);
}
`;

// Mikkelsen-style bump: perturb normal using screen-space derivatives of a height (in view units)
export const BUMP = /* glsl */`
vec3 bumpNormal(vec3 surfPos, vec3 surfNorm, float h, float fd){
  vec3 sx=dFdx(surfPos), sy=dFdy(surfPos);
  vec3 r1=cross(sy,surfNorm), r2=cross(surfNorm,sx);
  float det=dot(sx,r1)*fd;
  vec3 grad=sign(det)*(dFdx(h)*r1+dFdy(h)*r2);
  return normalize(abs(det)*surfNorm-grad);
}
`;
