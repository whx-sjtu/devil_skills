#!/usr/bin/env python3
"""Agentic token-throughput-per-chip vs. interactivity chart in the InferenceX dashboard style (light theme).

Ported from SemiAnalysisAI/InferenceX-app: globals.css (#eaebec / #131416), typography.ts (axis 12px,
line label 13px, data label 10px), chart-rendering.ts (point r 3.5), rooflines.ts (stroke 2, d3.curveMonotoneX),
dynamic-colors.ts + const-gpu-keys.ts (VENDOR_OKLCH_ZONES, HW_REGISTRY), line-label-layer.ts (line-label anchors,
pill and point-label collision layout). Official series come from /api/v1/views/inference with best=false.

  agentic_chart.py SPEC.json [-o OUT_STEM] [--view SAVED.view.json]   writes OUT_STEM.png/.svg (+ .view.json)
  agentic_chart.py --list [MODEL]                                       models, or MODEL's official series
"""
import argparse
import gzip
import itertools
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

FONTS = Path(__file__).resolve().parent.parent / "fonts"
API = "https://inferencex.semianalysis.com/api/v1/views"
BG, FG, AXIS, GRID, BORDER, ENGINE_INK = "#eaebec", "#131416", "#666b72", "#d9dce0", "#b4b9bc", "#d1d5db"
PX = 0.72  # pt per px at dpi 100
# HW_REGISTRY: gpu key -> (vendor zone, sort index, dashboard label)
HW = {"vr200": ("nvidia", -1, "Vera Rubin NVL72"), "gb300": ("nvidia", 0, "GB300 NVL72"),
      "gb200": ("nvidia", 1, "GB200 NVL72"), "b300": ("nvidia", 2, "B300"), "b200": ("nvidia", 3, "B200"),
      "mi355x": ("amd", 4, "MI355X"), "h200": ("nvidia", 5, "H200"), "mi325x": ("amd", 6, "MI325X"),
      "h100": ("nvidia", 7, "H100"), "mi300x": ("amd", 8, "MI300X"), "rtx6000pro": ("nvidia", 9, "RTX PRO 6000"),
      "jalapeno": ("openai", 10, "Jalapeño"), "tpuv7": ("google", 11, "TPU7x")}
ZONES = {"amd": (12, 42, 0.18), "nvidia": (120, 170, 0.15), "openai": (290, 330, 0.16),
         "google": (250, 275, 0.16), "unknown": (185, 235, 0.12)}  # VENDOR_OKLCH_ZONES: hue start, end, light chroma
GOOGLE_BLUE = "#4285F4"
# Overlays are not InferenceX series, so they stay out of vendor_colors and leave the dashboard colours unchanged.
OVERLAY_PALETTE = ["#d62728", "#6a3d9a", "#1f78b4", "#ff7f00", "#17becf", "#8c564b"]


def _linear_rgb(l, c, h):
    a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
    lms = [(l + 0.3963377774 * a + 0.2158037573 * b) ** 3,
           (l - 0.1055613458 * a - 0.0638541728 * b) ** 3,
           (l - 0.0894841775 * a - 1.2914855480 * b) ** 3]
    m = [(4.0767416621, -3.3077115913, 0.2309699292),
         (-1.2684380046, 2.6097574011, -0.3413193965),
         (-0.0041960863, -0.7034186147, 1.7076147010)]
    return [sum(k * x for k, x in zip(row, lms)) for row in m]


def oklch_hex(l, c, h):
    """CSS Color 4 style gamut mapping: lower chroma at fixed L/h until sRGB fits."""
    lo, hi = 0.0, c
    if any(not -1e-6 <= v <= 1 + 1e-6 for v in _linear_rgb(l, c, h)):
        for _ in range(30):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if all(-1e-6 <= v <= 1 + 1e-6 for v in _linear_rgb(l, mid, h)) else (lo, mid)
        c = lo
    out = []
    for v in _linear_rgb(l, c, h):
        v = min(1.0, max(0.0, v))
        v = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        out.append(round(v * 255))
    return "#%02x%02x%02x" % tuple(out)


