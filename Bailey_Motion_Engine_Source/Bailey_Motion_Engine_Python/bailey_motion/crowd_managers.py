"""Optional six-manager experiment: physical staff, information and utility.

Settings live in a separate opt-in JSON, not in default behavioral settings.
Knowledge of a closure and physical closure are different states. Staff do not
count as audience, moving peers, or extra RNG draws. See CROWD_MANAGERS.tex.
"""
import math

from . import geometry as G, perception, plans
from .crowd_routes import RouteGraph
from .records import Record, record, finite

DEFAULTS=dict(enabled=False,count=6,positions=[],strength=12.,decayLength=8.,
              communicationRange=12.,memorySeconds=60.,managerRadius=.2025,
              requireBothFloors=True,showCoverage=False,closures=[])


def options(world):
    supplied=world.get('crowdManagers',{})
    if not isinstance(supplied,dict): raise ValueError('crowdManagers must be an object.')
    c=record(DEFAULTS); c.update(record(supplied))
    if type(c.count) is not int or c.count!=6: raise ValueError('Exactly six managers are required.')
    for key in ('enabled','requireBothFloors','showCoverage'):
        if type(c[key]) is not bool: raise ValueError(f'crowdManagers.{key} must be boolean.')
    for key in ('strength','decayLength','communicationRange','memorySeconds','managerRadius'):
        if not finite(c[key]) or c[key]<=0: raise ValueError(f'Invalid crowdManagers.{key}.')
    if not isinstance(c.positions,list) or any(not isinstance(p,str) for p in c.positions):
        raise ValueError('positions must be a list of candidate IDs.')
    if c.positions and (len(c.positions)!=6 or len(set(c.positions))!=6):
        raise ValueError('Supply six distinct candidate IDs, or [] for automatic initialization.')
    if not isinstance(c.closures,list): raise ValueError('closures must be a list.')
    return c


def candidates(g,seats,radius=.2025):
    """A finite placement domain: clear points in circulation/aisles/foyer.

    This discretizes STAFF PLACEMENT, not pedestrian movement. Exclude seats,
    portal approaches, barrier walls and overly narrow aisle positions.
    """
    sites={}
    def add(name,floor,region,point,**extra):
        site=Record(point,id=name,floor=floor,region=region,**extra)
        trial=Record(site,radius=radius,seat=Record(r=0.))
        if not plans.inside_region(trial,site.x,site.y,g): return
        if any(p.floor==floor and G.distance(site,p)<.85+radius for p in g.portals): return
        if any(s.floor==floor and G.distance(site,s)<radius+.2025+.08 for s in seats): return
        sites[name]=site
    for region in ('rim','corridor','balcony-rim'):
        b=g.regions[region]
        for k,fraction in enumerate((.35,.7)):
            for j in range(12):
                theta=math.pi*(b.minAngle+(b.maxAngle-b.minAngle)*(j+.5)/12)
                add(f'{region}:{k}:{j}',b.floor,region,G.point(b.minR+fraction*(b.maxR-b.minR),theta,g))
    for zone,b in g.zones.items():
        for j,fraction in enumerate(g.aisleAngles):
            angle=fraction*math.pi
            for k,depth in enumerate((.3,.65)):
                add(f'aisle:{zone}:{j}:{k}',b.floor,'aisle',G.point(b.minR+depth*(b.maxR-b.minR),angle,g),
                    zone=zone,aisleAngle=angle)
    for j,x in enumerate((-9.,-5.,0.,5.,9.)):
        for k,y in enumerate((35.,38.)): add(f'foyer:{j}:{k}',0,'foyer',Record(x=x,y=y))
    return sites


def signal(a,m,g,portals,c):
    """q in [0,1]: same floor, finite range, wall occlusion, exp(-d/ell)."""
    if a.floor!=m.floor: return 0.
    d=G.distance(a,m)
    if d>c.communicationRange or not perception.line_of_sight(a,m,g,portals): return 0.
    return math.exp(-d/c.decayLength)


def valid_layout(ids,sites,c):
    if len(ids)!=6 or len(set(ids))!=6 or any(p not in sites for p in ids): return False
    if c.requireBothFloors and {sites[p].floor for p in ids}!={0,1}: return False
    return all(sites[a].floor!=sites[b].floor or G.distance(sites[a],sites[b])>=2*c.managerRadius+.08
               for j,a in enumerate(ids) for b in ids[j+1:])


