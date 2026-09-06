# -*- coding: utf-8 -*-
"""从转录 MIDI 提取主旋律(skyline)并画成带音名的旋律线图。
用法: python draw_melody.py <in.mid> <out.png> [t0 t1]
"""
import sys, os
import pretty_midi
from PIL import Image, ImageDraw, ImageFont

NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

def name(p): return f"{NOTE_NAMES[p%12]}{p//12-1}"

def draw(mid, out, t0=None, t1=None):
    pm = pretty_midi.PrettyMIDI(mid)
    notes = sorted([n for i in pm.instruments for n in i.notes], key=lambda n: n.start)
    if t0 is not None:
        notes = [n for n in notes if n.end > t0 and n.start < t1]
        for n in notes:
            n.start = max(n.start, t0); n.end = min(n.end, t1)
    if not notes:
        print("NO NOTES"); return

    # skyline 旋律: 贪心选不重叠的、每次取开始时间最早的最高音
    mel = []
    i = 0
    while i < len(notes):
        # 同一时刻起音的取最高
        t = notes[i].start
        grp = [n for n in notes[i:] if n.start - t < 0.06]
        best = max(grp, key=lambda n: n.pitch)
        mel.append(best)
        # 跳过与 best 重叠的音符
        j = i
        while j < len(notes) and notes[j].start < best.end - 0.03:
            j += 1
        i = j

    t0s = min(n.start for n in mel)
    t1s = max(n.end for n in mel)
    dur = t1s - t0s
    pmin = min(n.pitch for n in mel) - 1
    pmax = max(n.pitch for n in mel) + 1
    W = 2400; ROWH = 64; TOP = 40
    H = TOP + (pmax - pmin + 1) * 22
    img = Image.new("RGB", (W, H), (252, 252, 250))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arialbd.ttf", 15)
        fonts = ImageFont.truetype("arial.ttf", 12)
    except Exception:
        font = fonts = ImageFont.load_default()
    def X(t): return (t - t0s) / dur * (W - 80) + 60
    def Y(p): return TOP + (pmax - p) * 22 + 11
    for p in range(pmin, pmax + 1):
        if p % 12 == 0:
            d.line([60, Y(p), W - 10, Y(p)], fill=(210, 210, 205))
            d.text((6, Y(p) - 8), name(p), fill=(150, 150, 150), font=fonts)
    for t in range(0, int(dur) + 1):
        x = X(t0s + t)
        d.line([x, TOP - 10, x, H - 8], fill=(228, 228, 224) if t % 5 else (170, 170, 166))
        if t % 5 == 0:
            d.text((x + 2, 6), f"{t}s", fill=(100, 100, 100), font=fonts)
    for k, n in enumerate(mel):
        x0, x1 = X(n.start), X(n.end)
        if x1 - x0 < 26: x1 = x0 + 26
        y = Y(n.pitch)
        d.rounded_rectangle([x0, y - 12, x1, y + 12], 4, fill=(190, 40, 60) if k % 2 else (220, 90, 40), outline=(120, 20, 30))
        d.text((x0 + 3, y - 9), name(n.pitch), fill=(255, 255, 255), font=font)
    img.save(out)
    print(f"MEL_NOTES={len(mel)} range[{name(pmin)},{name(pmax)}] -> {out}")

if __name__ == "__main__":
    a = sys.argv
    draw(a[1], a[2], float(a[3]) if len(a) > 3 else None, float(a[4]) if len(a) > 4 else None)
