# -*- coding: utf-8 -*-
"""把 ai_fast/ 的单首卷帘图拼成大图(每张 5列×6行=30首), 供 AI 批量读谱。
用法: python montage_fast.py [per_sheet]
输出: ai_fast/montage_NN.png
"""
import os, sys, glob, json
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ai_fast")

def main():
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    cols = 5
    rows = (per + cols - 1) // cols
    CW, CH = 660, 330           # 每格
    files = sorted(glob.glob(os.path.join(OUT, "*_spec.png")))
    try:
        font = ImageFont.truetype("msyh.ttc", 16)
    except Exception:
        font = ImageFont.load_default()
    nsheet = 0
    for s in range(0, len(files), per):
        batch = files[s: s + per]
        W, H = cols * CW, ((len(batch) + cols - 1) // cols) * CH
        sheet = Image.new("RGB", (W, H), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        for i, f in enumerate(batch):
            r, c = divmod(i, cols)
            x0, y0 = c * CW, r * CH
            im = Image.open(f)
            im.thumbnail((CW - 8, CH - 8))
            sheet.paste(im, (x0 + 4, y0 + 4))
            d.rectangle([x0, y0, x0 + CW - 1, y0 + CH - 1], outline=(180, 180, 180))
        nsheet += 1
        p = os.path.join(OUT, f"montage_{nsheet:02d}.png")
        sheet.save(p)
        print(p, len(batch))
    print(f"sheets={nsheet} total={len(files)}")

if __name__ == "__main__":
    main()
