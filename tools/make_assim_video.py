#!/usr/bin/env python3
"""Genereer een stil, ondertiteld uitleg-filmpje van POC E (data-assimilatie).

Bouwt frames met Pillow uit de echte /api/assimilation-data en encodeert met cv2
naar MP4 (mp4v). Geen ffmpeg/TTS nodig. Uitvoer: assimilatie_uitleg.mp4.
"""
import json
import sys
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

API = "http://127.0.0.1:8000/api/assimilation"
OUT = sys.argv[1] if len(sys.argv) > 1 else "assimilatie_uitleg.mp4"
W, H, FPS = 1280, 720, 25

BG    = (8, 12, 20)
GRID  = (26, 46, 66)
TXT   = (215, 224, 230)
MUT   = (128, 150, 165)
GREEN = (90, 190, 100)
RED   = (240, 95, 92)
TEAL  = (90, 200, 185)
ACC   = (79, 195, 247)

FDIR = "/usr/share/fonts/truetype/dejavu/"
def font(sz, bold=False):
    return ImageFont.truetype(FDIR + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), sz)
F_TITLE, F_H2, F_CAP, F_SM, F_AX = font(30, 1), font(26, 1), font(23), font(16), font(14)


def blend(c, a):
    a = max(0.0, min(1.0, a))
    return tuple(int(BG[i] + (c[i] - BG[i]) * a) for i in range(3))


def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    return lines


def caption(draw, text, alpha, y0=582, color=TXT):
    for i, ln in enumerate(wrap(draw, text, F_CAP, W - 180)):
        draw.text((90, y0 + i * 34), ln, font=F_CAP, fill=blend(color, alpha))


def dashed(draw, pts, color, width=3, dash=14, gap=10):
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        seg = np.hypot(x1 - x0, y1 - y0)
        if seg < 1:
            continue
        n = int(seg // (dash + gap)) + 1
        for k in range(n):
            a = (k * (dash + gap)) / seg
            b = min(1.0, (k * (dash + gap) + dash) / seg)
            draw.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                       (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)], fill=color, width=width)


def polyline(draw, pts, color, width=3, reveal=1.0):
    k = max(0, min(len(pts), int(round(len(pts) * reveal))))
    if k >= 2:
        draw.line(pts[:k], fill=color, width=width, joint="curve")
    return pts[:k]


# ── data ────────────────────────────────────────────────────────────────────
def fetch():
    with urllib.request.urlopen(API, timeout=180) as r:
        return json.load(r)


