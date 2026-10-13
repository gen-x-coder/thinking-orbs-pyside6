"""
thinking_orbs.py — PySide6 port of thinking-orbs
https://github.com/gen-x-coder/thinking-orbs-pyside6

Original (React / TypeScript): https://github.com/Jakubantalik/thinking-orbs

Dotted, monochrome 3D "thought orb" loading indicators. This is a 1:1 transcription of
the original TypeScript engine (src/engine/*.ts + src/presets.ts, spec 1.0.0): same
formulas, same presets, same draw order. Verified against the project's own golden
vectors (spec/orbs-golden.json) — every dot and line matches within 1e-4.

Usage:
    from thinking_orbs import ThinkingOrb

    orb = ThinkingOrb(state="searching", size=64)     # 64 or 20 (two tuned designs)
    orb.setState("connecting")
    orb.setTheme("light")       # "auto" (default) | "dark" | "light"
    orb.setSpeed(1.5)           # multiplier on the preset's baked speed
    orb.setPaused(True)

The widget's natural size is `size` x `size` px. Put it in a bigger layout slot (or call
setFixedSize) and it scales the whole drawing uniformly — like CSS-scaling the canvas.

Run this file directly for a demo playground:  python thinking_orbs.py

MIT License. Original design and engine © 2026 Jakub Antalik; PySide6 port © 2026 Lucas Bonsel.
"""

from __future__ import annotations

__version__ = "0.1.0"

import math
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPalette
from PySide6.QtWidgets import QSizePolicy, QWidget

# ---------------------------------------------------------------------------
# core.ts — shared primitives
# ---------------------------------------------------------------------------

PI = math.pi
_sin, _cos, _sqrt, _floor = math.sin, math.cos, math.sqrt, math.floor


def js_round(x: float) -> int:
    """JavaScript Math.round (half rounds up), not Python's banker's rounding."""
    return int(_floor(x + 0.5))


def lerp(a, b, f):
    return a + (b - a) * f


def frac(x):
    return x - _floor(x)


def hashD(a, b):
    """Deterministic hash in [0, 1)."""
    h = _sin(a * 12.9898 + b * 78.233) * 43758.5453
    return h - _floor(h)


def vnoise(x, y):
    """Value noise on a 2D lattice — smooth, deterministic, cheap."""
    xi = _floor(x)
    yi = _floor(y)
    fx = x - xi
    fy = y - yi
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    a = hashD(xi, yi)
    b = hashD(xi + 1, yi)
    c = hashD(xi, yi + 1)
    d = hashD(xi + 1, yi + 1)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy


_GOLDEN = PI * (3 - _sqrt(5))


def fibDir(i, n):
    """Stable directions on a unit sphere (Fibonacci lattice)."""
    y = 1 - (2 * (i + 0.5)) / n
    rad = _sqrt(1 - y * y)
    a = i * _GOLDEN
    return (rad * _cos(a), y, rad * _sin(a))


def angleDelta(a, b):
    return math.atan2(_sin(a - b), _cos(a - b))


def makeProj(yaw, tilt, cx, cy, scale):
    """Shared spin + tilt + orthographic projection."""
    st = _sin(tilt)
    ct = _cos(tilt)
    sy = _sin(yaw)
    cyw = _cos(yaw)

    def pt(x, y, z):
        x1 = x * cyw + z * sy
        z1 = -x * sy + z * cyw
        y1 = y * ct - z1 * st
        z2 = y * st + z1 * ct
        return (cx + x1 * scale, cy - y1 * scale, z2)

    return pt


def radiusScale(size, pow_):
    return (size / 300) ** pow_


# A dot is a list [x, y, z, r, white, a]; a line is [x1, y1, x2, y2, white, a, w].
def finalizeFrame(dots, lines, rMin=None):
    """Drop invisible marks, clamp radii to the mode floor, z-sort far→near."""
    if rMin is None:
        rMin = 0.3
    visible = []
    for d in dots:
        if d[5] < 0.02:
            continue
        if d[3] < rMin:
            d[3] = rMin
        visible.append(d)
    visible.sort(key=lambda d: d[2])  # stable, like JS Array.sort
    return visible, [l for l in lines if l[5] >= 0.02]


def _g(o, k, default):
    v = o.get(k)
    return default if v is None else v


# ---------------------------------------------------------------------------
# orbits.ts — "working"
# ---------------------------------------------------------------------------

