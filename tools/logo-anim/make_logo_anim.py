"""Animated logo overlays + a 5 s outro for a 1080x1920 reel (Al-Anwar Al-Najafyia logo).

usage: python make_logo_anim.py <logo image> <output folder> [--ffmpeg PATH] [--preview]

Writes logo_a..d.mov (ProRes 4444 with alpha, 10 s, logo top-left), logo_hold.png,
outro.mp4 (dark background) and outro_alpha.mov (transparent).
"""
import sys, math, subprocess, argparse, os
from collections import deque
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageFilter

ap = argparse.ArgumentParser()
ap.add_argument('logo'); ap.add_argument('out')
ap.add_argument('--ffmpeg', default='ffmpeg'); ap.add_argument('--preview', action='store_true')
ARGS = ap.parse_args()
OUT, FFMPEG, PREVIEW = ARGS.out, ARGS.ffmpeg, ARGS.preview
W, H, FPS = 1080, 1920, 30
GOLD = np.array([218, 176, 42], np.float32) / 255
PARTS = ['arcs', 'rays', 'sun', 'arabic', 'en1', 'en2']
SRC_W, SRC_H = 1505, 1403
ANCHOR = (761.0, 583.0)          # sun centre inside the cropped layers

# ---------- split the logo into parts (coordinates measured on the 2000x1611 original) ----------
def extract_layers(path):
    im = Image.open(path).convert('RGB')
    if abs(im.size[1] / im.size[0] - 1611 / 2000) > 0.02:
        sys.exit(f'unexpected logo proportions {im.size}; expected the 2000x1611 logo (white background)')
    im = im.resize((2000, 1611), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)
    alpha = np.clip((255 - a[..., 2]) / (255 - 42), 0, 1)
    h, w = alpha.shape
    yy, xx = np.mgrid[0:h, 0:w]
    def component_mask(on, region, seeds):
        on = on & region; out = np.zeros_like(on)
        for sy, sx in seeds:
            row = np.where(on[sy])[0]; sx = int(row[np.argmin(abs(row - sx))])
            q = deque([(sy, sx)]); out[sy, sx] = True
            while q:
                y, x = q.popleft()
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and on[ny, nx] and not out[ny, nx]:
                        out[ny, nx] = True; q.append((ny, nx))
        g = out.copy()
        for _ in range(2):
            g[1:] |= g[:-1]; g[:-1] |= g[1:]; g[:, 1:] |= g[:, :-1]; g[:, :-1] |= g[:, 1:]
        return g & region
    sun = (xx - 1008) ** 2 + (yy - 683) ** 2 < 118 ** 2
    rays = (yy < 720) & ~sun
    band = (yy >= 700) & (yy < 1200) & ~sun & ~rays
    arcs = component_mask(alpha > 0.15, band, seeds=[(1150, 290), (1150, 1712)])
    parts = dict(sun=sun, rays=rays, arcs=arcs, arabic=band & ~arcs,
                 en1=(yy >= 1200) & (yy < 1370), en2=yy >= 1370)
    x0, x1, y0, y1 = 247, 1752, 100, 1503
    res = {}
    for k, m in parts.items():
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[..., :3] = (GOLD * 255).astype(np.uint8)
        rgba[..., 3] = (alpha * m * 255).astype(np.uint8)
        res[k] = Image.fromarray(rgba[y0:y1, x0:x1])
    return res

LAYER_IMGS = None

def init_worker(path):
    global LAYER_IMGS
    LAYER_IMGS = extract_layers(path)

# ---------- easing ----------
def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def prog(t, t0, t1): return clamp((t - t0) / (t1 - t0)) if t1 > t0 else float(t >= t0)
def ease_out(x): return 1 - (1 - x) ** 3
def ease_in_out(x): return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2
def back_out(x, k=1.70158): x -= 1; return 1 + (k + 1) * x ** 3 + k * x ** 2

