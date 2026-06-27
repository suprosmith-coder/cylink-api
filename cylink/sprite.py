"""
Auralis nanotech sprite — animated purple/green pixel art
Animations: float, pulse, scanline, glitch, spinup, alert
"""

import math
import random
import time
import threading
from rich.text import Text
from rich.console import Console
from rich.live import Live
from rich.align import Align


# ── Palette ────────────────────────────────────────────────────────────
def _rgb(r, g, b):
    return f"rgb({r},{g},{b})"

# Base colors
P_DEEP   = (88,  28,  135)   # deep purple   — outer shell
P_MID    = (126, 34,  206)   # mid purple    — body
P_LIGHT  = (168, 85,  247)   # light purple  — highlight
G_NODE   = (34,  197, 94)    # green         — circuit nodes
G_GLOW   = (74,  222, 128)   # bright green  — glow points
DARK     = (15,  3,   30)    # near black    — shadow/edge
RED_NODE = (239, 68,  68)    # red           — alert state
RED_GLOW = (252, 165, 165)   # light red     — alert glow

_  = None   # transparent


# ── Base sprite layout ─────────────────────────────────────────────────
# Codes: P=deep, M=mid, L=light, G=node, B=glow, D=dark, _=transparent
BASE = [
    [_,  _,  'D', 'D', 'G', 'G', 'D', 'D', _,   _ ],
    [_,  'D','P', 'M', 'M', 'M', 'M', 'P', 'D', _ ],
    ['D','P', 'M','G', 'L', 'L', 'G', 'M', 'P', 'D'],
    ['D','M', 'L','B', 'M', 'M', 'B', 'L', 'M', 'D'],
    ['D','P', 'M','G', 'L', 'L', 'G', 'M', 'P', 'D'],
    [_,  'D','P', 'M', 'G', 'G', 'M', 'P', 'D', _ ],
    [_,  'G','D', 'P', 'M', 'M', 'P', 'D', 'G', _ ],
    [_,  _,  'B', 'D', 'P', 'P', 'D', 'B', _,   _ ],
    [_,  _,  _,   'G', 'D', 'D', 'G', _,   _,   _ ],
]

SPRITE_H = len(BASE)
SPRITE_W = len(BASE[0])

# Node positions for targeted animations
NODE_POSITIONS = [
    (0, 4), (0, 5),          # top nodes
    (2, 3), (2, 6),          # eye nodes
    (3, 3), (3, 6),          # glow eyes
    (4, 3), (4, 6),          # lower eye nodes
    (5, 4), (5, 5),          # mid nodes
    (6, 1), (6, 8),          # arm nodes
    (7, 2), (7, 7),          # leg glow
    (8, 3), (8, 6),          # foot nodes
]


# ── Color resolver ─────────────────────────────────────────────────────
def _resolve(code, g_rgb=None, b_rgb=None, p_rgb=None, m_rgb=None, d_rgb=None):
    """Resolve a cell code to an rgb tuple, with override support."""
    g = g_rgb   or G_NODE
    b = b_rgb   or G_GLOW
    p = p_rgb   or P_DEEP
    m = m_rgb   or P_MID
    l = P_LIGHT
    d = d_rgb   or DARK
    mapping = {'P': p, 'M': m, 'L': l, 'G': g, 'B': b, 'D': d}
    return mapping.get(code)


def _lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _brighten(c, factor):
    return tuple(min(255, int(v * factor)) for v in c)


def _darken(c, factor):
    return tuple(int(v * factor) for v in c)


# ── Frame builder ──────────────────────────────────────────────────────
def build_frame(
    offset_y: int = 0,
    g_rgb=None,
    b_rgb=None,
    scanline_y: int = -1,
    glitch_row: int = -1,
    glitch_shift: int = 0,
) -> list[Text]:
    """
    Build one frame of the sprite as a list of Rich Text lines.
    offset_y   : vertical float offset (0 or 1 blank lines prepended)
    g_rgb      : override green node color
    b_rgb      : override bright glow color
    scanline_y : row index to render as a bright scan line (-1 = none)
    glitch_row : row index to shift horizontally (-1 = none)
    glitch_shift: pixels to shift glitch row
    """
    lines = []

    # Float offset — prepend blank lines
    for _ in range(max(0, offset_y)):
        lines.append(Text(""))

    for row_i, row in enumerate(BASE):
        # Glitch: shift row by slicing
        if row_i == glitch_row and glitch_shift != 0:
            shift = glitch_shift % SPRITE_W
            row = row[shift:] + row[:shift]

        line = Text()
        for col_i, code in enumerate(row):
            if code is None:
                line.append("  ")
                continue

            rgb = _resolve(code, g_rgb=g_rgb, b_rgb=b_rgb)
            if rgb is None:
                line.append("  ")
                continue

            # Scanline: brighten entire row
            if row_i == scanline_y:
                rgb = _brighten(rgb, 1.6)
                rgb = tuple(min(255, v) for v in rgb)

            line.append("  ", style=f"on rgb({rgb[0]},{rgb[1]},{rgb[2]})")
        lines.append(line)

    # Pad to fixed height so layout doesn't jump
    while len(lines) < SPRITE_H + 2:
        lines.append(Text(""))

    return lines


