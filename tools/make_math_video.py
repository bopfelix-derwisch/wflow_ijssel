#!/usr/bin/env python3
"""Bouw de wiskunde-uitleg-video van POC E uit het MathJax-slidedeck.

Screenshot elke slide van tools/math_slides.html met headless chromium (crisp
MathJax), assembleert holds + crossfades, en encodeert met ffmpeg naar H.264.
Uitvoer: dashboard/assimilatie_wiskunde.mp4
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
DECK = "file://" + os.path.join(HERE, "math_slides.html")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "dashboard", "assimilatie_wiskunde.mp4")
W, H, FPS, XF = 1280, 720, 25, 12

# seconden per slide (index 0..18) — geschaald op leeslast
DUR = [6, 11, 9, 10, 11, 11, 11, 10, 10, 10, 9, 12, 10, 9, 12, 10, 11, 11, 12]
N = len(DUR)

CHROME = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")


def render_slide(i, out_png):
    cmd = [CHROME, "--headless=new", "--no-sandbox",
           "--enable-unsafe-swiftshader", "--use-gl=angle", "--use-angle=swiftshader",
           "--hide-scrollbars", "--force-device-scale-factor=1",
           f"--window-size={W},{H}", "--virtual-time-budget=9000",
           f"--screenshot={out_png}", f"{DECK}?s={i}"]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=90)
    if not os.path.exists(out_png):
        raise RuntimeError(f"slide {i} niet gerenderd")
    img = Image.open(out_png).convert("RGB").resize((W, H))
    return np.asarray(img)[:, :, ::-1]   # BGR


def main():
    if not CHROME:
        print("chromium niet gevonden"); sys.exit(1)
    tmp = tempfile.mkdtemp()
    slides = []
    for i in range(N):
        arr = render_slide(i, os.path.join(tmp, f"s{i}.png"))
        slides.append(arr)
        print(f"  slide {i+1}/{N} gerenderd")

    # ffmpeg-pipe (H.264) of cv2-fallback
    use_ff = shutil.which("ffmpeg") is not None
    if use_ff:
        p = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
             "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
        write = lambda f: p.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    else:
        import cv2
        vw = cv2.VideoWriter(OUT, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
        write = lambda f: vw.write(np.ascontiguousarray(f, dtype=np.uint8))

    nframes = 0
    for k in range(N):
        hold = int(DUR[k] * FPS)
        for _ in range(hold):
            write(slides[k]); nframes += 1
        if k < N - 1:
            a = slides[k].astype(np.float32); b = slides[k + 1].astype(np.float32)
            for j in range(XF):
                t = (j + 1) / (XF + 1)
                write((a * (1 - t) + b * t).astype(np.uint8)); nframes += 1

    if use_ff:
        p.stdin.close()
        if p.wait() != 0:
            print("ffmpeg-encode faalde"); sys.exit(1)
        codec = "h264"
    else:
        vw.release(); codec = "mp4v"
    print(f"geschreven: {OUT}  ({nframes} frames, {nframes/FPS:.1f}s, {codec})")


if __name__ == "__main__":
    main()
