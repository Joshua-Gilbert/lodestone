"""How trace.txt was made from plate.png (the 1921 plate, 532 x 668).

    python3 trace.py [plate.png] > trace.txt       (needs opencv, scikit-image, scipy)

Not part of the build: trace.txt is the drawing, and can be edited by hand
(then run mksplash.py).  This is the tracing it started from.

  1. The stone: the plate blurred and thresholded (Otsu), opened to drop
     the nails, closed, the biggest blob; its bottom cut along a hand-placed
     curve, where the hanging bundles of nails would otherwise count as
     stone.  Its outline simplified to within 2 pixels.
  2. The nails as ridges: contrast equalised (CLAHE), then Sato's ridge
     filter for bright ridges on the stone and dark ones on the paper,
     blended across the stone's edge so the edge itself isn't a ridge.
  3. Lines from the ridges: a short line integral at 45 angles; its
     strongest points (and, at crossings, every strong angle) seed lines,
     each refitted to its ridge and extended along it over short gaps.  A
     line is kept only if enough of it is ridge that the lines kept
     before don't already explain; nearly collinear repeats and lines
     hugging the stone's edge are dropped.  Then a gentler second pass.
  4. Which end is the head: the wider end of the ridge; if neither is
     clearly wider, the end nearer the middle of the stone (nails stick
     out from it point first, as they do in the plate).
"""
import sys
import cv2
import numpy as np
from scipy.ndimage import map_coordinates, maximum_filter
from skimage.filters import sato

PLATE = sys.argv[1] if len(sys.argv) > 1 else 'plate.png'
# the stone's bottom, placed by hand: below this line it is nails, not stone
BOTTOM = [(0, 430), (75, 450), (110, 480), (150, 500), (200, 520), (250, 535), (300, 540), (340, 538),
          (445, 532), (470, 515), (532, 505), (532, 668), (0, 668)]


def disk(r):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def the_stone(g0):
    b = cv2.GaussianBlur(g0, (0, 0), 2.0)
    _, dark = cv2.threshold(b, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    m = cv2.morphologyEx(cv2.morphologyEx(dark, cv2.MORPH_OPEN, disk(7)), cv2.MORPH_CLOSE, disk(12))
    _, lab, st, _ = cv2.connectedComponentsWithStats(m)
    m = (lab == 1 + np.argmax(st[1:, cv2.CC_STAT_AREA])).astype(np.uint8) * 255
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    auto = np.zeros_like(m)
    cv2.drawContours(auto, [max(cs, key=cv2.contourArea)], -1, 255, -1)
    cut = np.zeros(g0.shape, np.uint8)
    cv2.fillPoly(cut, [np.array(BOTTOM, np.int32)], 1)
    rock = (auto > 0) & (cut == 0)
    return cv2.morphologyEx(rock.astype(np.uint8) * 255, cv2.MORPH_CLOSE, disk(4)) > 0


def ridges(g0, rock):
    g = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(6, 6)).apply(g0).astype(float) / 255
    sig = [1.2, 1.8, 2.5]
    w = cv2.GaussianBlur(rock.astype(float), (0, 0), 3)
    R = w * sato(g, sigmas=sig, black_ridges=False) + (1 - w) * sato(g, sigmas=sig, black_ridges=True)
    return R / np.percentile(R, 99.5)