# ---------- layers ----------
class Logo:
    def __init__(self, width):
        self.s = width / SRC_W
        self.w, self.h = round(SRC_W * self.s), round(SRC_H * self.s)
        self.ax, self.ay = ANCHOR[0] * self.s, ANCHOR[1] * self.s
        self.img = {p: LAYER_IMGS[p].resize((self.w, self.h), Image.LANCZOS) for p in PARTS}
        self.alpha = {p: np.asarray(self.img[p], np.float32)[..., 3] / 255 for p in PARTS}
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        self.dist = np.hypot(xx - self.ax, yy - self.ay)          # for radial reveals
        self.yy, self.xx = yy, xx
        self.maxd = float(self.dist.max())

    def transformed(self, a, scale=1.0, rot=0.0, dx=0.0, dy=0.0):
        """alpha map transformed about the anchor; output in logo space."""
        if scale == 1 and rot == 0 and dx == 0 and dy == 0: return a
        c, s_ = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        # inverse affine: output (x,y) -> source
        ia, ib = c / scale, s_ / scale
        id_, ie = -s_ / scale, c / scale
        ox, oy = self.ax + dx, self.ay + dy
        ic = self.ax - ia * ox - ib * oy
        if_ = self.ay - id_ * ox - ie * oy
        im = Image.fromarray((a * 255).astype(np.uint8), 'L')
        im = im.transform((self.w, self.h), Image.AFFINE, (ia, ib, ic, id_, ie, if_), Image.BICUBIC)
        return np.asarray(im, np.float32) / 255

    def frame(self, st):
        """st: dict part -> dict(op, scale, rot, dx, dy, reveal) ; returns alpha (h,w) and shine map."""
        total = np.zeros((self.h, self.w), np.float32)
        for p in PARTS:
            ps = st.get(p, {})
            op = ps.get('op', 1.0)
            if op <= 0: continue
            a = self.alpha[p]
            rv = ps.get('reveal')                  # callable(mask helpers) -> 0..1 mask
            if rv is not None: a = a * rv(self)
            a = self.transformed(a, ps.get('scale', 1.0), ps.get('rot', 0.0), ps.get('dx', 0.0), ps.get('dy', 0.0)) * op
            total = total + a * (1 - total)
        return total

def shine_map(logo, pos, width=0.10, strength=0.85):
    """diagonal light band; pos 0..1 across the logo."""
    if pos is None: return 0
    d = (logo.xx / logo.w * 0.75 + logo.yy / logo.h * 0.25)
    p = -0.25 + pos * 1.5
    return strength * np.exp(-((d - p) / width) ** 2)

def colorize(alpha, shine=0, glow=None, glow_op=0.0):
    """premultiplied RGBA float from a gold alpha mask + optional shine and outer glow."""
    rgb = GOLD[None, None, :] + (1 - GOLD)[None, None, :] * (np.asarray(shine)[..., None] if np.ndim(shine) else shine)
    out = np.dstack([rgb * alpha[..., None], alpha])
    if glow is not None and glow_op > 0:
        g = Image.fromarray((alpha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(glow))
        g = np.asarray(g, np.float32) / 255 * glow_op
        gl = np.dstack([np.broadcast_to(GOLD * 1.1, g.shape + (3,)) * g[..., None], g])
        out = out + gl * (1 - out[..., 3:4])
    return out

def over(dst, src, x, y):
    """premultiplied src over dst at integer offset, clipped."""
    h, w = src.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.shape[1], x + w), min(dst.shape[0], y + h)
    if x1 <= x0 or y1 <= y0: return
    s = src[y0 - y:y1 - y, x0 - x:x1 - x]
    d = dst[y0:y1, x0:x1]
    dst[y0:y1, x0:x1] = s + d * (1 - s[..., 3:4])

def radial(r):            # reveal pixels within radius r (logo px), soft edge
    return lambda L: np.clip((r * L.maxd - L.dist) / (6 * L.s / 0.2 + 1e-3), 0, 1)

def wipe_up(f):           # reveal from bottom up, f 0..1
    return lambda L: np.clip(((L.yy / L.h) - (1 - f) * 1.05 + 0.05) / 0.05, 0, 1)

def wipe_x(f, rtl=True):  # horizontal wipe; Arabic reads right-to-left
    def m(L):
        u = L.xx / L.w
        u = 1 - u if rtl else u
        return np.clip((f * 1.1 - u) / 0.1, 0, 1)
    return m

# ---------- the four bugs (logo top-left) ----------
BUG_W, BUG_X, BUG_Y = 270, 54, 200
BUG_DUR = 10.0

