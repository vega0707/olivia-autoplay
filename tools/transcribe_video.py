# -*- coding: utf-8 -*-
"""视频 → 音频 → AMT-APC ONNX 转录 → 钢琴卷帘图。
用法: python transcribe_video.py <video.mp4> <out_prefix> [duration_sec]
输出: <out_prefix>.mid + <out_prefix>_roll.png (供 AI 读谱认曲)
"""
import os, sys, subprocess, tempfile

REPO = r"C:\Users\locea\AppData\Local\Temp\2m4l"   # 2midi4lin 源码 clone
sys.path.insert(0, REPO)

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
import pretty_midi

def extract_audio(video, wav_path, duration):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ff, "-y", "-ss", "0", "-t", str(duration), "-i", video,
           "-ac", "1", "-ar", "16000", "-vn", wav_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(wav_path):
        raise RuntimeError("ffmpeg failed: " + r.stderr[-400:])

def roll_png(mid_path, png_path, total_sec):
    pm = pretty_midi.PrettyMIDI(mid_path)
    notes = [n for inst in pm.instruments for n in inst.notes]
    if not notes:
        print("NO NOTES"); return 0
    tmax = max(total_sec, max(n.end for n in notes) + 0.5)
    pmin = max(21, min(n.pitch for n in notes) - 2)
    pmax = min(108, max(n.pitch for n in notes) + 2)
    W, H = 2400, 820
    TOP, BOT = 46, 10
    img = Image.new("RGB", (W, H), (250, 250, 247))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 15)
        fontb = ImageFont.truetype("arialbd.ttf", 17)
    except Exception:
        font = fontb = ImageFont.load_default()
    span = pmax - pmin + 1
    def y_of(p): return TOP + (pmax - p) * (H - TOP - BOT) / span
    BLACK = {1, 3, 6, 8, 10}
    # 黑键行底纹 + C 线
    for p in range(pmin, pmax + 1):
        if (p % 12) in BLACK:
            d.rectangle([0, y_of(p) - (H - TOP - BOT) / span / 2, W, y_of(p) + (H - TOP - BOT) / span / 2], fill=(238, 238, 235))
    for p in range(pmin, pmax + 1):
        if p % 12 == 0:
            y = y_of(p)
            d.line([0, y, W, y], fill=(180, 180, 175), width=1)
            d.text((4, y - 16), f"C{p//12 - 1}", fill=(120, 120, 120), font=font)
    # 时间网格
    for t in range(0, int(tmax) + 1):
        x = t / tmax * W
        major = (t % 5 == 0)
        d.line([x, TOP, x, H - BOT], fill=(200, 200, 196) if not major else (160, 160, 156), width=1)
        if major:
            d.text((x + 3, 8), f"{t}s", fill=(90, 90, 90), font=fontb)
    # 音符条
    for n in notes:
        x0, x1 = n.start / tmax * W, n.end / tmax * W
        if x1 - x0 < 3: x1 = x0 + 3
        y = y_of(n.pitch)
        h = max(5, (H - TOP - BOT) / span - 1)
        col = (30, 60, 160) if (n.pitch % 12) not in BLACK else (15, 30, 95)
        d.rectangle([x0, y - h / 2, x1, y + h / 2], fill=col)
    img.save(png_path)
    print(f"NOTES={len(notes)} pitch[{pmin},{pmax}] dur={tmax:.1f}s -> {png_path}")
    return len(notes)

def main():
    video, prefix = sys.argv[1], sys.argv[2]
    duration = float(sys.argv[3]) if len(sys.argv) > 3 else 45.0
    tmp = tempfile.mkdtemp(prefix="tr_")
    wav = os.path.join(tmp, "a.wav")
    extract_audio(video, wav, duration)
    from src.transcription.onnx_transcriber import ONNXTranscriber
    t = ONNXTranscriber(style="level2", mode="apc")
    mid = prefix + ".mid"
    t.transcribe(wav, mid)
    roll_png(mid, prefix + "_roll.png", duration)

if __name__ == "__main__":
    main()
