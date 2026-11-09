"""The source RNG, including its cached Gaussian and bounded distribution sampling.

This deliberately preserves the JavaScript generator and random draw order,
rather than substituting Python's random module. Parameters named sd are
standard deviations, unlike the older square-room model's variance argument.
"""
import math

from .records import finite

MASK = 0xFFFFFFFF


class RNG:
    def __init__(self, seed=2026):
        # JS stores this accumulator as a Number, including rounding after 2**53.
        self.s = float((int(seed) & MASK) or 1)
        self.spare = None

    def uniform(self):
        # Integer operations are masked to 32 bits to match JS Math.imul/bit shifts,
        # while s remains a floating accumulator like the source JavaScript Number.
        self.s += 0x6D2B79F5
        t = int(self.s) & MASK
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & MASK)) & MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    def normal(self):
        # Box-Muller yields two standard-normal values. Return one and cache the
        # other, so reproducing draw order requires keeping this spare-value state.
        if self.spare is not None:
            value, self.spare = self.spare, None
            return value
        u = max(1e-12, self.uniform())
        radius = math.sqrt(-2 * math.log(u))
        angle = 2 * math.pi * self.uniform()
        self.spare = radius * math.sin(angle)
        return radius * math.cos(angle)

    def gamma(self, k):
        # Shape < 1 is reduced to a shape > 1 case; larger shapes use rejection
        # sampling. The iteration limit and fallback are retained from the source.
        if k < 1:
            return self.gamma(k + 1) * max(self.uniform(), 1e-12) ** (1 / k)
        d = k - 1 / 3
        c = 1 / math.sqrt(9 * d)
        for _ in range(1000):
            x = self.normal()
            v = 1 + c * x
            if v <= 0:
                continue
            v = v * v * v
            u = self.uniform()
            if (u < 1 - .0331 * x * x * x * x or
                    math.log(max(u, 1e-14)) < .5 * x * x + d * (1 - v + math.log(v))):
                return d * v
        return k

    def sample(self, params):
        # Distribution specs use arithmetic mean and sd, not log-space parameters.
        m = float(params["mean"])
        s = max(0, float(params.get("sd", 0) or 0))
        if s < 1e-10:
            # A deterministic parameter consumes no random draws. The source
            # returns early here, before the optional clipping below.
            return m
        if params.get("type") == "beta":
            # Preserve the source's shape floors, even for inconsistent moments.
            v = max(.02, m * (1 - m) / (s * s) - 1)
            a, b = max(.15, m * v), max(.15, (1 - m) * v)
            x, y = self.gamma(a), self.gamma(b)
            value = x / (x + y)
        elif params.get("type") == "lognormal":
            # Convert arithmetic moments to normal moments before exponentiating.
            q = math.log(1 + (s / m) ** 2)
            value = math.exp(math.log(m) - q / 2 + math.sqrt(q) * self.normal())
        else:
            value = m + s * self.normal()
        # Source min/max use clipping, rather than resampling a truncated law.
        if finite(params.get("min")):
            value = max(params["min"], value)
        if finite(params.get("max")):
            value = min(params["max"], value)
        return value

    def shuffle(self, items):
        # Seeded in-place Fisher-Yates. Used both for seat sampling and each tick's
        # agent update order, so changes here affect the entire trajectory.
        for i in range(len(items) - 1, 0, -1):
            j = math.floor(self.uniform() * (i + 1))
            items[i], items[j] = items[j], items[i]
        return items
