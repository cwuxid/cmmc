"""Optional illuminated shortest-route network with CONSTANT utility influence.

LEDs are wayfinding cues, not bodies or accelerations. Continuous strip
coverage along the modeled walking network is assumed; no photometry or
distance-to-strip exposure law is fitted. Only the next local target is revealed.
"""
import math

from . import geometry as G
from .crowd_routes import RouteGraph
from .records import Record,record,finite

DEFAULTS=dict(enabled=False,strength=12.,adaptive=True,showStrips=True)


def options(world):
    supplied=world.get('ledStrips',{})
    if not isinstance(supplied,dict): raise ValueError('ledStrips must be an object.')
    config=record(DEFAULTS);config.update(record(supplied))
    for name in ('enabled','adaptive','showStrips'):
        if type(config[name])is not bool: raise ValueError(f'ledStrips.{name} must be boolean.')
    if not finite(config.strength) or config.strength<0:
        raise ValueError('ledStrips.strength must be finite and nonnegative (utility units).')
    return config


def arc_points(g,r,start,end,spacing=.6):
    steps=max(1,math.ceil(abs(end-start)*r/spacing))
    return [G.point(r,start+(end-start)*j/steps,g) for j in range(steps+1)]


def region_path(g,region,a,b):
    """Display the graph metric without drawing a chord through its inner disk."""
    bounds=g.regions[region]
    if bounds.kind=='rectangle': return [record(a),record(b)]
    R=bounds.minR;r1=max(R,G.radius(a,g));r2=max(R,G.radius(b,g))
    t1,t2=G.polar(a,g),G.polar(b,g)
    alpha,beta=math.acos(min(1.,R/r1)),math.acos(min(1.,R/r2))
    if abs(t2-t1)<=alpha+beta: return [record(a),record(b)]
    sign=1 if t2>t1 else -1
    return [record(a)]+arc_points(g,R,t1+sign*alpha,t2-sign*beta)+[record(b)]


class LEDGuidance:
    def __init__(self,engine):
        self.engine,self.config=engine,options(engine.config)
        if not engine.plan_layout or getattr(engine.policy,'settings',{}).get('behaviorMode')!='local':
            raise ValueError('LED strips require the current two-plan geometry and local behavior.')
        # Reuse topology/cache if managers are active, without creating any staff.
        crowd=engine.crowd
        self.graph=crowd.graph if crowd and crowd.graph is not None else RouteGraph(engine.g)
        self.blocked=None;self.revision=0;self._paths=None
        for a in engine.agents:
            a.data.led=Record(instruction=None,recommendedDecisions=0,followedDecisions=0,changedChoiceDecisions=0)
        self.before_tick()

    def before_tick(self):
        # Adaptive lighting assumes an instantaneous availability controller.
        # This is controller knowledge, not global closure knowledge for guests.
        if self.blocked is not None and not self.config.adaptive:return
        blocked=frozenset(p.id for p in self.engine.portals if p.evacuationAllowed and not p.enabled)
        if blocked!=self.blocked:
            self.blocked=blocked;self.revision+=1;self._paths=None

    def instruction(self,a,actions):
        state=a.data.led
        state.instruction=None
        # Zero removes both bonus and information effects, useful as a control.
        if self.config.strength==0:return None
        # Physical strips are a shared field. A guest's private knowledge must
        # not silently redraw the installed directions for that person alone.
        trial=Record(a,data=Record(a.data,knownBlocked=[]))
        raw=self.engine.policy.local.available_actions(trial,self.engine.context(trial))
        route=self.graph.recommend(trial,raw,self.blocked)
        # Static strips may become stale. A guest who already knows their
        # indicated route is blocked ignores that instruction; no secret update.
        if route and route.actionId in {action.id for action in actions} and not any(p in a.data.knownBlocked for p in route.portals):
            state.instruction=record(route)
        return state.instruction

    def bonus(self,a,action):
        route=a.data.led.instruction
        return self.config.strength if route and action.id==route.actionId else 0.

    def display_paths(self):
        """Cached reference strips: graph continuations, aisles and row branches.

        Cross-floor stair transfers are never joined by a planar line. Curves
        use the same annular geometry as route costs. This display is read-only
        with respect to agents, RNG, closures and decisions.
        """
        if self._paths is not None:return self._paths
        e=self.engine;g=e.g;paths=[]
        distances,_,following=self.graph.field(self.blocked)
        for start,(end,gate) in following.items():
            a,b=self.graph.nodes[start],self.graph.nodes[end]
            if a.floor!=b.floor or G.distance(a,b)<1e-8:continue
            points=(region_path(g,a.region,a,b) if a.region==b.region and a.region in g.regions
                    else [record(a),record(b)])
            paths.append(Record(floor=a.floor,points=points,kind='network'))
        for zone,spec in g.zones.items():
            for j,fraction in enumerate(g.aisleAngles):
                if not math.isfinite(distances[self.graph.ends[(zone,j)]]):continue
                angle=fraction*math.pi
                paths.append(Record(floor=spec.floor,points=[G.point(spec.minR,angle,g),G.point(spec.maxR,angle,g)],kind='aisle'))
        branches={}
        for seat in e.seats:
            route=self.graph.seat_route(seat,self.blocked).route
            if route is None:continue
            key=(seat.section,seat.row,seat.block,route.actionId)
            if key not in branches:branches[key]=[seat,seat.angle]
            elif route.actionId=='ROW_LEFT':branches[key][1]=max(branches[key][1],seat.angle)
            else:branches[key][1]=min(branches[key][1],seat.angle)
        for (_,_,_,identity),(seat,angle) in branches.items():
            # Include the row-to-aisle-centre attachment used by the graph.
            end=seat.leftAisle if identity=='ROW_LEFT' else seat.rightAisle
            paths.append(Record(floor=seat.floor,points=arc_points(g,seat.r,angle,end),kind='row'))
        self._paths=paths
        return paths

    def summary(self):
        states=[a.data.led for a in self.engine.agents]
        offered=sum(s.recommendedDecisions for s in states)
        followed=sum(s.followedDecisions for s in states)
        return dict(enabled=True,strength=self.config.strength,influence='constant utility bonus',
                    adaptive=self.config.adaptive,controllerBlocked=sorted(self.blocked),
                    recommendedDecisions=offered,followedDecisions=followed,
                    changedChoiceDecisions=sum(s.changedChoiceDecisions for s in states),
                    adherence=followed/offered if offered else None)

    def export(self):
        return record(dict(settings=self.config,summary=self.summary(),
                           graph=dict(nodes=len(self.graph.nodes),edges=sum(map(len,self.graph.edges.values())))))