def bug_state(kind, t):
    st = {p: {} for p in PARTS}
    shine = None
    if kind == 'a':   # شروق: sun rises, rays grow, arcs draw up, text fades up
        st['sun'] = dict(scale=max(1e-3, back_out(prog(t, 0.0, 0.6))), op=prog(t, 0, .2))
        st['rays'] = dict(reveal=radial(ease_out(prog(t, 0.25, 1.05))))
        st['arcs'] = dict(reveal=wipe_up(ease_in_out(prog(t, 0.5, 1.25))))
        for i, p in enumerate(['arabic', 'en1', 'en2']):
            k = ease_out(prog(t, 0.95 + i * .15, 1.5 + i * .15)); st[p] = dict(op=k, dy=(1 - k) * 14)
        shine = prog(t, 6.0, 7.0) if 6.0 <= t <= 7.0 else None
    elif kind == 'b': # انزلاق: whole logo slides in from the left edge with a soft settle
        k = back_out(prog(t, 0.0, 0.8), 1.2)
        for p in PARTS: st[p] = dict(dx=(1 - k) * -(BUG_W + BUG_X + 20), op=prog(t, 0, .3))
        st['rays'].update(rot=(1 - ease_out(prog(t, 0, 1.0))) * -25)
        shine = prog(t, 0.9, 1.6) if 0.9 <= t <= 1.6 else (prog(t, 6.0, 7.0) if 6.0 <= t <= 7.0 else None)
    elif kind == 'c': # لمعة: soft fade-in and scale, then a light sweep
        k = ease_out(prog(t, 0.0, 0.9))
        for p in PARTS: st[p] = dict(op=k, scale=0.9 + 0.1 * k)
        shine = prog(t, 0.7, 1.7) if 0.7 <= t <= 1.7 else (prog(t, 5.5, 6.5) if 5.5 <= t <= 6.5 else None)
    elif kind == 'd': # تجميع: parts assemble one after another
        k = back_out(prog(t, 0.0, 0.5)); st['sun'] = dict(scale=max(1e-3, k), op=prog(t, 0, .15))
        k = ease_out(prog(t, 0.2, 0.9)); st['rays'] = dict(rot=(1 - k) * -90, scale=0.4 + 0.6 * k, op=k)
        k = ease_out(prog(t, 0.5, 1.1)); st['arcs'] = dict(scale=0.7 + 0.3 * k, op=k)
        st['arabic'] = dict(reveal=wipe_x(ease_in_out(prog(t, 0.9, 1.6)), rtl=True))
        k = ease_out(prog(t, 1.4, 1.9)); st['en1'] = dict(op=k, dx=(1 - k) * -18)
        k = ease_out(prog(t, 1.6, 2.1)); st['en2'] = dict(op=k, dx=(1 - k) * 18)
        shine = prog(t, 6.0, 7.0) if 6.0 <= t <= 7.0 else None
    return st, shine

# ---------- outro ----------
OUT_W = 800
OUT_DUR = 5.0

def bg_frame(t, cache={}):
    if 'base' not in cache:
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        r = np.hypot((xx - W / 2) / W, (yy - H * 0.46) / H)
        top = np.array([0.16, 0.11, 0.05]); edge = np.array([0.015, 0.012, 0.01])
        k = np.clip(r / 0.62, 0, 1)[..., None]
        cache['base'] = top * (1 - k) + edge * k
        cache['ang'] = np.arctan2(yy - H * 0.40, xx - W / 2)
        cache['r'] = r
        rng = np.random.default_rng(7)
        cache['dust'] = rng.random((70, 4))
    base = cache['base'].copy()
    # slow rotating light beams behind the logo
    beams = (0.5 + 0.5 * np.cos(cache['ang'] * 12 + t * 0.35)) ** 6
    beams *= np.exp(-cache['r'] / 0.28)[...] * 0.22 * ease_out(prog(t, 0.4, 1.6))
    base = base + beams[..., None] * GOLD
    # drifting gold dust
    for x, y, sz, ph in cache['dust']:
        px = int(x * W); py = int((y - t * 0.02 * (0.5 + ph)) % 1 * H)
        a = 0.25 + 0.35 * (0.5 + 0.5 * math.sin(t * 2 + ph * 6))
        rr = 1 + int(sz * 3)
        base[max(0, py - rr):py + rr, max(0, px - rr):px + rr] += GOLD * a * 0.6
    fade = ease_out(prog(t, 0, 0.5))
    return np.clip(base * fade, 0, 1)

def outro_state(t):
    st = {p: {} for p in PARTS}
    st['sun'] = dict(scale=max(1e-3, back_out(prog(t, 0.2, 0.9))), op=prog(t, 0.2, 0.4))
    st['rays'] = dict(reveal=radial(ease_out(prog(t, 0.55, 1.5))))
    st['arcs'] = dict(reveal=wipe_up(ease_in_out(prog(t, 0.9, 1.8))))
    st['arabic'] = dict(reveal=wipe_x(ease_in_out(prog(t, 1.5, 2.4)), rtl=True))
    k = ease_out(prog(t, 2.2, 2.8)); st['en1'] = dict(op=k, dy=(1 - k) * 30)
    k = ease_out(prog(t, 2.45, 3.05)); st['en2'] = dict(op=k, dy=(1 - k) * 30)
    gs = 0.1 * ease_out(prog(t, 0.0, 0.2))  # scale breathe: whole logo slowly pushes in
    for p in PARTS: st[p]['scale'] = st[p].get('scale', 1.0) * (0.96 + 0.04 * ease_in_out(prog(t, 0, 5)))
    shine = prog(t, 3.1, 4.0) if 3.1 <= t <= 4.0 else None
    return st, shine