def main():
    d = fetch()
    if not d.get("available"):
        print("assimilatie niet beschikbaar:", d.get("reason")); sys.exit(1)
    lv, s = d["live"], d["summary"]
    phf, pha = d["per_horizon_free"], d["per_horizon_assim"]

    obs = lv["recent_obs"]
    nr = len(obs)
    anchor = obs[-1]
    free = [anchor] + lv["free"]
    mean = [anchor] + lv["mean"]
    p10 = [anchor] + lv["p10"]
    p90 = [anchor] + lv["p90"]
    N = nr + len(lv["free"])                     # totaal aantal x-posities
    fc_idx = list(range(nr - 1, N))              # forecast begint op laatste meting

    allv = obs + free + mean + p10 + p90
    ymin, ymax = min(allv) * 0.88, max(allv) * 1.08
    PX0, PY0, PX1, PY1 = 95, 150, 1185, 520

    def X(i): return PX0 + (PX1 - PX0) * i / (N - 1)
    def Y(v): return PY1 - (PY1 - PY0) * (v - ymin) / (ymax - ymin)

    obs_pts  = [(X(i), Y(obs[i])) for i in range(nr)]
    free_pts = [(X(fc_idx[i]), Y(free[i])) for i in range(len(free))]
    mean_pts = [(X(fc_idx[i]), Y(mean[i])) for i in range(len(mean))]
    p10_pts  = [(X(fc_idx[i]), Y(p10[i])) for i in range(len(p10))]
    p90_pts  = [(X(fc_idx[i]), Y(p90[i])) for i in range(len(p90))]

    # rmse-paneel
    rh = phf["horizon"]
    rf, ra = phf["rmse"], pha["rmse"]
    rmax = max(max(rf), max(ra)) * 1.12
    def RX(h): return PX0 + (PX1 - PX0) * (h - 1) / (len(rh) - 1)
    def RY(v): return PY1 - (PY1 - PY0) * v / rmax

    def grid_y(draw, vmin, vmax, yf, unit):
        for g in np.linspace(vmin, vmax, 5):
            y = yf(g)
            draw.line([(PX0, y), (PX1, y)], fill=GRID, width=1)
            draw.text((PX0 - 62, y - 8), f"{int(g)}", font=F_AX, fill=MUT)
        draw.text((PX0 - 62, PY0 - 30), unit, font=F_AX, fill=MUT)

    def header(draw, sub):
        draw.text((90, 46), "Data-assimilatie — de verwachting bijsturen met de meting", font=F_TITLE, fill=TXT)
        draw.text((90, 100), sub, font=F_H2, fill=blend(ACC, 1))

    def legend(draw, items, y=560):
        x = 95
        for label, col in items:
            draw.line([(x, y + 10), (x + 34, y + 10)], fill=col, width=4)
            draw.text((x + 42, y), label, font=F_SM, fill=MUT)
            x += 52 + draw.textlength(label, font=F_SM)

    # ── frame-renderer ────────────────────────────────────────────────────────
    def discharge_frame(obs_r, free_r, assim_r, cap, sub, band=True):
        img = Image.new("RGB", (W, H), BG); dr = ImageDraw.Draw(img)
        header(dr, sub)
        grid_y(dr, ymin, ymax, Y, "m³/s")
        # scheidslijn meting|verwachting
        xsep = X(nr - 1)
        dr.line([(xsep, PY0), (xsep, PY1)], fill=blend(ACC, 0.5), width=1)
        dr.text((xsep + 6, PY0 - 2), "vandaag", font=F_AX, fill=blend(ACC, 0.8))
        # band
        if band and assim_r > 0.02:
            k = max(2, int(len(p90_pts) * assim_r))
            poly = p90_pts[:k] + p10_pts[:k][::-1]
            dr.polygon(poly, fill=blend(TEAL, 0.16 * assim_r))
        # vrije verwachting (rood, gestreept)
        if free_r > 0.02:
            k = max(2, int(len(free_pts) * free_r))
            dashed(dr, free_pts[:k], blend(RED, free_r), width=3)
        # geassimileerd (teal)
        if assim_r > 0.02:
            polyline(dr, mean_pts, blend(TEAL, assim_r), width=4, reveal=assim_r)
        # meting (groen) + punten
        pts = polyline(dr, obs_pts, blend(GREEN, obs_r), width=4, reveal=obs_r)
        for (x, y) in pts:
            dr.ellipse([x - 4, y - 4, x + 4, y + 4], fill=blend(GREEN, obs_r))
        legend(dr, [("gemeten (RWS)", GREEN), ("vrije verwachting", RED), ("geassimileerd + band", TEAL)])
        caption(dr, cap, 1.0)
        return img

    def rmse_frame(reveal, cap):
        img = Image.new("RGB", (W, H), BG); dr = ImageDraw.Draw(img)
        header(dr, "Het bewijs — fout per voorspeldag (hindcast)")
        grid_y(dr, 0, rmax, RY, "m³/s")
        for h in rh:
            dr.text((RX(h) - 4, PY1 + 8), str(h), font=F_AX, fill=MUT)
        dr.text((PX0, PY1 + 30), "lead-time (dagen vooruit)", font=F_AX, fill=MUT)
        kf = max(2, int(len(rh) * reveal))
        fpts = [(RX(rh[i]), RY(rf[i])) for i in range(len(rh))]
        apts = [(RX(rh[i]), RY(ra[i])) for i in range(len(rh))]
        polyline(dr, fpts, RED, 3, reveal)
        polyline(dr, apts, TEAL, 3, reveal)
        for i in range(min(kf, len(rh))):
            for pts, col in ((fpts, RED), (apts, TEAL)):
                x, y = pts[i]; dr.ellipse([x - 3, y - 3, x + 3, y + 3], fill=col)
        legend(dr, [("vrij — RMSE", RED), ("geassimileerd — RMSE", TEAL)])
        caption(dr, cap, 1.0)
        return img

    def title_card(title, lines, a=1.0):
        img = Image.new("RGB", (W, H), BG); dr = ImageDraw.Draw(img)
        dr.text((90, 250), title, font=F_TITLE, fill=blend(TXT, a))
        for i, ln in enumerate(lines):
            dr.text((90, 320 + i * 40), ln, font=F_H2, fill=blend(MUT, a))
        dr.text((90, 640), "Waterlab · POC E · data-assimilatie (EnKF-familie)", font=F_SM, fill=blend(ACC, a))
        return img

    # ── scenario ──────────────────────────────────────────────────────────────
    def R(a, b, t): return max(0.0, min(1.0, (t - a) / (b - a)))
    frames = []
    tp, tq = lv["tau_prior"], lv["tau_post"]
    dp, dq = lv["target_prior"], lv["target_post"]
    cap1 = "De afvoer bij Westervoort — de laatste dagen echt gemeten (groen)."
    cap2 = "Het model voorspelt hoe het wegzakt na de regen. Maar die verwachting zit systematisch te hóóg (rood)."
    cap3 = (f"Data-assimilatie neemt de recente meting mee en stuurt de verwachting bij (blauwgroen), "
            f"met een eerlijke onzekerheidsband. τ {tp}→{tq}, seizoensdoel {dp}→{dq} m³/s.")
    cap4 = (f"Doe je dit voor élke dag in het verleden: de fout is op iedere voorspeldag kleiner. "
            f"Dag 14: {s['rmse_free_day14']} → {s['rmse_assim_day14']} m³/s.")

    def add(img, n):
        arr = np.asarray(img)[:, :, ::-1]
        for _ in range(n):
            frames.append(arr)

    # S0 intro (fade in)
    for i in range(55):
        add(title_card("Hoe de meting de verwachting bijstuurt",
                       ["Data-assimilatie op de IJssel-afvoer, in het kort.",
                        "Van overschatting naar een betrouwbaarder, eerlijk beeld."],
                       a=R(0, 30, i)), 1)
    # S1 meting
    for i in range(85):
        add(discharge_frame(R(0, 55, i), 0, 0, cap1, "De meting", band=False), 1)
    # S2 vrije verwachting
    for i in range(105):
        add(discharge_frame(1, R(0, 70, i), 0, cap2, "De verwachting overschat"), 1)
    # S3 assimilatie
    for i in range(140):
        add(discharge_frame(1, 1, R(0, 80, i), cap3, "Bijgestuurd met de meting"), 1)
    # kort pauze
    add(discharge_frame(1, 1, 1, cap3, "Bijgestuurd met de meting"), 20)
    # S4 rmse
    for i in range(150):
        add(rmse_frame(R(0, 95, i), cap4), 1)
    add(rmse_frame(1, cap4), 20)
    # S5 outro
    for i in range(75):
        a = R(0, 25, i)
        add(title_card("Meting erbij = betrouwbaarder",
                       ["De bijgestuurde verwachting ligt dichter bij de werkelijkheid,",
                        f"en blijft eerlijk over de onzekerheid (band ~{s['coverage_assim']}% dekking).",
                        "Getoetst tegen de RWS-meting — geen tweede waarheid."], a=a), 1)

    # ── encode ──────────────────────────────────────────────────────────────
    import shutil
    codec = "mp4v"
    if shutil.which("ffmpeg"):
        import subprocess
        p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
             "-movflags", "+faststart", OUT],
            stdin=subprocess.PIPE)
        for f in frames:
            p.stdin.write(np.ascontiguousarray(f).tobytes())
        p.stdin.close()
        if p.wait() != 0:
            print("ffmpeg-encode faalde"); sys.exit(1)
        codec = "h264"
    else:
        vw = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        for f in frames:
            vw.write(np.ascontiguousarray(f))
        vw.release()
    print(f"geschreven: {OUT}  ({len(frames)} frames, {len(frames)/FPS:.1f}s, {codec})")


if __name__ == "__main__":
    main()