def frameOrbits(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.82
    pt = makeProj(t * 0.12, 0.3, cx, cy, 1)
    rs = radiusScale(size, _g(o, "rsPow", 0.6))

    dots = []
    orbitN = _g(o, "orbitN", 12)
    ghostN = _g(o, "ghostN", 40)
    particles = _g(o, "particles", 3)
    ghostR = _g(o, "ghostR", 0.9)
    ghostA = _g(o, "ghostA", 0.5)
    partR = _g(o, "partR", 1.2)
    partRDepth = _g(o, "partRDepth", 1.6)

    for orb in range(orbitN):
        h1 = hashD(orb, 1.7)
        h2 = hashD(orb, 5.2)
        h3 = hashD(orb, 8.9)
        ro = R * (0.45 + 0.52 * h1)
        th = h1 * 2 * PI
        phi = math.acos(2 * h2 - 1)
        nx = _sin(phi) * _cos(th)
        ny = _cos(phi)
        nz = _sin(phi) * _sin(th)
        ux = -ny
        uy = nx
        uz = 0
        ul = max(1e-6, _sqrt(ux * ux + uy * uy))
        ux /= ul
        uy /= ul
        vx = ny * uz - nz * uy
        vy = nz * ux - nx * uz
        vz = nx * uy - ny * ux
        speed = (0.25 + 0.55 * h3) * (1 if h3 > 0.5 else -1)

        for k in range(ghostN):
            a = (k / ghostN) * 2 * PI
            ca, sa = _cos(a), _sin(a)
            px, py, z = pt((ux * ca + vx * sa) * ro, (uy * ca + vy * sa) * ro, (uz * ca + vz * sa) * ro)
            depth = (z / ro + 1) / 2
            dots.append([px, py, z, ghostR * rs, 0.72, ghostA * (0.4 + 0.6 * depth)])

        for m in range(particles):
            a = t * speed + (m / particles) * 2 * PI + h2 * 6
            ca, sa = _cos(a), _sin(a)
            px, py, z = pt((ux * ca + vx * sa) * ro, (uy * ca + vy * sa) * ro, (uz * ca + vz * sa) * ro)
            depth = (z / ro + 1) / 2
            dots.append([px, py, z, (partR + partRDepth * depth) * rs, 0.3 - 0.22 * depth, 1])

    return finalizeFrame(dots, [], o.get("rMin"))


# ---------------------------------------------------------------------------
# lattice.ts — globe ("searching"), rubik ("solving"), wave ("listening")
# ---------------------------------------------------------------------------

def _solveCycle(time_, count, slotDur, rest):
    cyc = 2 * count * slotDur + rest
    tc = math.fmod(time_, cyc)
    amount = [0.0] * count
    active = -1
    if tc < 2 * count * slotDur:
        slot = int(_floor(tc / slotDur))
        p = (tc - slot * slotDur) / slotDur
        cl = min(1, p / 0.7)
        ep = 1 - (1 - cl) ** 3
        if slot < count:
            for i in range(slot):
                amount[i] = 1
            amount[slot] = ep
            active = slot
        else:
            u = 2 * count - 1 - slot
            for i in range(u):
                amount[i] = 1
            amount[u] = 1 - ep
            active = u
    return amount, active


def _applyMoves(x, y, z, moves, amount, active):
    inActive = False
    for i, (axis, lo, hi, ang) in enumerate(moves):
        if amount[i] <= 0:
            continue
        coord = x if axis == 0 else (y if axis == 1 else z)
        if coord < lo or coord >= hi:
            continue
        if i == active:
            inActive = True
        a = ang * amount[i]
        ca = _cos(a)
        sa = _sin(a)
        if axis == 0:
            y2 = y * ca - z * sa
            z = y * sa + z * ca
            y = y2
        elif axis == 1:
            x2 = x * ca + z * sa
            z = -x * sa + z * ca
            x = x2
        else:
            x2 = x * ca - y * sa
            y = x * sa + y * ca
            x = x2
    return x, y, z, inActive


_moves_cache: dict[int, list] = {}


def _makeMoves(count):
    hit = _moves_cache.get(count)
    if hit is not None:
        return hit
    moves = []
    for i in range(count):
        axis = min(2, int(_floor(hashD(i, 2.3) * 3)))
        lo = -1.0 + 0.5 * min(3, int(_floor(hashD(i, 5.9) * 4)))
        d = 1 if hashD(i, 7.7) < 0.5 else -1
        moves.append((axis, lo, lo + 0.5, (d * PI) / 2))
    _moves_cache[count] = moves
    return moves


def frameGlobe(size, t, o):
    spin = 0.5
    cx = cy = size / 2
    radius = (size / 2) * 0.82
    tilt = 0.4 + 0.06 * _sin(t * 0.35)
    pt = makeProj(t * spin, tilt, cx, cy, radius)
    scan = t * (spin + (1.7 - spin) * _g(o, "scanMul", 1))
    rs = radiusScale(size, _g(o, "rsPow", 0.6))
    dimBase = _g(o, "dimBase", 1)
    rBase, rDepth, rBoost = _g(o, "rBase", 0.6), _g(o, "rDepth", 1.7), _g(o, "rBoost", 1)
    inkFar, inkSpan = _g(o, "inkFar", 0.62), _g(o, "inkSpan", 0.54)

    dots = []
    latRings = _g(o, "latRings", 17)
    lonDensity = _g(o, "lonDensity", 44)
    for li in range(latRings + 1):
        lat = -PI / 2 + (li / latRings) * PI
        cosLat = _cos(lat)
        sinLat = _sin(lat)
        lonCount = max(1, js_round(abs(cosLat) * lonDensity))
        for lj in range(lonCount):
            lon = (lj / lonCount) * 2 * PI
            px, py, z = pt(cosLat * _cos(lon), sinLat, cosLat * _sin(lon))
            depth = (z + 1) / 2
            d = angleDelta(lon + t * spin, scan)
            boost = math.exp(-(d * d) / 0.18) * max(0, z)
            dots.append([
                px, py, z,
                (rBase + rDepth * depth + rBoost * boost) * rs,
                inkFar - inkSpan * depth,
                dimBase + (1 - dimBase) * min(1, boost),
            ])
    return finalizeFrame(dots, [], o.get("rMin"))


def frameRubik(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.82
    pt = makeProj(t * 0.55, 0.35 + 0.1 * _sin(t * 0.9), cx, cy, R)
    rs = radiusScale(size, _g(o, "rsPow", 0.6))
    moveCount = _g(o, "moveCount", 14)
    moves = _makeMoves(moveCount)
    amount, active = _solveCycle(t, moveCount, 0.42, 1.2)
    rBase, rDepth, rActive = _g(o, "rBase", 0.6), _g(o, "rDepth", 1.7), _g(o, "rActive", 0.3)
    inkFar, inkSpan = _g(o, "inkFar", 0.62), _g(o, "inkSpan", 0.54)

    dots = []
    latRings = _g(o, "latRings", 15)
    lonDensity = _g(o, "lonDensity", 40)
    for li in range(latRings + 1):
        lat = -PI / 2 + (li / latRings) * PI
        cosLat = _cos(lat)
        sinLat = _sin(lat)
        lonCount = max(1, js_round(abs(cosLat) * lonDensity))
        for lj in range(lonCount):
            lon = (lj / lonCount) * 2 * PI
            x, y, z, inA = _applyMoves(cosLat * _cos(lon), sinLat, cosLat * _sin(lon), moves, amount, active)
            px, py, zr = pt(x, y, z)
            depth = (zr + 1) / 2
            dots.append([
                px, py, zr,
                (rBase + rDepth * depth + (rActive if inA else 0)) * rs,
                inkFar - inkSpan * depth - (0.14 if inA else 0),
                1,
            ])
    return finalizeFrame(dots, [], o.get("rMin"))


def frameWave(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.874
    pt = makeProj(t * 0.18, 0.38, cx, cy, 1)
    rs = radiusScale(size, _g(o, "rsPow", 0.6))
    rBase, rDepth = _g(o, "rBase", 0.6), _g(o, "rDepth", 1.7)

    dots = []
    rings = _g(o, "rings", 15)
    lonDensity = _g(o, "lonDensity", 40)
    for ri in range(rings + 1):
        lat = -PI / 2 + (ri / rings) * PI
        cosLat = _cos(lat)
        sinLat = _sin(lat)
        w = 0.62 * _sin(t * 2.1 - ri * 0.52) + 0.38 * _sin(t * 1.27 + ri * 0.83)
        rr = R * (0.88 + 0.105 * w)
        lonCount = max(1, js_round(abs(cosLat) * lonDensity))
        crest = max(0, w)
        for lj in range(lonCount):
            lon = (lj / lonCount) * 2 * PI
            px, py, z = pt(cosLat * _cos(lon) * rr, sinLat * rr, cosLat * _sin(lon) * rr)
            depth = (z / R + 1) / 2
            dots.append([
                px, py, z,
                (rBase + rDepth * depth) * (1 + 0.4 * crest) * rs,
                0.66 - 0.56 * depth - 0.1 * crest,
                1,
            ])
    return finalizeFrame(dots, [], o.get("rMin"))


# ---------------------------------------------------------------------------
# web.ts — "connecting"
# ---------------------------------------------------------------------------

def frameWeb(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.8 * _g(o, "spread", 1)
    pt = makeProj(t * 0.12, 0.32, cx, cy, R)
    rs = radiusScale(size, _g(o, "rsPow", 0.6))

    nodeN = _g(o, "nodeN", 30)
    thr = _g(o, "thr", 0.72)
    nodeR = _g(o, "nodeR", 1.4)
    nodeRDepth = _g(o, "nodeRDepth", 1.8)
    lineW = max(0.6, _g(o, "lineW", 0.8) * rs)

    nodes = []
    for i in range(nodeN):
        d = fibDir(i, nodeN)
        x = d[0] + 0.3 * (vnoise(i * 0.31 + 9, t * 0.24) - 0.5) * 2
        y = d[1] + 0.3 * (vnoise(i * 0.53 + 27, t * 0.21) - 0.5) * 2
        z = d[2] + 0.3 * (vnoise(i * 0.77 + 55, t * 0.27) - 0.5) * 2
        l = _sqrt(x * x + y * y + z * z)
        nodes.append((x / l, y / l, z / l))

    lines = []
    dots = []
    proj = [pt(*n) for n in nodes]

    for i in range(nodeN):
        ni = nodes[i]
        for j in range(i + 1, nodeN):
            nj = nodes[j]
            dx = ni[0] - nj[0]
            dy = ni[1] - nj[1]
            dz = ni[2] - nj[2]
            dist = _sqrt(dx * dx + dy * dy + dz * dz)
            if dist >= thr:
                continue
            x1, y1, z1 = proj[i]
            x2, y2, z2 = proj[j]
            depth = ((z1 + z2) / 2 + 1) / 2
            lines.append([x1, y1, x2, y2, 0.42, (1 - dist / thr) * (0.3 + 0.55 * depth), lineW])

    for i in range(nodeN):
        px, py, z = proj[i]
        depth = (z + 1) / 2
        pulse = 1 + 0.25 * _sin(t * 1.4 + i * 2.7)
        dots.append([px, py, z, (nodeR + nodeRDepth * depth) * pulse * rs, 0.55 - 0.45 * depth, 1])

    signals = _g(o, "signals", 5)
    for s in range(signals):
        seg = _floor(t * 0.55 + s * 7.31)
        a = int(_floor(hashD(seg, s * 3.1 + 1.7) * nodeN))
        b = int(_floor(hashD(seg, s * 5.7 + 4.2) * nodeN))
        if a == b:
            continue
        f = frac(t * 0.55 + s * 7.31)
        x = lerp(nodes[a][0], nodes[b][0], f)
        y = lerp(nodes[a][1], nodes[b][1], f)
        z = lerp(nodes[a][2], nodes[b][2], f)
        l = max(1e-6, _sqrt(x * x + y * y + z * z))
        px, py, zr = pt(x / l, y / l, z / l)
        depth = (zr + 1) / 2
        dots.append([px, py, zr, (nodeR * 1.5 + nodeRDepth * depth) * rs, 0.05, 0.5 + 0.5 * depth])

    return finalizeFrame(dots, lines, o.get("rMin"))


# ---------------------------------------------------------------------------
# braid.ts — "weaving"
# ---------------------------------------------------------------------------

def frameBraid(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.76
    pt = makeProj(t * 0.4, 0.3, cx, cy, 1)
    rs = radiusScale(size, _g(o, "rsPow", 0.6))

    dots = []
    ghostN = _g(o, "ghostN", 150)
    for i in range(ghostN):
        d = fibDir(i, ghostN)
        px, py, z = pt(d[0] * R, d[1] * R, d[2] * R)
        depth = (z / R + 1) / 2
        dots.append([px, py, z, 0.8 * rs, 0.78, 0.1 + 0.22 * depth])

    strandN = _g(o, "strandN", 52)
    turns = _g(o, "turns", 3)
    rBase, rDepth = _g(o, "rBase", 1.2), _g(o, "rDepth", 1.8)
    for s in range(3):
        phase = (s / 3) * 2 * PI
        for i in range(strandN):
            u = (frac(i / strandN + t * 0.045) * 2 - 1) * 0.96
            surf = _sqrt(max(0, 1 - u * u))
            endFade = min(1, (1 - abs(u)) / 0.1)
            a = u * PI * turns + phase
            weave = 1 + 0.075 * _sin(u * PI * turns * 2 + phase * 2 + t * 0.8)
            rr = surf * R * weave
            px, py, zr = pt(_cos(a) * rr, u * R * weave, _sin(a) * rr)
            depth = (zr / R + 1) / 2
            dots.append([
                px, py, zr,
                (rBase + rDepth * depth) * rs,
                0.55 - 0.45 * depth,
                endFade * (0.45 + 0.55 * depth),
            ])
    return finalizeFrame(dots, [], o.get("rMin"))


# ---------------------------------------------------------------------------
# ribbon.ts — "composing" (ribbon) and "breathing" (ring, faceOn)
# ---------------------------------------------------------------------------

def frameRibbon(size, t, o):
    cx = cy = size / 2
    R = (size / 2) * 0.78
    spin = _g(o, "spin", 1)
    camTilt = 0.3
    pt = makeProj(t * 0.1 * spin, camTilt, cx, cy, 1)
    rs = radiusScale(size, _g(o, "rsPow", 0.6))
    faceOn = bool(o.get("faceOn"))

    dots = []
    ghostN = _g(o, "ghostN", 150)
    for i in range(ghostN):
        d = fibDir(i, ghostN)
        px, py, z = pt(d[0] * R, d[1] * R, d[2] * R)
        depth = (z / R + 1) / 2
        dots.append([px, py, z, 0.8 * rs, 0.78, 0.1 + 0.22 * depth])

    ya = t * 0.24 * spin
    ta = -camTilt if faceOn else 0.55 + 0.3 * _sin(t * 0.18) * spin
    ux = _cos(ya)
    uy = 0
    uz = _sin(ya)
    vx = -uz * _sin(ta)
    vy = _cos(ta)
    vz = ux * _sin(ta)
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx

    wobMul = _g(o, "wobMul", 1)
    wobAmp = 0.23 * wobMul
    baseR = R / (1 + 0.85 * wobAmp) if faceOn else R

    baseLanes = _g(o, "lanes", 5)
    segs = _g(o, "segs", 88)
    lanes = max(1, js_round(baseLanes * _g(o, "bandMul", 1)))
    rBase, rDepth = _g(o, "rBase", 1.1), _g(o, "rDepth", 1.7)
    half = (lanes - 1) / 2
    for w in range(lanes):
        laneOff = (w - half) * 0.075
        edge = abs(w - half) / max(1, half)
        for k in range(segs):
            a = (k / segs) * 2 * PI
            wob = (0.16 * _sin(a * 3 - t * 1.7 + w * 0.22) + 0.07 * _sin(a * 5 + t * 1.1)) * wobMul
            radial = 1 + wob if faceOn else 1
            off = laneOff if faceOn else laneOff + wob
            ca, sa = _cos(a), _sin(a)
            x = ux * ca + vx * sa + nx * off
            y = uy * ca + vy * sa + ny * off
            z = uz * ca + vz * sa + nz * off
            l = _sqrt(x * x + y * y + z * z)
            rr = baseR * radial
            px, py, zr = pt((x / l) * rr, (y / l) * rr, (z / l) * rr)
            depth = (zr / R + 1) / 2
            dots.append([
                px, py, zr,
                (rBase + rDepth * depth) * (1 - 0.25 * edge) * rs,
                0.52 - 0.44 * depth + 0.18 * edge,
                0.4 + 0.6 * depth,
            ])
    return finalizeFrame(dots, [], o.get("rMin"))


# ---------------------------------------------------------------------------
# morph.ts — "shaping"
# ---------------------------------------------------------------------------

def _smoothE(x):
    return x * x * (3 - 2 * x)


def _polyPath(verts):
    V = len(verts)
    L = []
    total = 0.0
    for i in range(V):
        a = verts[i]
        b = verts[(i + 1) % V]
        l = math.hypot(b[0] - a[0], b[1] - a[1])
        L.append(l)
        total += l

    def path(f):
        target = f * total
        i = 0
        while target > L[i] and i < V - 1:
            target -= L[i]
            i += 1
        a = verts[i]
        b = verts[(i + 1) % V]
        ff = min(1, target / L[i]) if L[i] else 0
        return (a[0] + (b[0] - a[0]) * ff, a[1] + (b[1] - a[1]) * ff)

    return path


def _circle(f):
    a = -PI / 2 + f * 2 * PI
    return (_cos(a) * 0.24, _sin(a) * 0.24)


_TRIANGLE = _polyPath([(0.0, -0.26), (0.24, 0.16), (-0.24, 0.16)])
_SQUARE = _polyPath([(0, -0.2), (0.2, -0.2), (0.2, 0.2), (-0.2, 0.2), (-0.2, -0.2)])
_CYCLE = [_circle, _TRIANGLE, _SQUARE]
_HOLD = 1.4
_MORPH = 0.9
_SEG = _HOLD + _MORPH


def frameMorph(size, t, o):
    K = len(_CYCLE)
    tc = math.fmod(t, _SEG * K)
    k = int(_floor(tc / _SEG))
    local = tc - k * _SEG
    m = _smoothE((local - _HOLD) / _MORPH) if local > _HOLD else 0
    sprd = _g(o, "spread", 1)

    pA = _CYCLE[k]
    pB = _CYCLE[(k + 1) % K]
    M = 160
    pts = []
    for i in range(M):
        f = i / M
        a = pA(f)
        b = pB(f)
        pts.append(((a[0] + (b[0] - a[0]) * m) * sprd, (a[1] + (b[1] - a[1]) * m) * sprd))
    L = []
    total = 0.0
    for i in range(M):
        a = pts[i]
        b = pts[(i + 1) % M]
        l = math.hypot(b[0] - a[0], b[1] - a[1])
        L.append(l)
        total += l

    n = max(6, js_round(34 * _g(o, "iconD", 1)))
    re = _g(o, "rDot", 0.021) * 1.35 * sprd
    pulse = 1 + 0.02 * _sin(local * 3.1)

    dots = []
    c2 = size / 2
    seg = 0
    acc = 0.0
    for k2 in range(n):
        target = (k2 / n) * total
        while acc + L[seg] < target and seg < M - 1:
            acc += L[seg]
            seg += 1
        a = pts[seg]
        b = pts[(seg + 1) % M]
        f = min(1, (target - acc) / L[seg]) if L[seg] else 0
        x = (a[0] + (b[0] - a[0]) * f) * pulse
        y = (a[1] + (b[1] - a[1]) * f) * pulse
        dots.append([c2 + x * size, c2 + y * size, 0, max(0.35, re * size), 0.1, 1])
    return finalizeFrame(dots, [], o.get("rMin"))


# ---------------------------------------------------------------------------
# profiles.ts + presets.ts
# ---------------------------------------------------------------------------

_COUNT_PAIRS = [("latRings", "lonDensity"), ("rings", "lonDensity"), ("lanes", "segs")]
_COUNT_KEYS = ["orbitN", "ghostN", "nodeN", "strandN", "signals"]
_RADIUS_KEYS = ["rBase", "rDepth", "rActive", "rDot", "ghostR", "partR", "partRDepth", "nodeR", "nodeRDepth"]


def scaleCounts(opts, scale):
    out = dict(opts)
    done = set()
    rt = _sqrt(scale)
    for a, b in _COUNT_PAIRS:
        va, vb = out.get(a), out.get(b)
        if va is not None and vb is not None and a not in done and b not in done:
            out[a] = max(2, js_round(va * rt))
            out[b] = max(2, js_round(vb * rt))
            done.update((a, b))
    for k in _COUNT_KEYS:
        v = out.get(k)
        if v is not None and v != 0 and k not in done:
            out[k] = max(1, js_round(v * scale))
    v = out.get("iconD")
    if v is not None:
        out["iconD"] = max(0.02, v * scale)
    return out


def scaleRadii(opts, scale):
    out = dict(opts)
    for k in _RADIUS_KEYS:
        if out.get(k) is not None:
            out[k] = out[k] * scale
    out["rSizeMul"] = _g(out, "rSizeMul", 1) * scale
    return out


BASE_PROFILES = {
    "globe": dict(latRings=17, lonDensity=44, rBase=0.6, rDepth=1.7, rBoost=1.0, inkFar=0.62, inkSpan=0.54, rsPow=0.6, rMin=0.3),
    "orbits": dict(orbitN=12, ghostN=40, ghostR=0.9, ghostA=0.5, particles=3, partR=1.2, partRDepth=1.6, rsPow=0.6, rMin=0.3),
    "rubik": dict(latRings=15, lonDensity=40, moveCount=14, rBase=0.6, rDepth=1.7, rActive=0.3, inkFar=0.62, inkSpan=0.54, rsPow=0.6, rMin=0.3),
    "wave": dict(rings=15, lonDensity=40, rBase=0.6, rDepth=1.7, rsPow=0.6, rMin=0.3),
    "web": dict(nodeN=30, thr=0.72, signals=5, nodeR=1.4, nodeRDepth=1.8, lineW=0.8, rsPow=0.6, rMin=0.3),
    "braid": dict(strandN=52, turns=3.0, ghostN=150, rBase=1.2, rDepth=1.8, rsPow=0.6, rMin=0.3),
    "ribbon": dict(lanes=5, segs=88, ghostN=150, rBase=1.1, rDepth=1.7, rsPow=0.6, rMin=0.3),
    "ring": dict(lanes=5, segs=88, ghostN=0, faceOn=1, rBase=1.1, rDepth=1.7, rsPow=0.6, rMin=0.3),
    "morph": dict(rDot=0.021, iconD=1, rMin=0.25),
}

STATE_TO_MODE = {
    "working": "orbits",
    "searching": "globe",
    "solving": "rubik",
    "listening": "wave",
    "connecting": "web",
    "weaving": "braid",
    "composing": "ribbon",
    "breathing": "ring",
    "shaping": "morph",
}
STATES = list(STATE_TO_MODE)

LABELS = {
    "working": "Working…",
    "searching": "Searching…",
    "solving": "Solving…",
    "listening": "Listening…",
    "connecting": "Connecting…",
    "weaving": "Weaving…",
    "composing": "Composing…",
    "breathing": "Thinking…",
    "shaping": "Shaping…",
}

# (speed, count, size, extra)
PRESETS = {
    "orbits": {64: (1.885, 1, 1, None), 20: (3.9, 0.238, 2.4, None)},
    "globe": {64: (2.015, 0.42, 1.15, dict(scanMul=4.08, dimBase=0.45)),
              20: (2.665, 0.105, 1.75, dict(scanMul=4.335, dimBase=0.45))},
    "rubik": {64: (1.82, 0.35, 1.05, None), 20: (1.95, 0.088, 1.9, None)},
    "wave": {64: (4.388, 0.341, 1, None), 20: (3.998, 0.105, 1.6, None)},
    "web": {64: (3.315, 1.35, 0.95, None), 20: (6.63, 0.25, 1.52, None)},
    "braid": {64: (1.625, 0.5, 1, None), 20: (2.75, 0.1125, 1.36, None)},
    "ribbon": {64: (2.34, 0.25, 0.85, dict(spin=0, bandMul=3.9, wobMul=1)),
               20: (3.12, 0.051, 1.073, dict(spin=0, bandMul=4.94, wobMul=1))},
    "ring": {64: (3.24, 0.25, 0.956, dict(spin=0, bandMul=3.627, wobMul=0.368)),
             20: (3.78, 0.028, 1.622, dict(spin=0, bandMul=3.968, wobMul=0.565))},
    "morph": {64: (2.405, 0.702, 0.395, dict(spread=1.45)),
              20: (2.08, 0.53, 1.011, dict(spread=1.45))},
}

MODE_FRAMES = {
    "orbits": frameOrbits,
    "globe": frameGlobe,
    "rubik": frameRubik,
    "wave": frameWave,
    "web": frameWeb,
    "braid": frameBraid,
    "ribbon": frameRibbon,
    "ring": frameRibbon,
    "morph": frameMorph,
}

_preset_cache: dict = {}


def resolvePreset(state: str, size: int):
    """(state, size) → (mode, speed, opts), exactly like presets.ts."""
    key = (state, size)
    hit = _preset_cache.get(key)
    if hit:
        return hit
    mode = STATE_TO_MODE[state]
    speed, count, sz, extra = PRESETS[mode][size]
    opts = dict(BASE_PROFILES[mode])
    if count != 1:
        opts = scaleCounts(opts, count)
    if sz != 1:
        opts = scaleRadii(opts, sz)
    if extra:
        opts.update(extra)
    res = (mode, speed, opts)
    _preset_cache[key] = res
    return res


def orb_frame(state: str, size: int, t: float):
    """Geometry for one instant: (dots, lines) in draw order. `t` is already speed-scaled."""
    mode, _speed, opts = resolvePreset(state, size)
    return MODE_FRAMES[mode](size, t, opts)


# ---------------------------------------------------------------------------
# PySide6 widget
# ---------------------------------------------------------------------------

_CLOCK_START = time.perf_counter()  # one shared clock keeps every orb in phase

# Pre-built gray colour cache: 256 ink levels.
_GRAYS = [QColor(g, g, g) for g in range(256)]


def _ink(white: float, alpha: float, dark: bool) -> QColor:
    w = 0.0 if white < 0 else (1.0 if white > 1 else white)
    g = js_round((1 - w if dark else w) * 255)
    c = QColor(_GRAYS[g])
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


class ThinkingOrb(QWidget):
    """
    Animated thinking-orb widget.

    state:  working | searching | solving | listening | connecting |
            weaving | composing | breathing | shaping
    size:   64 or 20 — the two tuned designs (dot count / dot size / speed differ)
    theme:  "auto" (follow the widget palette), "dark" (light dots), "light" (dark dots)
    speed:  multiplier on the preset speed
    """

    def __init__(self, state: str = "working", size: int = 64, theme: str = "auto",
                 speed: float = 1.0, paused: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self._state = "working"
        self._size = 64
        self._theme = "auto"
        self._speed = 1.0
        self._paused = False
        self._reduced_motion = False
        self._frozen_t = None  # set while paused

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self.update)

        self.setState(state)
        self.setSize(size)
        self.setTheme(theme)
        self.setSpeed(speed)
        self.setPaused(paused)

    # --- public API -----------------------------------------------------
    def state(self) -> str:
        return self._state

    def setState(self, state: str) -> None:
        if state not in STATE_TO_MODE:
            raise ValueError(f"unknown state {state!r}; choose from {STATES}")
        self._state = state
        self.setAccessibleName(LABELS[state])
        self.setToolTip(LABELS[state])
        self.update()

    def orbSize(self) -> int:
        return self._size

    def setSize(self, size: int) -> None:
        if size not in (64, 20):
            raise ValueError("size must be 64 or 20 (the two tuned presets)")
        self._size = size
        self.updateGeometry()
        self.update()

    def setTheme(self, theme: str) -> None:
        if theme not in ("auto", "dark", "light"):
            raise ValueError("theme must be 'auto', 'dark' or 'light'")
        self._theme = theme
        self.update()

    def setSpeed(self, speed: float) -> None:
        self._speed = float(speed)
        self.update()

    def setPaused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self._frozen_t = self._clock() if paused else None
        self._sync_timer()
        self.update()

    def setReducedMotion(self, reduced: bool) -> None:
        """Static representative frame (t = 0.6), like prefers-reduced-motion on web."""
        self._reduced_motion = bool(reduced)
        self._sync_timer()
        self.update()

    def isDark(self) -> bool:
        if self._theme == "dark":
            return True
        if self._theme == "light":
            return False
        # auto: follow the effective background of this widget
        return self.palette().color(QPalette.ColorRole.Window).lightness() < 128

    # --- Qt plumbing ------------------------------------------------------
    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def showEvent(self, e):
        self._sync_timer()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()  # free when not visible
        super().hideEvent(e)

    def changeEvent(self, e):
        if e.type() in (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange,
                        QEvent.Type.StyleChange, QEvent.Type.ThemeChange):
            self.update()
        super().changeEvent(e)

    def _sync_timer(self):
        if self.isVisible() and not self._paused and not self._reduced_motion:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    @staticmethod
    def _clock() -> float:
        return time.perf_counter() - _CLOCK_START

    def _t(self) -> float:
        _mode, base_speed, _opts = resolvePreset(self._state, self._size)
        if self._reduced_motion:
            return 0.6
        secs = self._frozen_t if self._frozen_t is not None else self._clock()
        return secs * base_speed * self._speed

    def paintEvent(self, _event):
        p = QPainter(self)
        # fit the size×size design into the widget, centred, uniformly scaled
        side = min(self.width(), self.height())
        target = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        paint_orb(p, target, self._state, self._size, self._t(), self.isDark())
        p.end()


def paint_orb(p: QPainter, target: QRectF, state: str, size: int, t: float, dark: bool) -> None:
    """
    Draw one orb frame into `target` with any QPainter (widget, QImage, delegate, icon...).
    `t` is the speed-scaled time: seconds * preset speed (see resolvePreset) * your multiplier.
    """
    dots, lines = orb_frame(state, size, t)
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.translate(target.x(), target.y())
    p.scale(target.width() / size, target.height() / size)

    if lines:
        pen = QPen()
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        for x1, y1, x2, y2, white, a, w in lines:
            pen.setColor(_ink(white, a, dark))
            pen.setWidthF(w)
            p.setPen(pen)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    p.setPen(Qt.PenStyle.NoPen)
    rect = QRectF()
    for x, y, _z, r, white, a in dots:
        p.setBrush(_ink(white, a, dark))
        rect.setRect(x - r, y - r, 2 * r, 2 * r)
        p.drawEllipse(rect)
    p.restore()


# ---------------------------------------------------------------------------
# Demo playground:  python thinking_orbs.py
# ---------------------------------------------------------------------------

def _demo():
    import sys

    from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QGridLayout, QHBoxLayout,
                                   QLabel, QPushButton, QSlider, QVBoxLayout)

    app = QApplication.instance() or QApplication(sys.argv)

    win = QWidget()
    win.setWindowTitle("thinking-orbs — PySide6")
    win.setAutoFillBackground(True)

    def apply_bg(dark):
        pal = win.palette()
        bg, fg = (QColor("#0b0b0c"), QColor("#e8e8e8")) if dark else (QColor("#f7f7f5"), QColor("#1a1a1a"))
        pal.setColor(QPalette.ColorRole.Window, bg)
        pal.setColor(QPalette.ColorRole.WindowText, fg)
        pal.setColor(QPalette.ColorRole.ButtonText, fg)
        pal.setColor(QPalette.ColorRole.Button, QColor("#1c1c1e") if dark else QColor("#e9e9e6"))
        pal.setColor(QPalette.ColorRole.Text, fg)
        pal.setColor(QPalette.ColorRole.Base, QColor("#2a2a2d") if dark else QColor("#ffffff"))
        win.setPalette(pal)

    root = QVBoxLayout(win)
    root.setContentsMargins(24, 24, 24, 24)
    root.setSpacing(16)

    # Playground: big preview + controls
    big = ThinkingOrb("listening", 64)
    big.setFixedSize(192, 192)  # the 64 design, drawn 3× (like CSS scaling)
    small = ThinkingOrb("listening", 64)
    tiny = ThinkingOrb("listening", 20)
    caption = QLabel(LABELS["listening"])

    preview = QHBoxLayout()
    preview.addWidget(big)
    preview.addSpacing(24)
    inline = QVBoxLayout()
    inline.addStretch()
    inline.addWidget(small)
    row = QHBoxLayout()
    row.addWidget(tiny)
    row.addWidget(caption)
    row.addStretch()
    inline.addLayout(row)
    inline.addStretch()
    preview.addLayout(inline)
    preview.addStretch()
    root.addLayout(preview)

    orbs_all = [big, small, tiny]
    grid_orbs: list[ThinkingOrb] = []

    state_row = QHBoxLayout()
    group = QButtonGroup(win)
    for s in STATES:
        b = QPushButton(s)
        b.setCheckable(True)
        b.setChecked(s == "listening")
        group.addButton(b)
        state_row.addWidget(b)

        def pick(_checked=False, s=s):
            for o in (big, small, tiny):
                o.setState(s)
            caption.setText(LABELS[s])

        b.clicked.connect(pick)
    root.addLayout(state_row)

    ctl = QHBoxLayout()
    ctl.addWidget(QLabel("Speed"))
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(10, 300)
    slider.setValue(100)
    speed_lbl = QLabel("1.00×")

    def on_speed(v):
        speed_lbl.setText(f"{v / 100:.2f}×")
        for o in orbs_all + grid_orbs:
            o.setSpeed(v / 100)

    slider.valueChanged.connect(on_speed)
    ctl.addWidget(slider, 1)
    ctl.addWidget(speed_lbl)
    pause = QCheckBox("Paused")
    pause.toggled.connect(lambda on: [o.setPaused(on) for o in orbs_all + grid_orbs])
    ctl.addWidget(pause)
    dark_cb = QCheckBox("Dark background")
    dark_cb.setChecked(True)
    dark_cb.toggled.connect(apply_bg)  # orbs on theme="auto" follow the palette
    ctl.addWidget(dark_cb)
    root.addLayout(ctl)

    # Gallery: all nine states at both sizes
    grid = QGridLayout()
    for i, s in enumerate(STATES):
        o64 = ThinkingOrb(s, 64)
        o20 = ThinkingOrb(s, 20)
        grid_orbs += [o64, o20]
        grid.addWidget(o64, 0, i, Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(o20, 1, i, Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(s)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(lbl, 2, i)
    root.addLayout(grid)

    apply_bg(True)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    _demo()
