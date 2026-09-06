# -*- coding: utf-8 -*-
"""抽取视频若干帧保存为 jpg，并打印视频基本信息。用法: python probe_video_frames.py <video> <outdir>"""
import cv2, os, sys

vid = sys.argv[1]
outdir = sys.argv[2]
os.makedirs(outdir, exist_ok=True)

cap = cv2.VideoCapture(vid)
if not cap.isOpened():
    print("OPEN_FAIL"); sys.exit(1)

fps = cap.get(cv2.CAP_PROP_FPS)
n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
dur = (n / fps) if fps else 0.0
print(f"fps={fps:.2f} frames={n} size={w}x{h} dur={dur:.1f}s")

# 按 5%/25%/50%/75%/95% 位置抽 5 帧
for tag, frac in [("a", 0.05), ("b", 0.25), ("c", 0.50), ("d", 0.75), ("e", 0.95)]:
    idx = max(0, min(n - 1, int(n * frac)))
    cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
    ok, frame = cap.read()
    if ok:
        p = os.path.join(outdir, f"frame_{tag}_{idx}.jpg")
        cv2.imwrite(p, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print("saved", p)
    else:
        print("READ_FAIL at", idx)
cap.release()