def initial_layout(sites,seats,g,c):
    """Greedy sum_i max_m q_im initialization, NOT the evacuation objective.

    Geometric clusters/coverage provide a starting point. Simulated clearance
    time, including queues and staff obstruction, ranks optimizer candidates.
    Profiles use all seats so initialization does not know random occupancy.
    """
    ids=sorted(sites)
    open_portals=[Record(p,enabled=p.evacuationAllowed) for p in g.portals]
    profiles={p:[signal(s,sites[p],g,open_portals,c) for s in seats] for p in ids}
    chosen=[]; best=[0.]*len(seats)
    for step in range(6):
        floor=step if step<2 and c.requireBothFloors else None
        available=[p for p in ids if p not in chosen and (floor is None or sites[p].floor==floor)
                   and all(sites[p].floor!=sites[q].floor or G.distance(sites[p],sites[q])>=2*c.managerRadius+.08 for q in chosen)]
        if not available: raise ValueError('Insufficient compatible manager candidates.')
        winner=min(available,key=lambda p:(-sum(max(0.,v-b) for v,b in zip(profiles[p],best)),p))
        chosen.append(winner); best=[max(b,v) for b,v in zip(best,profiles[winner])]
    return sorted(chosen)


class CrowdSystem:
    def __init__(self,e,managers_enabled=None):
        self.engine,self.config=e,options(e.config)
        if managers_enabled is not None:
            self.config.enabled=managers_enabled
        if not e.plan_layout or getattr(e.policy,'settings',{}).get('behaviorMode')!='local':
            raise ValueError('Crowd-manager experiments require current geometry and local behavior.')
        self.managers=[]; self.graph=None; self.seat_routes=[]; self.assignments={}; self.events=[]
        self.peakQueues={}
        for event in self.config.closures:
            if not isinstance(event,dict): raise ValueError('A closure must be an object.')
            when,delay,gate=event.get('at',0.),event.get('notifyAfter'),event.get('portalId')
            if not finite(when) or when<0 or (delay is not None and (not finite(delay) or delay<0)):
                raise ValueError('Closure at/notifyAfter must be nonnegative seconds; null means no broadcast.')
            if gate not in e.portal_map or not e.portal_map[gate].evacuationAllowed:
                raise ValueError(f'Unknown/excluded closure portal: {gate}')
            if any(x.portalId==gate for x in self.events): raise ValueError('Duplicate permanent closure.')
            self.events.append(Record(portalId=gate,at=when,notifyAfter=delay,applied=False,appliedAt=None))
        if self.config.enabled:
            self.graph=RouteGraph(e.g)
            self.sites=candidates(e.g,e.seats,self.config.managerRadius)
            ids=self.config.positions or initial_layout(self.sites,e.seats,e.g,self.config)
            if not valid_layout(ids,self.sites,self.config): raise ValueError('Invalid six-manager placement.')
            self.config.positions=list(ids)
            for j,name in enumerate(ids):
                p=self.sites[name]
                self.managers.append(Record(p,id=-j-1,managerId=f'CM{j+1}',candidateId=name,
                                            standingRegion=p.region,region='manager',radius=self.config.managerRadius,
                                            vx=0.,vy=0.,exited=False,knownBlocked=[],data=Record(portal=None)))
            self.seat_routes=[self.graph.seat_route(s) for s in e.seats]
            by_seat={r.seatLabel:r.route for r in self.seat_routes}
            for s in e.seats:
                same=[m for m in self.managers if m.floor==s.floor] or self.managers
                m=min(same,key=lambda m:(-signal(s,m,e.g,e.portals,self.config),G.distance(s,m),m.managerId))
                self.assignments[s.label]=m.managerId
            for a in e.agents:
                a.data.guidance=Record(responsibleManager=self.assignments[a.seat.label],responsiveness=1.,
                                       initialRoute=record(by_seat[a.seat.label]),memory=None,received=0,
                                       recommendedDecisions=0,followedDecisions=0,changedChoiceDecisions=0)
        self.before_tick()

    def before_tick(self):
        e=self.engine
        # Observable queue proxy, not a pressure/density safety measure. Use
        # previous completed observation state at this tick boundary.
        queues={}
        for a in e.agents:
            target=a.data.get('queueTarget')
            if not a.exited and a.floor>=0 and target in e.portal_map and \
               math.hypot(a.vx,a.vy)<=e.policy.settings.queueSpeedThreshold and \
               G.distance(a,e.portal_map[target])<=e.policy.settings.queueObservationDistance:
                queues[target]=queues.get(target,0)+1
        for target,count in queues.items(): self.peakQueues[target]=max(count,self.peakQueues.get(target,0))
        for event in self.events:
            if not event.applied and e.t+1e-9>=event.at:
                e.portal_map[event.portalId].enabled=False
                event.applied=True; event.appliedAt=e.t
        for m in self.managers:
            known=set(m.knownBlocked)
            for event in self.events:
                if event.applied and event.notifyAfter is not None and e.t+1e-9>=event.at+event.notifyAfter:
                    known.add(event.portalId)
            for p in e.portals:
                if p.evacuationAllowed and p.floor==m.floor and not p.enabled and \
                   G.distance(m,p)<=e.policy.settings.discoveryRadius and perception.line_of_sight(m,p,e.g,e.portals):
                    known.add(p.id)
            m.knownBlocked=sorted(known)

    def receive(self,a,actions,stage):
        """Prefer the original assigned manager among receivable instructions.

        If that manager cannot be heard, use the strongest receivable signal.
        Fallback never changes the seat's original manager assignment.
        Staff use a shared routing rule with their own knowledge; no speech
        throughput or individualized conversation delay is modeled.
        """
        if not self.managers: return None
        e=self.engine; state=a.data.guidance
        heard=[(signal(a,m,e.g,e.portals,self.config),m) for m in self.managers]
        heard=[(q,m) for q,m in heard if q>0]
        if heard:
            q,m=min(heard,key=lambda pair:(pair[1].managerId!=state.responsibleManager,
                                          -pair[0],pair[1].managerId))
            # A guest may report a discovered blockage to the manager they hear.
            m.knownBlocked=sorted(set(m.knownBlocked)|set(a.data.knownBlocked))
            a.data.knownBlocked=sorted(set(a.data.knownBlocked)|set(m.knownBlocked))
            route=self.graph.recommend(a,actions,a.data.knownBlocked)
            state.memory=(Record(route,managerId=m.managerId,signal=q,receivedAt=e.t,stage=stage,
                                 expiresAt=e.t+self.config.memorySeconds) if route else None)
            state.received+=1
        memory=state.memory
        if memory and (e.t>memory.expiresAt or any(p in a.data.knownBlocked for p in memory.portals)):
            state.memory=memory=None
        if memory and memory.stage!=stage:
            # Follow only already communicated portal IDs, not a newly omniscient
            # global search once staff are out of communication range.
            eligible=[x for x in actions if x.id in memory.portals or x.kind=='aisle']
            if eligible:
                chosen=min(eligible,key=lambda x:memory.portals.index(x.id) if x.id in memory.portals else -1)
                memory.actionId=chosen.id; memory.stage=stage
            else:
                state.memory=memory=None
        return memory

    def bonus(self,a,action):
        memory=a.data.guidance.memory
        if not memory or action.id!=memory.actionId: return 0.
        age=max(0.,self.engine.t-memory.receivedAt)
        return self.config.strength*a.data.guidance.responsiveness*memory.signal*math.exp(-age/self.config.memorySeconds)

    def summary(self):
        e=self.engine; times=sorted(a.exitAt for a in e.agents if a.exited)
        rank=math.ceil(.95*len(e.agents))
        states=[a.data.guidance for a in e.agents if 'guidance' in a.data]
        offered=sum(s.recommendedDecisions for s in states); followed=sum(s.followedDecisions for s in states)
        return dict(enabled=self.config.enabled,count=len(self.managers),managerSelection='assigned-first',
                    time95=times[rank-1] if len(times)>=rank else None,
                    recommendedDecisions=offered,followedDecisions=followed,
                    peopleReached=sum(s.received>0 for s in states),
                    changedChoiceDecisions=sum(s.changedChoiceDecisions for s in states),
                    adherence=followed/offered if offered else None,
                    closures=record(self.events),positions=list(self.config.positions),peakObservedQueues=dict(self.peakQueues))

    def export(self):
        return record(dict(settings=self.config,managers=self.managers,seatAssignments=self.assignments,
                           seatRoutes=self.seat_routes,candidates=list(self.sites.values()) if self.graph else [],
                           graph=dict(nodes=len(self.graph.nodes),edges=sum(map(len,self.graph.edges.values()))) if self.graph else None,
                           summary=self.summary()))
