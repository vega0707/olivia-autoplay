# -*- coding: utf-8 -*-
"""快速识别: mp4 → 30s 音频 → numpy STFT 半音网格热图 (无神经网络, ~3-5s/首)。
用法: python fast_iden.py <video.mp4> <out_prefix>
输出: <out_prefix>_spec.png (热图, 供 AI 读图认曲) + <out_prefix>.json (统计)
"""
import os, sys, json, subprocess, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

SR = 16000
WIN = 4096
HOP = 512          # 32ms
DUR = 30.0
NOTE_NAMES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

def extract_wav(video, wav_path, duration=DUR):
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    r = subprocess.run([ff, "-y", "-ss", "0", "-t", str(duration), "-i", video,
                        "-ac", "1", "-ar", str(SR), "-vn", wav_path],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(wav_path):
        raise RuntimeError("ffmpeg: " + r.stderr[-200:])

def chroma_spectrogram(y):
    """返回 (pitch_grid[88], frames) 幅度矩阵 + 帧时间轴。"""
    win = np.hanning(WIN).astype(np.float32)
    n = (len(y) - WIN) // HOP
    freqs = np.fft.rfftfreq(WIN, 1 / SR)          # 3.9Hz per bin
    # midi 音级 → 频率 bin 范围
    p_lo = np.zeros(88, dtype=int); p_hi = np.zeros(88, dtype=int)
    for p in range(21, 109):
        f1 = 440.0 * 2 ** ((p - 0.5 - 69) / 12)
        f2 = 440.0 * 2 ** ((p + 0.5 - 69) / 12)
        p_lo[p - 21] = int(np.searchsorted(freqs, f1))
        p_hi[p - 21] = int(np.searchsorted(freqs, f2))
    grid = np.zeros((88, n), dtype=np.float32)
    for i in range(n):
        seg = y[i * HOP: i * HOP + WIN] * win
        mag = np.abs(np.fft.rfft(seg))
        grid[:, i] = [mag[p_lo[k]:max(p_lo[k] + 1, p_hi[k])].max() for k in range(88)]
    times = np.arange(n) * HOP / SR
    return grid, times

def spec_png(grid, times, out_png, title=""):
    g = grid / (grid.max() + 1e-9)
    n = g.shape[1]
    # 时间池化到 ~320 列 (每列 3 帧 ≈ 96ms), 取 max 保留音头
    ncols = 320
    if n > ncols:
        pad = (-n) % ncols
        gp = np.pad(g, ((0, 0), (0, pad)))
        g = gp.reshape(88, -1, ncols).max(axis=1)
        n = ncols
    # 每帧 top3 音级离散显示: 1.0 / 0.6 / 0.35, 其余为 0 —— 直接估计的钢琴卷帘
    order = np.argsort(g, axis=0)[::-1]            # 每列降序的行索引
    disp = np.zeros_like(g)
    cols = np.arange(n)
    disp[order[0], cols] = 1.0
    disp[order[1], cols] = 0.6
    disp[order[2], cols] = 0.35
    rows = np.where(disp.max(axis=1) > 0)[0]
    if len(rows) == 0: rows = np.array([30, 70])
    pmin, pmax = max(0, rows.min() - 1), min(87, rows.max() + 1)
    if pmax - pmin > 44:                            # 跨度限制(能量重心窗口)
        act = disp.max(axis=1)
        center = int(np.average(np.arange(88), weights=act + 1e-9))
        pmin, pmax = max(0, center - 23), min(87, center + 21)
    sub = disp[pmin:pmax + 1][::-1]                 # 高音在上
    H0, W0 = sub.shape
    SCALE_Y, SCALE_X = 7, 2
    v = (sub * 255).astype(np.uint8)
    v_up = np.repeat(np.repeat(v, SCALE_Y, axis=0), SCALE_X, axis=1)
    # 蓝→青→白渐变色映射
    img = np.zeros((*v_up.shape, 3), dtype=np.uint8)
    img[..., 2] = v_up
    img[..., 1] = (v_up.astype(np.float32) ** 1.6 * 255).astype(np.uint8)
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)
    try: font = ImageFont.truetype("arialbd.ttf", 14)
    except Exception: font = ImageFont.load_default()
    for p in range(pmin, pmax + 1):
        if p % 12 == 0:
            yy = (pmax - p) * SCALE_Y
            d.line([0, yy, im.width, yy], fill=(90, 90, 110))
            d.text((4, yy + 1), f"C{p//12-1}", fill=(230, 230, 40), font=font)
    for t in range(0, int(times[-1]) + 1, 5):
        xx = int(t / times[-1] * im.width)
        d.line([xx, 0, xx, im.height], fill=(90, 90, 110))
        d.text((xx + 2, 2), f"{t}s", fill=(255, 160, 60), font=font)
    if title:
        bar = Image.new("RGB", (im.width, 30), (245, 245, 240))
        bd = ImageDraw.Draw(bar)
        try: ft = ImageFont.truetype("msyh.ttc", 18)
        except Exception: ft = font
        bd.text((6, 4), title, fill=(20, 20, 20), font=ft)
        full = Image.new("RGB", (im.width, im.height + 30), (245, 245, 240))
        full.paste(bar, (0, 0)); full.paste(im, (0, 30))
        full.save(out_png)
    else:
        im.save(out_png)
    return pmin, pmax

def main():
    video, prefix = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else ""
    tmp = tempfile.mkdtemp(prefix="fid_")
    wav = os.path.join(tmp, "a.wav")
    extract_wav(video, wav)
    import soundfile as sf
    y, sr = sf.read(wav, dtype="float32")
    if y.ndim > 1: y = y.mean(axis=1)
    grid, times = chroma_spectrogram(y)
    pmin, pmax = spec_png(grid, times, prefix + "_spec.png", title)
    g = grid / (grid.max() + 1e-9)
    stats = {"dur": float(times[-1]), "range": f"{NOTE_NAMES[(pmin+21)%12]}{((pmin+21)//12)-1}-{NOTE_NAMES[(pmax+21)%12]}{((pmax+21)//12)-1}",
             "active_pitches": int((g.max(axis=1) > 0.25).sum())}
    json.dump(stats, open(prefix + ".json", "w", encoding="utf-8"))
    print(f"OK {stats}")

if __name__ == "__main__":
    main()