def find_nails(R, rock):
    H, W = R.shape
    dist_in = cv2.distanceTransform(rock.astype(np.uint8), cv2.DIST_L2, 3)
    dist_out = cv2.distanceTransform((~rock).astype(np.uint8), cv2.DIST_L2, 3)
    bord = np.where(rock, dist_in, dist_out)            # distance to the stone's edge
    gy, gx = np.gradient(cv2.GaussianBlur((dist_in - dist_out).astype(np.float32), (0, 0), 4))

    def prof(p0, d, ts, half=1.5):
        """the ridge's strength along a line, the best within +-half across it"""
        nrm = np.array([-d[1], d[0]])
        best = None
        for o in np.linspace(-half, half, 5):
            pts = p0[None, :] + ts[:, None] * d[None, :] + o * nrm[None, :]
            v = map_coordinates(R, [pts[:, 1], pts[:, 0]], order=1, mode='constant')
            best = v if best is None else np.maximum(best, v)
        return best

    def refine(x1, y1, x2, y2, lo, gap):
        p0 = np.array([x1, y1], float)
        p1 = np.array([x2, y2], float)
        L = np.linalg.norm(p1 - p0)
        d = (p1 - p0) / L
        for _ in range(2):                              # onto the ridge's centre
            ts = np.arange(0, L, 1.0)
            nrm = np.array([-d[1], d[0]])
            offs = np.linspace(-3, 3, 13)
            P = p0[None, None, :] + ts[:, None, None] * d + offs[None, :, None] * nrm
            v = map_coordinates(R, [P[..., 1], P[..., 0]], order=1, mode='constant')
            w = np.maximum(v - 0.2, 0) ** 2
            if w.sum() < 1e-6:
                return None
            ys = (w * offs[None, :]).sum(1) / np.maximum(w.sum(1), 1e-9)
            ok = w.sum(1) > 1e-3
            if ok.sum() < 5:
                return None
            a, b = np.polyfit(ts[ok], ys[ok], 1)
            p0, p1 = p0 + b * nrm, p0 + L * d + (a * L + b) * nrm
            L = np.linalg.norm(p1 - p0)
            d = (p1 - p0) / L
        ts = np.arange(-160, L + 160, 1.0)               # along it, both ways
        v = prof(p0, d, ts)
        on = v > lo
        i0 = int(np.searchsorted(ts, 0))
        i1 = int(np.searchsorted(ts, L)) - 1
        if on[i0:i1 + 1].mean() < 0.6:
            return None
        a, miss = i0, 0
        while a > 0:
            if on[a - 1]:
                a -= 1; miss = 0
            else:
                miss += 1
                if miss > gap:
                    break
                a -= 1
        a += miss if not on[a] else 0
        while a < i0 and not on[a]:
            a += 1
        b, miss = i1, 0
        while b < len(ts) - 1:
            if on[b + 1]:
                b += 1; miss = 0
            else:
                miss += 1
                if miss > gap:
                    break
                b += 1
        while b > i1 and not on[b]:
            b -= 1
        return p0 + ts[a] * d, p0 + ts[b] * d, v[a:b + 1].mean()

    KL = 25                                             # the line integral's length
    angs = np.deg2rad(np.arange(0, 180, 4))
    resp = []
    for a in angs:
        k = np.zeros((KL + 2, KL + 2), np.float32)
        c = (KL + 1) / 2
        dx, dy = np.cos(a) * KL / 2, np.sin(a) * KL / 2
        cv2.line(k, (int(round(c * 16 - dx * 16)), int(round(c * 16 - dy * 16))),
                 (int(round(c * 16 + dx * 16)), int(round(c * 16 + dy * 16))), 1.0, 1, cv2.LINE_AA, 4)
        resp.append(cv2.filter2D(R.astype(np.float32), -1, k / k.sum()))
    resp = np.stack(resp)
    best, arg = resp.max(0), resp.argmax(0)
    ys, xs = np.nonzero((best == maximum_filter(best, size=5)) & (best > 0.40))
    seeds = set(zip(best[ys, xs], xs, ys, arg[ys, xs]))
    for i in range(len(angs)):                          # crossings: every strong angle
        r = resp[i]
        lm = (r > 0.45) & (r >= resp[(i - 1) % len(angs)]) & (r >= resp[(i + 1) % len(angs)]) & (r == maximum_filter(r, size=7))
        y2, x2 = np.nonzero(lm)
        seeds |= set(zip(r[y2, x2], x2, y2, np.full(len(x2), i)))
    seeds = sorted(seeds, key=lambda s: -s[0])

    keep = []
    cov = np.zeros((H, W), np.uint8)                    # what the lines kept explain

    def accept(s0, s1, strict):
        L = np.linalg.norm(s1 - s0)
        d = (s1 - s0) / L
        ts = np.arange(0, L, 1.0)
        pts = s0 + ts[:, None] * d
        xi = np.clip(np.round(pts[:, 0]).astype(int), 0, W - 1)
        yi = np.clip(np.round(pts[:, 1]).astype(int), 0, H - 1)
        unc = cov[yi, xi] == 0
        vu = prof(s0, d, ts, half=0.7)[unc]
        if strict:
            if unc.sum() < 12 or vu.mean() < 0.36 or (vu > 0.25).mean() < 0.8:
                return
        elif unc.sum() < 14 or vu.mean() < 0.30 or (vu > 0.22).mean() < 0.75:
            return
        for k0, k1 in keep:                             # a repeat of one kept?
            kl = np.linalg.norm(k1 - k0)
            kd = (k1 - k0) / kl
            if abs(np.dot(kd, d)) < 0.99:
                continue
            nrm = np.array([-kd[1], kd[0]])
            if abs(np.dot(s0 - k0, nrm)) > 2.5 or abs(np.dot(s1 - k0, nrm)) > 2.5:
                continue
            ta = sorted([np.dot(s0 - k0, kd), np.dot(s1 - k0, kd)])
            if min(ta[1], kl) - max(ta[0], 0) > -4:
                return
        ts = np.linspace(0, L, 20)                      # along the stone's edge?
        pts = s0 + ts[:, None] * d
        xi = np.clip(pts[:, 0].astype(int), 0, W - 1)
        yi = np.clip(pts[:, 1].astype(int), 0, H - 1)
        nb = bord[yi, xi] < 5
        if nb.mean() > 0.5:
            nx, ny = gx[yi, xi], gy[yi, xi]
            nn = np.hypot(nx, ny) + 1e-9
            if np.median(np.abs(d[0] * (-ny / nn) + d[1] * (nx / nn))[nb]) > 0.8:
                return
        keep.append((s0, s1))
        cv2.line(cov, tuple(np.round(s0).astype(int)), tuple(np.round(s1).astype(int)), 1, 3)

    def run(seeds, lo, gap, mmin, strict):
        for sc, x, y, ai in seeds:
            if cov[y, x]:
                continue
            d = np.array([np.cos(angs[ai]), np.sin(angs[ai])])
            p0 = np.array([x, y], float) - d * KL / 2
            r = refine(*p0, *(p0 + d * KL), lo=lo, gap=gap)
            if r is None:
                continue
            s0, s1, mean = r
            if np.linalg.norm(s1 - s0) >= 16 and mean >= mmin:
                accept(s0, s1, strict)

    run(seeds, 0.24, 4, 0.30, True)
    ys, xs = np.nonzero((best == maximum_filter(best, size=5)) & (best > 0.30))
    run(sorted(zip(best[ys, xs], xs, ys, arg[ys, xs]), reverse=True), 0.20, 3, 0.27, False)
    return keep