def vendor_colors(keys):
    """generateVendorColors(activeKeys, 'light'): one hue band per vendor, lightness 0.68 -> 0.42."""
    groups, out = {}, {}
    for k in keys:
        groups.setdefault(HW.get(k.split("_")[0], ("unknown",))[0], []).append(k)
    for vendor, group in groups.items():
        # getModelSortIndex, then localeCompare, which (ICU) sorts '_' before '-' before digits before letters
        group.sort(key=lambda k: (HW.get(k.split("_")[0], (None, len(HW)))[1],
                                  [(0, "_-".index(ch)) if ch in "_-" else (1, ch) for ch in k.lower()]))
        start, end, chroma = ZONES[vendor]
        n = len(group)
        if vendor == "google" and n == 1:
            out[group[0]] = GOOGLE_BLUE
            continue
        for i, k in enumerate(group):
            light = round(0.68 - i / (n - 1) * 0.26, 3) if n > 1 else 0.55
            out[k] = oklch_hex(light, chroma, round(start + (i + 0.5) / n * (end - start), 1))
    return out


def frontier(pts):
    """globalParetoFrontier maximizing both axes; pts are (conc, y, x)."""
    best, out = -math.inf, []
    for p in sorted(pts, key=lambda p: (-p[2], -p[1])):
        if p[1] > best:
            out.append(p)
            best = p[1]
    return sorted(out, key=lambda p: p[2])


