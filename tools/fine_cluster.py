# -*- coding: utf-8 -*-
"""全量细指纹两两比对 (12半音x96时间段, 转调不变)。
基准: 同音频=1.000, 随机对=0.83~0.87, 同曲异编/高似~0.97-0.99。
输出: ai_fast/fine_pairs.json (sim>=0.96 全部对) + 控制台摘要。
wav 缓存: ai_fast/wavcache/<CODE>.wav (重复运行秒级)。
"""
import os, sys, json, tempfile, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ai_fast")
CACHE = r"D:\Olivia_Lin_Songs"
WAVC = os.path.join(OUT, "wavcache")
os.makedirs(WAVC, exist_ok=True)
sys.path.insert(0, HERE)
from fast_iden import extract_wav, chroma_spectrogram
import soundfile as sf

def feat_of(code):
    wp = os.path.join(WAVC, f"{code}.wav")
    if not os.path.isfile(wp):
        vid = os.path.join(CACHE, f"Uploaded_{code}", f"Uploaded_{code}_TOD1200_NI_L.mp4")
        if not os.path.isfile(vid):
            return None, 0.0
        tmp = os.path.join(tempfile.mkdtemp(prefix="ff_"), "a.wav")
        extract_wav(vid, tmp)
        os.replace(tmp, wp)
    y, sr = sf.read(wp, dtype="float32")
    if y.ndim > 1: y = y.mean(axis=1)
    rms = float(np.sqrt(np.mean(y ** 2)) + 1e-9)
    grid, _ = chroma_spectrogram(y)
    g = grid / (grid.max() + 1e-9)
    c12 = np.zeros((12, g.shape[1]), dtype=np.float32)
    for p in range(21, 109):
        c12[p % 12] += g[p - 21] ** 0.5
    n = c12.shape[1]; pad = (-n) % 96
    seg = np.pad(c12, ((0, 0), (0, pad))).reshape(12, 96, -1).mean(axis=2)
    v = seg.flatten()
    return v / (np.linalg.norm(v) + 1e-9), rms

def main():
    man = json.load(open(os.path.join(HERE, "uploaded_songs_manifest.json"), encoding="utf-8"))
    t0 = time.time()
    feats, meta, lowrms = [], [], []
    for i, m in enumerate(man):
        code = m["code"]
        f, rms = feat_of(code)
        if f is None:
            continue
        if rms < 0.02:
            lowrms.append((code, m["name"], round(rms, 4)))
        feats.append(f); meta.append({"code": code, "name": m["name"]})
        if (i + 1) % 100 == 0:
            print(f"feat {i+1}/{len(man)} {time.time()-t0:.0f}s", flush=True)
    F = np.array(feats, dtype=np.float32)
    print("features:", F.shape, f"{time.time()-t0:.0f}s", flush=True)
    N = F.shape[1] // 96
    S = np.zeros((len(meta), len(meta)), dtype=np.float32)
    for k in range(N):
        S = np.maximum(S, np.roll(F, k * 96, axis=1) @ F.T)
    iu = np.triu_indices(len(meta), 1)
    sims = S[iu]
    mask = sims >= 0.96
    idx = np.where(mask)[0]
    pairs = []
    for t in idx:
        i, j = iu[0][t], iu[1][t]
        pairs.append({"sim": round(float(sims[t]), 4),
                      "a": meta[i], "b": meta[j]})
    pairs.sort(key=lambda x: -x["sim"])
    json.dump({"pairs": pairs, "lowrms": lowrms},
              open(os.path.join(OUT, "fine_pairs.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    conf = [p for p in pairs if p["a"]["name"] != p["b"]["name"]]
    print(f"\n>=0.96 对: {len(pairs)} (名字冲突: {len(conf)})  lowrms可疑: {len(lowrms)}")
    for p in pairs[:40]:
        flag = " <<< 名字不同" if p["a"]["name"] != p["b"]["name"] else ""
        print(f'{p["sim"]:.4f}  {p["a"]["code"]}[{p["a"]["name"][:20]}] ~ {p["b"]["code"]}[{p["b"]["name"][:20]}]{flag}')
    if lowrms:
        print("\n低能量可疑(疑似坏音频):")
        for c, n, r in lowrms:
            print(f"  {c} {r} {n[:30]}")

if __name__ == "__main__":
    main()