def heads_first(g0, rock, nails):
    g = cv2.createCLAHE(2.5, (6, 6)).apply(g0).astype(float)
    bg = cv2.GaussianBlur(g, (0, 0), 6)
    N = np.where(rock, g - bg, bg - g)                  # nails brighter than around them
    cy, cx = np.argwhere(rock).mean(0)

    def width(p, d, t):
        nrm = np.array([-d[1], d[0]])
        pts = p + t * d + np.arange(-6, 6.5, 0.5)[:, None] * nrm
        return (map_coordinates(N, [pts[:, 1], pts[:, 0]], order=1) > 18).sum() * 0.5

    out = []
    for a, b in nails:
        d = (b - a) / np.linalg.norm(b - a)
        wa = max(width(a, d, t) for t in (1.5, 3, 4.5))
        wb = max(width(b, -d, t) for t in (1.5, 3, 4.5))
        if abs(wa - wb) >= 1.5:
            head_a = wa > wb
        else:
            head_a = np.hypot(*(a - [cx, cy])) < np.hypot(*(b - [cx, cy]))
        out.append((a, b) if head_a else (b, a))
    return out


if __name__ == '__main__':
    g0 = cv2.imread(PLATE, cv2.IMREAD_GRAYSCALE)
    rock = the_stone(g0)
    nails = heads_first(g0, rock, find_nails(ridges(g0, rock), rock))
    cs, _ = cv2.findContours(rock.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline = cv2.approxPolyDP(max(cs, key=cv2.contourArea), 2.0, True)[:, 0, :]
    print('# Lodestone start-up picture, traced from Fig. 1 of F. A. Annett,\n'
          '# Electrical Machinery (McGraw-Hill, 1921): public domain.\n'
          "# Plate pixels (532 x 668).  R x y: the stone's outline, in order.\n"
          '# N hx hy tx ty: a nail, head then point.  Edit freely, then run mksplash.py.')
    for x, y in outline:
        print('R %d %d' % (x, y))
    for a, b in nails:
        print('N %.1f %.1f %.1f %.1f' % (a[0], a[1], b[0], b[1]))
