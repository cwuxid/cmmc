"""Optional familiar-audience policy: minimize remaining GRAPH distance.

Students know the building topology. They do not automatically know unexpected
closures, predict congestion, move faster, or skip physical constraints. This
mode overrides route-choice utility rather than adding a familiarity reward.
"""
from .crowd_routes import RouteGraph
from .records import Record, record


class StudentRouting:
    def __init__(self,engine):
        self.engine=engine
        if not engine.plan_layout or getattr(engine.policy,'settings',{}).get('behaviorMode')!='local':
            raise ValueError('Student mode requires the current geometry and local behavior policy.')
        # Reuse the manager ROUTING IMPLEMENTATION, not staff or instructions.
        # Student mode has no active managers and never reads hidden closures.
        self.graph=RouteGraph(engine.g)
        self.seat_routes=[self.graph.seat_route(s) for s in engine.seats]
        by_seat={item.seatLabel:item.route for item in self.seat_routes}
        for a in engine.agents:
            a.data.student=Record(initialRoute=record(by_seat[a.seat.label]),decisions=0,unreachableDecisions=0)
            # Knowledge concerns locations/connectivity, not availability.
            for p in self.graph.portals.values():
                a.data.knownTargets[p.id]=Record(x=p.x,y=p.y)

    def choose(self,a,api,actions,current_id=None):
        """a* = argmin_a [length to/through a + shortest continuation].

        Ties use (exit ID, action ID), matching the shared manager graph.
        Never score behavioral weights, queue delays, panic or authority here.
        Unreachable alternatives are exported as nulls, not infinities.
        """
        routes={action.id:self.graph.action_route(a,action,a.data.knownBlocked) for action in actions}
        reachable=[route for route in routes.values() if route is not None]
        best=min(reachable,key=lambda r:(r.distance,r.exitId,r.actionId)) if reachable else None
        chosen=next((action for action in actions if best and action.id==best.actionId),None)
        scores=[]
        for action in actions:
            route=routes[action.id]
            scores.append(Record(id=action.id,kind=action.kind,target=record(action.target),
                                 perception=action.get('perception'),reachable=route is not None,
                                 routeDistance=route.distance if route else None,
                                 exitId=route.exitId if route else None,
                                 utility=-route.distance if route else None))
        a.data.student.decisions+=1
        a.data.student.unreachableDecisions+=int(best is None)
        a.data.lastUtility=-best.distance if best else None
        a.data.lastDecision=Record(time=api.t,stage=f"{a.floor}:{a.region}:{a.get('zone')}",
                                   currentTarget=current_id,selectionMode='student-shortest-distance',
                                   chosen=chosen.id if chosen else None,
                                   chosenExit=best.exitId if best else None,
                                   remainingRouteDistance=best.distance if best else None,
                                   route=record(best),knownBlocked=list(a.data.knownBlocked),
                                   alternatives=scores,globalCrowdTerm=0.)
        return chosen

    def summary(self):
        return dict(enabled=True,policy='student-shortest-distance',population=len(self.engine.agents),
                    decisions=sum(a.data.student.decisions for a in self.engine.agents),
                    unreachableDecisions=sum(a.data.student.unreachableDecisions for a in self.engine.agents),
                    closureKnowledge='local discovery; no crowd managers')

    def export(self):
        return record(dict(summary=self.summary(),seatRoutes=self.seat_routes,
                           graph=dict(nodes=len(self.graph.nodes),edges=sum(map(len,self.graph.edges.values())))))
