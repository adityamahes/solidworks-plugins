"""Involute spur gear outlines (external and internal) as sketch Profiles."""
from __future__ import annotations

import math

from .geometry import Profile, polar


def inv(a: float) -> float:
    return math.tan(a) - a


def toothed_outline(z: int, m: float, alpha: float, r_out: float, r_in: float,
                    s_pitch: float, phase: float = 0.0, n_flank: int = 9, name: str = "") -> Profile:
    """Closed toothed loop.

    Builds z involute "lobes" whose angular centre is phase + 2*pi*k/z. Each lobe
    has chordal thickness s_pitch on the pitch circle and spans r_in..r_out.
      * external gear: lobe = tooth,  r_out = tip,  r_in = root
      * internal gear: lobe = tooth *space* (cavity), r_out = ring root, r_in = ring tip
    """
    r = m * z / 2.0
    rb = r * math.cos(alpha)

    def beta(rho: float) -> float:  # half angular width of the lobe at radius rho
        rho = max(rho, rb)
        return s_pitch / (2 * r) + inv(alpha) - inv(math.acos(rb / rho))

    if beta(r_out) <= 0:
        raise ValueError(f"{name or 'gear'}: lobes come to a point before r={r_out:.3f}; reduce the addendum")
    r_flank0 = max(rb, r_in)
    b_in = beta(r_flank0)
    if 2 * math.pi / z - 2 * b_in <= 0:
        raise ValueError(f"{name or 'gear'}: lobes overlap at r={r_in:.3f}; reduce the dedendum or the module")

    radii = [r_flank0 + (r_out - r_flank0) * (i / (n_flank - 1)) ** 0.8 for i in range(n_flank)]
    prof = Profile(name)
    for k in range(z):
        c = phase + 2 * math.pi * k / z
        nxt = c + 2 * math.pi / z
        right = [polar(rho, c - beta(rho)) for rho in radii]
        left = [polar(rho, c + beta(rho)) for rho in reversed(radii)]
        if r_in < rb:
            prof.line(polar(r_in, c - b_in), right[0])
        prof.spline(right)
        prof.arc((0, 0), right[-1], left[0], ccw=True)
        prof.spline(left)
        if r_in < rb:
            prof.line(left[-1], polar(r_in, c + b_in))
        prof.arc((0, 0), polar(r_in, c + b_in), polar(r_in, nxt - b_in), ccw=True)
    return prof


def external_gear(z, m, alpha, backlash=0.0, ha=1.0, hf=1.25, phase=0.0, name="") -> Profile:
    r = m * z / 2
    return toothed_outline(z, m, alpha, r + ha * m, r - hf * m, math.pi * m / 2 - backlash / 2, phase, name=name)


def internal_gear(z, m, alpha, backlash=0.0, ha=1.0, hf=1.25, phase=0.0, name="") -> Profile:
    """Inner boundary of a ring gear. ha/hf are the ring's own addendum/dedendum."""
    r = m * z / 2
    return toothed_outline(z, m, alpha, r + hf * m, r - ha * m, math.pi * m / 2 + backlash / 2, phase, name=name)


def min_teeth_no_undercut(alpha: float, ha: float = 1.0) -> int:
    return math.ceil(2 * ha / math.sin(alpha) ** 2)
