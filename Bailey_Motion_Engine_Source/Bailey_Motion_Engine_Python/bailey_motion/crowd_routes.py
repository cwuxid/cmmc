"""Directed distance graph shared by OPTIONAL manager and student modes.

Units are metres. Vertices resolve aisle ends, portal departures and named
landings. Curved rows attach through their two legal ends. Region edges are
shortest centre paths in the declared schematic region, NOT surveyed distances
or predictions of force-driven trajectories. An enabled optional mode builds
this graph; ordinary behavioral decisions continue to use their existing model.
"""
import heapq
import math
from collections import OrderedDict

from . import geometry as G
from .records import Record, record


def region_distance(g, region, a, b):
    """Exact centre geodesic in a current annular sector, or a rectangle.

    If the chord intersects the inner disk, two tangents and an inner arc give
    sqrt(r1²-R²)+sqrt(r2²-R²)+R*(delta-acos(R/r1)-acos(R/r2)).
    Current sectors have width <= pi. Their minor geodesic stays in the sector
    and within the outer disk. Annular bounds already constrain body CENTRES.
    Rectangle exit endpoints are allowed on the declared threshold apron.
    """
    bounds = g.regions[region]
    if bounds.kind == "rectangle": return G.distance(a,b)
    r1,r2,R = G.radius(a,g),G.radius(b,g),bounds.minR
    if min(r1,r2) < R-1e-7: raise ValueError(f"Routing point inside {region}'s inner disk.")
    # hypot(p(R,theta)) can differ from R by an ulp. Near a tangent, sqrt
    # and acos amplify that error; snap nanometre-scale boundary roundoff.
    if abs(r1-R) <= 1e-10*max(1.,R): r1=R
    if abs(r2-R) <= 1e-10*max(1.,R): r2=R
    delta = abs(G.polar(a,g)-G.polar(b,g))
    alpha,beta = math.acos(min(1.,R/r1)),math.acos(min(1.,R/r2))
    if delta <= alpha+beta: return G.distance(a,b)
    return math.sqrt(max(0.,r1*r1-R*R))+math.sqrt(max(0.,r2*r2-R*R))+R*(delta-alpha-beta)