# ---------- encode ----------
def encoder(path, alpha):
    if PREVIEW:
        args = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20', '-vf', 'scale=540:960']
    elif alpha:
        args = ['-c:v', 'prores_ks', '-profile:v', '4444', '-pix_fmt', 'yuva444p10le', '-vendor', 'apl0']
    else:
        args = ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '14', '-preset', 'slow', '-movflags', '+faststart']
    return subprocess.Popen([FFMPEG, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{W}x{H}',
                             '-r', str(FPS), '-i', '-', *args, path], stdin=subprocess.PIPE)

def to_bytes(prem, checker=False):
    a = prem[..., 3:4]
    rgb = np.where(a > 1e-4, prem[..., :3] / np.maximum(a, 1e-4), 0)
    if checker:  # preview: show over a mid-grey "footage" stand-in
        bgc = np.full_like(rgb, 0.32)
        rgb = rgb * a + bgc * (1 - a); a = np.ones_like(a)
    return (np.clip(np.dstack([rgb, a]), 0, 1) * 255 + 0.5).astype(np.uint8).tobytes()

def run_bug(kind):
    L = Logo(BUG_W)
    ext = 'mp4' if PREVIEW else 'mov'
    p = encoder(f'{OUT}/logo_{kind}.{ext}', alpha=True)
    for f in range(int(BUG_DUR * FPS)):
        t = f / FPS
        st, sh = bug_state(kind, t)
        a = L.frame(st)
        canvas = np.zeros((H, W, 4), np.float32)
        over(canvas, colorize(a, shine_map(L, sh), glow=4, glow_op=0.35), BUG_X, BUG_Y)
        p.stdin.write(to_bytes(canvas, checker=PREVIEW))
    p.stdin.close(); p.wait()

def run_outro(with_bg):
    L = Logo(OUT_W)
    ox, oy = (W - L.w) // 2, int(H * 0.40 - L.ay)
    ext = 'mp4' if PREVIEW or with_bg else 'mov'
    p = encoder(f'{OUT}/outro{"" if with_bg else "_alpha"}.{ext}', alpha=not with_bg)
    for f in range(int(OUT_DUR * FPS)):
        t = f / FPS
        st, sh = outro_state(t)
        a = L.frame(st)
        canvas = np.zeros((H, W, 4), np.float32)
        if with_bg: canvas[..., :3] = bg_frame(t); canvas[..., 3] = 1
        glow_op = 0.55 * ease_out(prog(t, 0.3, 1.5)) * (1 + 0.25 * math.sin(t * 2.2))
        over(canvas, colorize(a, shine_map(L, sh, width=0.08), glow=14, glow_op=glow_op), ox, oy)
        p.stdin.write(to_bytes(canvas, checker=PREVIEW and not with_bg))
    p.stdin.close(); p.wait()

def run_stills():
    """full-frame PNG of the settled bug, to hold after a MOV ends."""
    L = Logo(BUG_W)
    canvas = np.zeros((H, W, 4), np.float32)
    over(canvas, colorize(L.frame({}), 0, glow=4, glow_op=0.35), BUG_X, BUG_Y)
    a = canvas[..., 3:4]; rgb = np.where(a > 1e-4, canvas[..., :3] / np.maximum(a, 1e-4), 0)
    Image.fromarray((np.clip(np.dstack([rgb, a]), 0, 1) * 255 + .5).astype(np.uint8)).save(f'{OUT}/logo_hold.png')


def job(name):
    if name.startswith('bug_'): run_bug(name[-1])
    elif name == 'outro': run_outro(True)
    elif name == 'outro_alpha': run_outro(False)
    elif name == 'stills': run_stills()
    return name

if __name__ == '__main__':
    import multiprocessing; multiprocessing.set_start_method('spawn', force=True)  # same as Windows
    os.makedirs(OUT, exist_ok=True)
    jobs = ['outro_alpha', 'bug_a', 'bug_b', 'bug_c', 'bug_d', 'outro', 'stills']
    with Pool(min(4, os.cpu_count() or 1), initializer=init_worker, initargs=(ARGS.logo,)) as pool:
        for n in pool.imap_unordered(job, jobs): print('done:', n, flush=True)