def monotone_x(xs, ys, steps=40):
    """d3.curveMonotoneX (Steffen tangents, cubic Bezier segments)."""
    n = len(xs)
    if n < 3 or any(b <= a for a, b in zip(xs, xs[1:])):  # tangents need strictly increasing x
        return list(xs), list(ys)
    sign = lambda v: (v > 0) - (v < 0)  # noqa: E731
    t = [0.0] * n
    for i in range(1, n - 1):
        h0, h1 = xs[i] - xs[i - 1], xs[i + 1] - xs[i]
        s0, s1 = (ys[i] - ys[i - 1]) / h0, (ys[i + 1] - ys[i]) / h1
        p = (s0 * h1 + s1 * h0) / (h0 + h1)
        t[i] = (sign(s0) + sign(s1)) * min(abs(s0), abs(s1), 0.5 * abs(p))
    t[0] = (3 * (ys[1] - ys[0]) / (xs[1] - xs[0]) - t[1]) / 2
    t[-1] = (3 * (ys[-1] - ys[-2]) / (xs[-1] - xs[-2]) - t[-2]) / 2
    px, py = [xs[0]], [ys[0]]
    for i in range(n - 1):
        dx = (xs[i + 1] - xs[i]) / 3
        cx = (xs[i], xs[i] + dx, xs[i + 1] - dx, xs[i + 1])
        cy = (ys[i], ys[i] + dx * t[i], ys[i + 1] - dx * t[i + 1], ys[i + 1])
        for k in range(1, steps + 1):
            u = k / steps
            w = ((1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3)
            px.append(sum(a * b for a, b in zip(w, cx)))
            py.append(sum(a * b for a, b in zip(w, cy)))
    return px, py


def si(v, _):
    return "0" if v == 0 else (f"{v / 1000:g}k" if v >= 1000 else f"{v:g}")


# Layout below works in SVG plot-area pixels (origin top-left, y down) like line-label-layer.ts;
# rects are (left, top, right, bottom).
def overlap(a, b, strict=False):
    if strict:
        return a[2] > b[0] and a[0] < b[2] and a[3] > b[1] and a[1] < b[3]
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def shift_into(lo, hi, size):
    return -lo if hi - lo > size or lo < 0 else (size - hi if hi > size else 0)


def line_anchors(fronts, half_w=60, ch=13 + 8):
    """placeLineLabels: anchor slots 0.25/0.5/0.75/1 rotated per series, top-most series first."""
    placed, out, crowded = [], {}, []
    collide = lambda x, y: any(abs(oy - y) < ch and abs(ox - x) < 2 * half_w for ox, oy in placed)  # noqa: E731
    cost = lambda x, y: sum(max(0, 2 * half_w - abs(ox - x)) * max(0, ch - abs(oy - y)) for ox, oy in placed)  # noqa: E731
    for i, (key, pts) in enumerate(sorted(fronts.items(), key=lambda kv: kv[1][0][1])):
        last, cands = len(pts) - 1, []
        for s in range(4):
            frac = (0.25, 0.5, 0.75, 1)[(s + i) % 4]
            p = pts[0] if last <= 0 else pts[max(1, min(last, math.floor(frac * last + 0.5)))]
            if p not in cands:
                cands.append(p)
        hit = next((p for p in cands if not collide(*p)), None)
        if hit is None:
            crowded.append((key, cands))
            continue
        placed.append(hit)
        out[key] = hit
    for key, cands in crowded:
        out[key] = min(cands, key=lambda p: cost(*p))
        placed.append(out[key])
    return out


def layout_pills(anchors, sizes, size, obstacles=()):
    """layoutPills: pill at anchor + (8, -14), else mirrored or row-shifted slots, clamped into the plot."""
    placed, out = [], {}
    free = lambda b, rects: not any(overlap(b[1], o, strict=True) for o in rects)  # noqa: E731
    for key, (x, y) in anchors.items():
        w, h = sizes[key]
        loc = (-5, -h / 2 - 3, w + 5, h / 2 + 3)
        tx0, ty0 = x + 8, y - 14
        mx, my = 2 * x - tx0 - loc[0] - loc[2], 2 * y - ty0 - loc[1] - loc[3]
        cands, rh = [(tx0, ty0), (tx0, my), (mx, ty0), (mx, my)], loc[3] - loc[1] + 4
        for row in (1, 2, 3):
            for cx in (tx0, mx):
                cands += [(cx, ty0 - row * rh), (cx, ty0 + row * rh)]
        boxes = []
        for cx, cy in cands:
            dx = shift_into(cx + loc[0], cx + loc[2], size[0])
            dy = shift_into(cy + loc[1], cy + loc[3], size[1])
            boxes.append(((cx + dx, cy + dy), (cx + dx + loc[0], cy + dy + loc[1], cx + dx + loc[2], cy + dy + loc[3])))
        # Obstacles are a preference; never giving up pill-vs-pill separation for them.
        out[key] = (next((b for b in boxes if free(b, placed + list(obstacles))), None)
                    or next((b for b in boxes if free(b, placed)), boxes[0]))
        placed.append(out[key][1])
    return out


def layout_point_labels(items, obstacles, size, sides=False):
    """placePointLabels: above, below, then one block further out; hidden when every slot collides.
    sides=True swaps the far slots for right/left ones, which stay unambiguous between close neighbours."""
    placed, out = list(obstacles), []
    for cx, cy, w, text in sorted(items, key=lambda t: t[0]):
        far = [(w / 2 + 9, 4), (-w / 2 - 9, 4)] if sides else [(0, -8 - 12 - 2), (0, 14 + 12 + 2)]
        for ox, first in [(0, -8), (0, 14)] + far:
            b = (cx + ox - w / 2 - 2, cy + first - 11, cx + ox + w / 2 + 2, cy + first + 5)
            if b[1] < 0 or b[3] > size[1] or b[2] - b[0] > size[0]:
                continue
            dx = ox + shift_into(b[0], b[2], size[0])
            b = (cx + dx - w / 2 - 2, b[1], cx + dx + w / 2 + 2, b[3])
            if not any(overlap(b, o) for o in placed):
                placed.append(b)
                out.append((cx + dx, cy + first, text, b))
                break
    return out


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "infx-agentic-chart", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return json.loads(gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body)


def find_model(name):
    models = get_json(f"{API}/options")["models"]
    for m in models:
        if name.lower() in {m["name"].lower(), m["compareSlug"], *m["dbKeys"]}:
            return m["name"]
    sys.exit(f"unknown model {name!r}; known: {', '.join(m['name'] for m in models)}")


def fetch_view(model, percentile="p90"):
    url = f"{API}/inference?" + urllib.parse.urlencode({
        "model": find_model(model), "sequence": "agentic-traces", "xmode": "interactivity",
        "percentile": percentile, "metric": "tpPerGpu", "optimal": "false", "best": "false"})
    return {"url": url, "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "response": get_json(url)}


def split_label(label):
    m = re.fullmatch(r"(.*?) \((.*)\)", label)
    return m.groups() if m else (label, "")


def official_series(view, keep, percentile):
    got = (view["params"]["sequence"], view["xAxis"]["statistic"], view["metric"]["key"], view["params"]["best"])
    assert got == ("agentic-traces", percentile, "tpPerGpu", False), got
    available = [s["hwKey"] for s in view["series"]]
    if set(keep or ()) - set(available):
        sys.exit(f"official series {sorted(set(keep) - set(available))} not in the view; available: {available}")
    out = {}
    for s in view["series"]:  # API order follows the HW_REGISTRY sort, like the dashboard legend
        if keep and s["hwKey"] not in keep:
            continue
        pts = [(p["concurrency"], p["y"], p["x"]) for p in s["points"]]
        # ScatterGraph rooflines: one frontier per submission date, joined into a single line sorted by x.
        front = sorted({q for d in {p["date"] for p in s["points"]} for q in frontier(
            [(p["concurrency"], p["y"], p["x"]) for p in s["points"] if p["date"] == d])}, key=lambda q: q[2])
        # Our frontier must reproduce the dashboard's, or the drawn line would differ from InferenceX.
        assert {(x, y) for _, y, x in front} == {(p["x"], p["y"]) for p in s["points"] if p["frontier"]}, \
            f"frontier mismatch for {s['hwKey']}"
        hw, engine = split_label(s["label"])
        chips = sorted({int(m.group(1)) for p in s["points"] if (m := re.search(r"GPU=(\d+)", p["topologyKey"]))})
        out[s["hwKey"]] = {"hw": hw, "engine": engine, "pts": pts, "front": front, "dashed": False, "chips": chips,
                           "runs": sorted({(str(p["runId"]), p["date"]) for p in s["points"]})}
    for k, c in vendor_colors(list(out)).items():
        out[k]["color"] = c
    return out


def user_series(specs, overlay):
    out, hl, base, palette = {}, None, None, itertools.cycle(OVERLAY_PALETTE[1:])
    for s in specs:
        pts = [(int(p["conc"]), float(p["tput"]), float(p["interactivity"])) for p in s["points"]]
        assert pts and all(math.isfinite(v) and v > 0 for p in pts for v in p), f"bad points in {s['hw']} {s['engine']}"
        gpu = next((g for g, v in HW.items() if s["hw"].lower() in (g, v[2].lower())), "unknown")
        key = f"{gpu}_{s['engine'].lower()}"
        assert key not in out, f"duplicate series {s['hw']} ({s['engine']})"
        out[key] = {"hw": s["hw"], "engine": s["engine"], "pts": pts, "front": frontier(pts), "color": s.get("color"),
                    "dashed": s.get("style", "dashed" if overlay else "solid") == "dashed"}
        if s.get("highlight"):
            assert hl is None, "more than one highlight series"
            hl = key
        if s.get("baseline"):
            assert base is None and key != hl, "one baseline series, different from the highlight"
            base = key
    auto = {} if overlay else vendor_colors(list(out))
    for k, s in out.items():
        s["color"] = s["color"] or auto.get(k) or (OVERLAY_PALETTE[0] if k == hl else next(palette))
    return out, hl, base


def wrap(line, fits):
    """Greedy word wrap by rendered width; continuation lines indent two spaces past the first."""
    ind = " " * (len(line) - len(line.lstrip()))
    out, cur = [], ind
    for word in line.split():
        if cur.strip() and not fits(f"{cur} {word}"):
            out.append(cur)
            cur = ind + "  "
        cur = f"{cur} {word}" if cur.strip() else cur + word
    return out + [cur]


def render(series, hl, base, title, subtitle, notes, out_stem):
    if (FONTS / "DMSans-Regular.ttf").exists():
        for w in ("Regular", "Bold"):
            font_manager.fontManager.addfont(str(FONTS / f"DMSans-{w}.ttf"))
        plt.rcParams["font.family"] = "DM Sans"
    else:
        print(f"warning: {FONTS} has no DM Sans, falling back to the matplotlib default font", file=sys.stderr)
    plt.rcParams.update({"svg.fonttype": "none", "pdf.fonttype": 42})

    fig = plt.figure(figsize=(12.4, 7.2), dpi=100, facecolor=BG)
    fig.text(0.02, 0.955, title, fontsize=18 * PX, fontweight="bold", color=FG)
    fig.text(0.02, 0.918, subtitle, fontsize=13 * PX, color=FG)
    ax = fig.add_axes([0.075, 0.12, 0.64, 0.75], facecolor=BG)

    fronts = {}
    for key, s in series.items():
        fronts[key] = s["front"]
        lx, ly = monotone_x([p[2] for p in fronts[key]], [p[1] for p in fronts[key]])
        d, h = s["dashed"], key == hl
        ax.plot(lx, ly, color=s["color"], lw=(3.5 if d else 2) * PX, ls=(0, (3, 1.5)) if d else "-",
                solid_capstyle="round", zorder=4.5 if d else 4)
        ax.scatter([p[2] for p in s["pts"]], [p[1] for p in s["pts"]], s=(2 * (5 if h else 3.5) * PX) ** 2,
                   color=s["color"], marker="D" if h else "o", edgecolors="white", linewidths=1.2 * PX if h else 0,
                   zorder=6 if h else 5)

    allp = [p for s in series.values() for p in s["pts"]]
    ax.set_xlim(0, max(p[2] for p in allp) * 1.08)
    ax.set_ylim(0, max(p[1] for p in allp) * 1.1)
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_major_locator(MaxNLocator(nbins=10, steps=[1, 2, 2.5, 5, 10]))
        axis.set_major_formatter(FuncFormatter(si))
    ax.tick_params(labelsize=10 * PX, colors=FG, length=6 * PX, width=1 * PX, color=FG)
    ax.grid(True, color=GRID, lw=1 * PX)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(FG)
        ax.spines[s].set_linewidth(1 * PX)
    ax.set_xlabel("Interactivity (tok/s/user)", fontsize=12 * PX, color=FG, labelpad=10)
    ax.set_ylabel("Token Throughput per Chip (tok/s/chip)", fontsize=12 * PX, color=FG, labelpad=10)

    renderer = fig.canvas.get_renderer()
    bb = ax.get_window_extent(renderer)
    fw, fh = fig.bbox.width, fig.bbox.height
    plot = (bb.width, bb.height)

    def to_svg(x, y):
        xd, yd = ax.transData.transform((x, y))
        return xd - bb.x0, bb.y1 - yd

    def to_fig(sx, sy):
        return (bb.x0 + sx) / fw, (bb.y1 - sy) / fh

    texts, sizes = {}, {}
    for key, s in series.items():
        hw = fig.text(0, 0, s["hw"], fontsize=13 * PX, fontweight="bold", color="white", va="center", zorder=8)
        eng = fig.text(0, 0, f" ({s['engine']})" if s["engine"] else "", fontsize=13 * PX, color=ENGINE_INK,
                       va="center", zorder=8)
        ea, eb = hw.get_window_extent(renderer), eng.get_window_extent(renderer)
        texts[key] = (hw, eng, ea.width)
        sizes[key] = (ea.width + (eb.width if s["engine"] else 0), ea.height)
    anchors = line_anchors({k: [to_svg(p[2], p[1]) for p in fr] for k, fr in fronts.items()})
    line = zip(*monotone_x([p[2] for p in fronts[hl]], [p[1] for p in fronts[hl]])) if hl else ()
    # Prefer pill slots off the highlighted line, which is the point of the chart.
    pills = layout_pills(anchors, sizes, plot, [to_svg(x, y) * 2 for x, y in line])
    for key, ((tx, ty), (l, t, r, b)) in pills.items():
        hw, eng, wa = texts[key]
        hw.set_position(to_fig(tx, ty))
        eng.set_position(to_fig(tx + wa, ty))
        x0, y0 = to_fig(l, b)
        x1, y1 = to_fig(r, t)
        ax.add_artist(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, transform=fig.transFigure,
                                     boxstyle=f"round,pad=0,rounding_size={4 / fw}", mutation_aspect=fw / fh,
                                     facecolor=series[key]["color"], edgecolor="none", alpha=0.95, zorder=7,
                                     clip_on=False))
    boxes = [b for _, b in pills.values()]
    if any(overlap(a, b, strict=True) for i, a in enumerate(boxes) for b in boxes[i + 1:]):
        print("warning: line labels overlap (the dashboard does the same when crowded); "
              "select fewer official series", file=sys.stderr)

    probe = fig.text(0, 0, "C00", fontsize=10 * PX, fontweight="bold")
    digit_w = probe.get_window_extent(renderer).width / 3
    probe.remove()
    # A baseline point next to the same-concurrency highlight point is labelled once, on the highlight.
    paired = {p[0] for p in series[hl]["pts"]} if hl and base else set()
    items = {k: [(*to_svg(x, y), digit_w * len(f"C{c}"), f"C{c}") for c, y, x in s["pts"]
                 if not (k == base and c in paired)] for k, s in series.items()}
    # Point obstacles so a neighbour's label cannot sit on one of the compared points.
    obstacles = boxes + [to_svg(x, y) * 2 for k in (hl, base) if k for _, y, x in series[k]["pts"]]
    n_items = sum(map(len, items.values()))
    labels = layout_point_labels(items.pop(hl), obstacles, plot, sides=True) if hl else []
    labels += layout_point_labels([t for v in items.values() for t in v], obstacles + [l[3] for l in labels], plot)
    for sx, sy, text, _ in labels:
        fig.text(*to_fig(sx, sy), text, ha="center", va="baseline", fontsize=10 * PX, fontweight="bold",
                 color=FG, zorder=6)

    panel = fig.add_axes([0.745, 0.12, 0.235, 0.75], facecolor=BG)
    panel.set_axis_off()
    panel.add_patch(FancyBboxPatch((0, 0), 1, 1, boxstyle="round,pad=0,rounding_size=0.02",
                                   transform=panel.transAxes, facecolor=BG, edgecolor=BORDER, lw=1 * PX))
    # Rows and fonts shrink together when crowded, so text never overlaps; legend gets at most half the panel.
    row = min(0.048, 0.5 / len(series))
    k = min(1, row / 0.048 * 1.3)
    for i, (key, s) in enumerate(series.items()):
        yy = 0.955 - i * row
        if s["dashed"]:
            panel.plot([0.035, 0.105], [yy, yy], color=s["color"], lw=3.5 * PX * k, ls=(0, (2, 1)),
                       transform=panel.transAxes)
        panel.scatter([0.07], [yy], s=(2 * 5 * PX * k) ** 2, color=s["color"], transform=panel.transAxes, zorder=3,
                      marker="D" if key == hl else "o", edgecolors="white", linewidths=1.2 * PX if key == hl else 0)
        panel.text(0.12, yy, f"{s['hw']} ({s['engine']})" if s["engine"] else s["hw"], fontsize=13 * PX * k,
                   color=FG, va="center", transform=panel.transAxes)
    probe = panel.text(0, 0, "", fontsize=10.5 * PX)
    max_w = panel.get_window_extent(renderer).width * (0.97 - 0.07)
    fits = lambda t: probe.set_text(t) or probe.get_window_extent(renderer).width <= max_w  # noqa: E731
    notes = [w for t in notes for w in wrap(t, fits)]
    probe.remove()
    y0 = 0.955 - (len(series) - 1) * row - max(0.03, row + 0.007)
    step = min(0.028, (y0 - 0.02) / max(1, len(notes) - 1))
    kn = min(1, step / 0.028 * 1.15)
    if min(k, kn) < 0.8:
        print(f"warning: side panel text shrunk to {min(k, kn):.0%} for {len(series)} series and "
              f"{len(notes)} note lines; select fewer official series or shorten notes", file=sys.stderr)
    for i, t in enumerate(notes):
        panel.text(0.07, y0 - i * step, t, fontsize=10.5 * PX * kn, color=AXIS, va="center",
                   transform=panel.transAxes)

    fig.savefig(f"{out_stem}.png", dpi=200, facecolor=BG)
    fig.savefig(f"{out_stem}.svg", facecolor=BG)
    print(f"wrote {out_stem}.png and .svg; point labels shown {len(labels)}/{n_items}")


def build(spec, view_file, out_stem):
    off, pct = spec.get("official"), spec.get("percentile", "p90")
    series, notes = {}, ["Lines: per-series Pareto frontier · Points: all measured",
                         f"x = 1 / {pct.upper()} full-response inter-token latency",
                         "y = (input + output) tok/s per chip", ""]
    for t in spec.get("notes", []):
        notes += [t, ""]
    if off:
        saved = json.loads(Path(view_file).read_text()) if view_file else fetch_view(off["model"], pct)
        if not view_file:
            Path(f"{out_stem}.view.json").write_text(json.dumps(saved, ensure_ascii=False))
        view = saved["response"]
        if re.sub(r"[^a-z0-9]", "", off["model"].lower()) != re.sub(r"[^a-z0-9]", "", view["params"]["model"].lower()):
            print(f"warning: spec model {off['model']!r} but the view is {view['params']['model']!r}", file=sys.stderr)
        series = official_series(view, off.get("series"), pct)
    users, hl, base = user_series(spec.get("series", []), overlay=bool(off))
    series.update(users)
    assert series, "nothing to plot"
    if hl and base:
        a, b = ({p[0]: p for p in series[k]["pts"]} for k in (hl, base))
        common = sorted(set(a) & set(b))
        if common:
            tput, inter = ([a[c][i] / b[c][i] for c in common] for i in (1, 2))
            notes += [f"{series[hl]['engine']} vs {series[base]['engine']}, same concurrency "
                      f"C{common[0]}–C{common[-1]} ({len(common)} points):",
                      f"  throughput {min(tput):.0%}–{max(tput):.0%}, interactivity {min(inter):.0%}–{max(inter):.0%}",
                      ""]
    if off:
        notes.append(f"InferenceX view API (best=false, fetched {saved['retrieved_at'][:10]}):")
        for s in series.values():
            if "runs" in s:
                chips = s["chips"][0] if len(s["chips"]) == 1 else f"{s['chips'][0]}–{s['chips'][-1]}"
                notes += [f"  {s['hw']} ({s['engine']}): {chips} chips",
                          "    " + ", ".join(f"run {r} ({d})" for r, d in s["runs"])]
    model = f"{view['params']['model']} " if off else ""
    precision = "/".join(view["params"]["precisions"]) if off else spec.get("precision", "")
    sources = (["InferenceX"] if off else []) + spec.get("sources", [])
    hws = list(dict.fromkeys(s["hw"] for s in series.values()))
    subtitle = "   ·   ".join([f"Hardware: {', '.join(hws)}"] + [f"Precision: {precision.upper()}"] * bool(precision)
                               + [f"Sources: {', '.join(sources)}"] * bool(sources))
    render(series, hl, base, spec.get("title", f"{model}Agentic Token Throughput per Chip vs. Interactivity"),
           spec.get("subtitle", subtitle), notes, out_stem)


def list_cmd(model):
    if not model:
        for m in get_json(f"{API}/options")["models"]:
            print(f"{m['name']:24} slug={m['compareSlug']:24} db={','.join(m['dbKeys'])} ({m['category']})")
        return
    saved = fetch_view(model)
    print(saved["url"])
    for s in saved["response"]["series"]:
        dates = sorted({p["date"] for p in s["points"]})
        print(f"{s['hwKey']:28} {s['label']:36} {len(s['points']):3} points  {dates[0]}..{dates[-1]}")


def self_check():
    assert frontier([(1, 1, 3), (2, 2, 2), (3, 1.5, 1)]) == [(2, 2, 2), (1, 1, 3)]
    xs, ys = monotone_x([0, 1, 2], [0, 1, 1])
    assert max(ys) <= 1 + 1e-9 and xs[-1] == 2
    same = layout_pills({"a": (100, 100), "b": (100, 100)}, {"a": (80, 16), "b": (80, 16)}, (400, 300))
    assert not overlap(same["a"][1], same["b"][1], strict=True)
    assert len(layout_point_labels([(50, 50, 20, "C1"), (50, 50, 20, "C2")], [], (400, 300))) == 2
    blocked = [(50, 42, 50, 42), (50, 64, 50, 64)]  # points sitting in the above and below slots
    assert layout_point_labels([(50, 50, 20, "C1")], blocked, (400, 300), sides=True)[0][0] > 50
    # Colours read off the live Kimi-K3 dashboard with only these four series selected.
    assert vendor_colors(["gb300_dynamo-vllm", "gb200_dynamo-vllm", "mi355x_atom", "mi355x_vllm-disagg"]) == {
        "gb300_dynamo-vllm": "#73ab41", "gb200_dynamo-vllm": "#005d37",
        "mi355x_atom": "#f3606a", "mi355x_vllm-disagg": "#8c1f00"}
    assert split_label("MI355X (ATOM¹)") == ("MI355X", "ATOM¹") and split_label("TPU7x") == ("TPU7x", "")
    assert wrap(" aa bb cc", lambda t: len(t) <= 6) == [" aa bb", "   cc"] and wrap("", len) == [""]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?", help="chart spec JSON (see SKILL.md)")
    ap.add_argument("-o", "--out", help="output stem; default is SPEC without .json")
    ap.add_argument("--view", help="saved OUT_STEM.view.json to reuse instead of fetching InferenceX")
    ap.add_argument("--list", nargs="?", const="", metavar="MODEL", help="list models, or MODEL's official series")
    args = ap.parse_args()
    self_check()
    if args.list is not None:
        list_cmd(args.list)
    elif not args.spec:
        ap.error("SPEC is required")
    else:
        build(json.loads(Path(args.spec).read_text()), args.view, args.out or str(Path(args.spec).with_suffix("")))