class RouteGraph:
    """Static topology; at most 64 cached reverse-Dijkstra knowledge states.

    Closure keys are explicit KNOWN portal IDs. No engine.enabled lookup is
    permitted here, so route selection cannot reveal an unknown obstruction.
    """
    def __init__(self,g):
        self.g = g
        self.portals = {p.id:p for p in g.portals if p.evacuationAllowed}
        self.nodes,self.edges,self.reverse,self.ends = {},{},{},{}
        self.cache = OrderedDict()
        for p in self.portals.values():
            self.node('P:'+p.id,Record(p,region=p['from'],zone=p.get('sourceZone')))
        for name,e in g.entrances.items(): self.node('E:'+name,record(e))
        for zone,spec in g.zones.items():
            for j,fraction in enumerate(g.aisleAngles):
                angle = fraction*math.pi
                name = f'A:{zone}:{j}'
                point = Record(G.point(spec.maxR,angle,g),floor=spec.floor,region='aisle',zone=zone)
                self.node(name,point); self.ends[(zone,j)] = name
                if spec.outerRegion == 'access':
                    p = next(p for p in self.portals.values() if p.type=='access' and abs(p.angle-angle)<1e-8)
                    self.edge(name,'P:'+p.id,G.distance(point,p))
                else:
                    rim = f'R:{zone}:{j}'
                    self.node(rim,Record(point,region=spec.outerRegion,zone=None))
                    self.edge(name,rim,0.)
        for name,e in g.entrances.items():
            if e.region == 'aisle':
                self.edge('E:'+name,self.ends[(e.zone,self.aisle_index(e.aisleAngle))],
                          abs(G.radius(e,g)-g.zones[e.zone].maxR))
        groups = {}
        for name,p in self.nodes.items():
            if p.region in g.regions: groups.setdefault((p.floor,p.region),[]).append(name)
        for (_,region),names in groups.items():
            for j,a in enumerate(names):
                for b in names[j+1:]:
                    length = region_distance(g,region,self.nodes[a],self.nodes[b])
                    self.edge(a,b,length); self.edge(b,a,length)
        for p in self.portals.values():
            if p.type != 'exit':
                e = g.entrances[p.toEntrance]
                length = p.length if p.type in ('access','stairs') else G.distance(p,e)
                self.edge('P:'+p.id,'E:'+e.id,length,p.id)

    def node(self,name,p):
        self.nodes[name]=p; self.edges[name]=[]; self.reverse[name]=[]

    def edge(self,a,b,length,portal=None):
        if not math.isfinite(length) or length<0: raise ValueError('Invalid graph edge length.')
        self.edges[a].append((b,length,portal)); self.reverse[b].append((a,length,portal))

    def aisle_index(self,angle):
        return min(range(len(self.g.aisleAngles)),key=lambda j:abs(self.g.aisleAngles[j]*math.pi-angle))

    def field(self,blocked=()):
        key=frozenset(blocked)
        if key in self.cache:
            self.cache.move_to_end(key); return self.cache[key]
        d={n:math.inf for n in self.nodes}; exits={}; following={}; heap=[]
        for p in sorted(self.portals.values(),key=lambda p:p.id):
            if p.type=='exit' and p.id not in key:
                name='P:'+p.id; d[name]=0.; exits[name]=p.id
                heapq.heappush(heap,(0.,p.id,name))
        while heap:
            distance,exit_id,name=heapq.heappop(heap)
            if distance!=d[name] or exit_id!=exits[name]: continue
            for previous,length,gate in self.reverse[name]:
                if gate in key: continue
                candidate=distance+length
                # Strict improvement avoids cycles on zero-length region links.
                # Sorted exit seeds/adjacency give deterministic equal-cost ties.
                if candidate<d[previous]-1e-10:
                    d[previous]=candidate; exits[previous]=exit_id; following[previous]=(name,gate)
                    heapq.heappush(heap,(candidate,exit_id,previous))
        self.cache[key]=(d,exits,following)
        if len(self.cache)>64: self.cache.popitem(last=False)
        return d,exits,following

    def action_route(self,a,action,blocked=()):
        """Force the proposed first action, THEN append its shortest continuation.

        A portal marker is not a waypoint that may be visited and bypassed:
        committing to it includes its actual transfer edge. This distinction
        prevents a cheap downstream exit from crediting an unrelated doorway.
        """
        prefix=[]; start=None
        if action.kind=='row':
            angle=a.seat.leftAisle if action.id=='ROW_LEFT' else a.seat.rightAisle
            start=self.ends[(a.seat.section,self.aisle_index(angle))]
            local=action.distance+self.g.aisleHalfWidth+abs(self.g.zones[a.seat.section].maxR-a.seat.r)
        elif action.kind=='aisle':
            start=self.ends[(a.zone,self.aisle_index(a.aisleAngle))]; local=action.distance
        elif action.kind=='portal':
            p=self.portals[action.id]; prefix=[p.id]
            if p.id in blocked: return None
            local=(region_distance(self.g,a.region,a,p) if a.region in self.g.regions else
                   abs(G.radius(a,self.g)-G.radius(p,self.g))+G.radius(a,self.g)*abs(G.polar(a,self.g)-p.angle))
            if p.type=='exit': return Record(actionId=action.id,distance=local,exitId=p.id,portals=prefix)
            start='E:'+p.toEntrance
            local+=next(length for end,length,gate in self.edges['P:'+p.id] if gate==p.id)
        else: return None
        d,exits,following=self.field(blocked)
        if not math.isfinite(d[start]): return None
        path=list(prefix); current=start; seen=set()
        while current in following:
            if current in seen: raise RuntimeError('Route predecessor cycle.')
            seen.add(current); current,gate=following[current]
            if gate: path.append(gate)
        exit_id=exits[start]
        if not path or path[-1]!=exit_id: path.append(exit_id)
        return Record(actionId=action.id,distance=local+d[start],exitId=exit_id,portals=path)

    def recommend(self,a,actions,blocked=()):
        routes=[r for action in actions if (r:=self.action_route(a,action,blocked)) is not None]
        return min(routes,key=lambda r:(r.distance,r.exitId,r.actionId)) if routes else None

    def seat_route(self,s,blocked=()):
        actions=[Record(kind='row',id=identity,distance=abs(s.angle-angle-sign*self.g.aisleHalfWidth/s.r)*s.r)
                 for identity,angle,sign in (('ROW_LEFT',s.leftAisle,1),('ROW_RIGHT',s.rightAisle,-1))]
        a=Record(seat=s,x=s.x,y=s.y,floor=s.floor,region='row',zone=s.section)
        route=self.recommend(a,actions,blocked)
        return Record(seatLabel=s.label,route=route)