# ── Animation engine ───────────────────────────────────────────────────
class SpriteAnimator:
    """
    Runs sprite animations in a background thread.
    Call start_idle() to begin looping animations.
    Call trigger(name) to fire one-shot animations.
    Call stop() to end.
    """

    IDLE_ANIMATIONS = ["float", "pulse", "scanline", "glitch"]

    def __init__(self, console: Console):
        self.console    = console
        self._stop      = threading.Event()
        self._thread    = None
        self._live      = None
        self._triggered = None   # one-shot trigger name

    def _current_frame(self, t: float, trigger: str | None) -> list[Text]:
        # ── One-shot: spinup ──────────────────────────────────────────
        if trigger == "spinup":
            phase = (t % 0.3) / 0.3
            bright_g = _lerp_color(G_NODE, (255, 255, 255), phase)
            bright_b = _lerp_color(G_GLOW, (255, 255, 255), phase)
            return build_frame(g_rgb=bright_g, b_rgb=bright_b)

        # ── One-shot: alert (red flash) ───────────────────────────────
        if trigger == "alert":
            phase = abs(math.sin(t * 8))
            g = _lerp_color(G_NODE, RED_NODE, phase)
            b = _lerp_color(G_GLOW, RED_GLOW, phase)
            return build_frame(g_rgb=g, b_rgb=b)

        # ── Idle: determine which animation to play ───────────────────
        cycle   = int(t / 4) % len(self.IDLE_ANIMATIONS)
        phase_t = t % 4.0   # 4 seconds per animation

        anim = self.IDLE_ANIMATIONS[cycle]

        # Float — sine wave vertical offset
        if anim == "float":
            offset = 1 if math.sin(t * math.pi) > 0 else 0
            return build_frame(offset_y=offset)

        # Pulse — green nodes breathe brightness
        if anim == "pulse":
            brightness = 0.7 + 0.6 * abs(math.sin(t * 1.5))
            g = _brighten(G_NODE, brightness)
            b = _brighten(G_GLOW, brightness)
            g = tuple(min(255, v) for v in g)
            b = tuple(min(255, v) for v in b)
            return build_frame(g_rgb=g, b_rgb=b)

        # Scanline — bright line sweeps top to bottom
        if anim == "scanline":
            scan_y = int((phase_t / 4.0) * SPRITE_H)
            return build_frame(scanline_y=scan_y)

        # Glitch — occasional horizontal pixel shift
        if anim == "glitch":
            if random.random() < 0.08:   # 8% chance per frame
                row   = random.randint(0, SPRITE_H - 1)
                shift = random.choice([-1, 1, -2, 2])
                return build_frame(glitch_row=row, glitch_shift=shift)
            return build_frame()

        return build_frame()

    def _render(self, lines: list[Text]) -> Text:
        combined = Text()
        for line in lines:
            combined.append_text(line)
            combined.append("\n")
        return combined

    def _run(self):
        start = time.time()
        with Live(
            self._render(build_frame()),
            console=self.console,
            refresh_per_second=24,
            transient=True,
        ) as live:
            self._live = live
            while not self._stop.is_set():
                t       = time.time() - start
                trigger = self._triggered
                frame   = self._current_frame(t, trigger)
                live.update(self._render(frame))
                time.sleep(1 / 24)

    def start_idle(self):
        """Begin idle animation loop in background thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def trigger(self, name: str, duration: float = 1.5):
        """Fire a named one-shot animation for `duration` seconds."""
        self._triggered = name
        def _clear():
            time.sleep(duration)
            self._triggered = None
        threading.Thread(target=_clear, daemon=True).start()

    def stop(self):
        """Stop the animation and clean up."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        self._live = None


# ── Static render (for non-animated contexts) ──────────────────────────
def print_sprite(console: Console):
    """Print a static frame of the sprite."""
    for line in build_frame():
        console.print(line)


def render_sprite() -> list[Text]:
    """Return a static frame as a list of Rich Text lines."""
    return build_frame()
