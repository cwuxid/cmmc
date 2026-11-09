"""The three acceleration terms in the supplied Social Force Component.

Positions are metres and velocities metres/second. These are accelerations
(the manuscript writes dv/dt), so no mass multiplication is applied. Route
choice supplies a local waypoint on the path to the selected egress.
"""
import math

from .records import Record, finite


EPSILON = 1e-12


def comfort_distance(a, settings):
    """r_i: an optional individual trait, otherwise the shared default r_0."""
    value = a.params.get("comfortDistance", settings.comfortDistance)
    if not finite(value) or value <= 0:
        raise ValueError("Individual comfortDistance must be finite and positive.")
    return value


def desired_acceleration(a, waypoint, tau):
    """f_des = (v0 * unit(waypoint - position) - velocity) / tau."""
    dx, dy = waypoint.x - a.x, waypoint.y - a.y
    distance = math.hypot(dx, dy)
    # At the exact waypoint, the unit direction is undefined. Set desired
    # velocity to zero, retaining the relaxation/braking term -v/tau.
    ux, uy = (dx / distance, dy / distance) if distance > EPSILON else (0., 0.)
    v0 = a.params.get("speed", 1.2)
    return Record(x=(v0 * ux - a.vx) / tau, y=(v0 * uy - a.vy) / tau)


def obstacle_acceleration(contacts, strength, r_i):
    """Sum A * exp(-d_iw/r_i) * n_iw for the represented obstacles W.

    A contact provides nonnegative centre-to-surface distance and a unit
    normal from the obstacle toward the pedestrian. Body exclusion remains
    a separate engine constraint; body radius is not subtracted again here.
    """
    ax = ay = 0.
    for contact in contacts:
        magnitude = strength * math.exp(-contact.distance / r_i)
        ax += magnitude * contact.normal.x
        ay += magnitude * contact.normal.y
    return Record(x=ax, y=ay)


def interaction_acceleration(a, neighbors, lam, n, n_prime):
    """Sum the screenshot's direction-sensitive f_ij, with coefficient one.

    x_hat points i -> j, v_ij = v_i - v_j, D = lambda*v_ij + x_hat.
    theta = atan2(cross(D_hat, x_hat), dot(D_hat, x_hat)); N_hat is
    D_hat rotated counterclockwise by 90 degrees. No norms-trait multiplier
    or extra interactionStrength occurs in the supplied equation.
    """
    ax = ay = 0.
    for b in neighbors:
        if b is a or b.get("id") == a.get("id"):
            continue
        if b.get("exited", False) or b.floor != a.floor:
            continue
        rx, ry = b.x - a.x, b.y - a.y
        distance = math.hypot(rx, ry)
        # Coincident positions do not define x_hat. Hard-body mechanics normally
        # prevent them; omit that singular pair rather than inventing a direction.
        if distance <= EPSILON:
            continue
        hx, hy = rx / distance, ry / distance
        dx = lam * (a.vx - b.vx) + hx
        dy = lam * (a.vy - b.vy) + hy
        length = math.hypot(dx, dy)
        # For distance > 0, exp(-distance/|D|) -> 0 as |D| -> 0.
        # Using that limit avoids a fabricated D direction or arbitrary floor.
        if length <= EPSILON:
            continue
        ux, uy = dx / length, dy / length
        nx, ny = -uy, ux
        theta = math.atan2(ux * hy - uy * hx, ux * hx + uy * hy)
        sign = 1 if theta > 0 else -1 if theta < 0 else 0
        attenuation = math.exp(-distance / length)
        longitudinal = math.exp(-(n_prime * theta * length) ** 2)
        lateral = math.exp(-(n * theta * length) ** 2)
        ax -= attenuation * (longitudinal * ux + sign * lateral * nx)
        ay -= attenuation * (longitudinal * uy + sign * lateral * ny)
    return Record(x=ax, y=ay)


def components(a, waypoint, contacts, neighbors, settings):
    """Expose each term and their sum before velocity caps or local steering."""
    desired = desired_acceleration(a, waypoint, settings.relaxationTime)
    r_i = comfort_distance(a, settings)
    obstacle = obstacle_acceleration(contacts, settings.obstacleStrength, r_i)
    interaction = interaction_acceleration(a, neighbors, settings.interactionLambda,
                                          settings.interactionN, settings.interactionNPrime)
    return Record(desired=desired, obstacle=obstacle, interaction=interaction,
                  total=Record(x=desired.x + obstacle.x + interaction.x,
                               y=desired.y + obstacle.y + interaction.y),
                  comfortDistance=r_i, obstacleCount=len(contacts), neighborCount=len(neighbors))


def integrate(a, acceleration, dt):
    """Explicit Euler: v(t+dt) = v(t) + dt * (f_des + f_obs + f_int)."""
    return Record(vx=a.vx + dt * acceleration.x, vy=a.vy + dt * acceleration.y)
