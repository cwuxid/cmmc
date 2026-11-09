"""Current connected-plan defaults plus an archived JavaScript-port world.

Topology follows the supplied specification; metric dimensions are provisional.
"""
import json
from pathlib import Path

from .records import record, finite


def default_config():
    # A fresh record is loaded per call. The current JSON declares two connected plans:
    # geometry is in metres, dt/maxSeconds in seconds, and distribution sd is
    # standard deviation. legacy_config() retains the original source geometry.
    return record(json.loads(Path(__file__).with_name("default_world.json").read_text(encoding="utf-8")))


def legacy_config():
    """Original source layout for JavaScript-port regression tests and archived runs."""
    return record(json.loads(Path(__file__).with_name("legacy_world.json").read_text(encoding="utf-8")))


def default_policy_settings():
    # Kept separate from world geometry: weightSigma/weightRho set log-weight
    # covariance; decision/noise intervals set timing; remaining coefficients
    # control utility scaling, discovery, and soft steering accelerations.
    return record(json.loads(Path(__file__).with_name("default_policy_settings.json").read_text(encoding="utf-8")))


def validate_config(config):
    """Validate user input at the CLI/UI boundary, as the original browser does."""
    for key in ("geometry", "distributions", "limits"):
        # The public runners require complete world objects, rather than silently
        # combining an unrelated or partially specified building with this layout.
        if not isinstance(config.get(key), dict):
            raise ValueError(f"World JSON must include a {key} object.")
    total = sum(section["capacity"] for section in config.geometry.sections)
    # Existing seating inventory bounds the population; geometry is not resized
    # automatically when participant count changes in this Bailey model.
    if type(config.get("population")) is not int or not 1 <= config.population <= total:
        raise ValueError(f"Population must be an integer between 1 and {total}.")
    if not finite(config.get("dt")) or not 0 < config.dt <= .4:
        # Match the source UI's timestep bounds. These are input checks, not
        # evidence that every timestep in this interval is physically calibrated.
        raise ValueError("Tick size must be between 0 and 0.4 seconds.")
    if not finite(config.limits.get("maxSeconds")) or config.limits.maxSeconds <= 0:
        raise ValueError("maxSeconds must be finite and positive.")
    if type(config.get("seed")) is not int or not 0 <= config.seed <= 0xFFFFFFFF:
        raise ValueError("Seed must be an unsigned 32-bit integer.")
    from . import plans
    if type(config.get("studentMode", False)) is not bool:
        raise ValueError("studentMode must be true or false.")
    if config.get("studentMode", False) and not plans.active(config.geometry):
        raise ValueError("Student mode requires the current two-plan geometry.")
    if "crowdManagers" in config:
        from .crowd_managers import options
        options(config)
    if "ledStrips" in config:
        from .led_guidance import options as led_options
        led_options(config)
    if plans.active(config.geometry):
        plans.validate(config.geometry)
        arrival = config.get("arrival", {})
        if not isinstance(arrival, dict) or not isinstance(arrival.get("routesBySeat", {}), dict):
            raise ValueError("arrival must contain a routesBySeat object.")
        from . import geometry
        labels = {s.label for s in geometry.build_seats(config.geometry)}
        if any(label not in labels for label in arrival.get("routesBySeat", {})):
            raise ValueError("arrival.routesBySeat contains an unknown seat label.")
    return config
