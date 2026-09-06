# -*- coding: utf-8 -*-
"""音频指纹聚类找错配: 每首生成 转调不变的结构直方图特征, 两两余弦相似。
同一首歌的多个副本应聚在一起; 簇内名单名冲突 => 错配嫌疑。
用法: python cluster_audio.py
输出: ai_fast/clusters.json (高相似对 + 簇) + 控制台摘要
"""
import os, sys, json, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ai_fast")
CACHE = r"D:\Olivia_Lin_Songs"
sys.path.insert(0, HERE)
from fast_iden import extract_wav, chroma_spectrogram
import soundfile as sf

def fold12(grid):
    """88 音级 → 12 半音能量, 帧池化到 24 段, 转调循环移位由匹配阶段处理。"""
    g = grid / (grid.max() + 1e-9)
    c12 = np.zeros((12, g.shape[1]), dtype=np.float32)
    for p in range(21, 109):
        c12[p % 12] += g[p - 21] ** 0.5          # 幅度域平方根压动态
    # 时间池化到 24 段(每段均值)
    n = c12.shape[1]
    pad = (-n) % 24
    gp = np.pad(c12, ((0, 0), (0, pad)))
    seg = gp.reshape(12, 24, -1).mean(axis=2)     # 12 x 24
    v = seg.flatten()
    return v / (np.linalg.norm(v) + 1e-9)

def rot12(v):
    """12 半音循环移位版本 (特征是 12x24 展开, 移位以 24 为步长)。"""
    return [np.roll(v, k * 24) for k in range(12)]

def main():
    man = json.load(open(os.path.join(HERE, "uploaded_songs_manifest.json"), encoding="utf-8"))
    feats, meta = [], []
    for i, m in enumerate(man):
        code = m["code"]
        fjson = os.path.join(OUT, f"{code}.json")
        vid = os.path.join(CACHE, f"Uploaded_{code}", f"Uploaded_{code}_TOD1200_NI_L.mp4")
        if not os.path.isfile(vid):
            continue
        try:
            tmp = tempfile.mkdtemp(prefix="cl_")
            wav = os.path.join(tmp, "a.wav")
            extract_wav(vid, wav)
            y, sr = sf.read(wav, dtype="float32")
            if y.ndim > 1: y = y.mean(axis=1)
            grid, times = chroma_spectrogram(y)
            feats.append(fold12(grid))
            meta.append({"code": code, "name": m["name"]})
        except Exception as e:
            print("skip", code, type(e).__name__)
        if (i + 1) % 50 == 0:
            print(f"...{i+1}", flush=True)
    F = np.array(feats)                     # N x 288
    print("features:", F.shape)
    # 转调不变两两相似度
    N = len(meta)
    sims = []
    FR = [rot12(F[i]) for i in range(N)]    # 每首 12 个移位版本
    for i in range(N):
        for j in range(i + 1, N):
            s = max(float(FR[i][k] @ F[j]) for k in range(12))
            if s > 0.55:
                sims.append((s, meta[i]["code"], meta[i]["name"], meta[j]["code"], meta[j]["name"]))
    sims.sort(reverse=True)
    out = [{"sim": round(s, 3), "a": {"code": c1, "name": n1}, "b": {"code": c2, "name": n2}}
           for s, c1, n1, c2, n2 in sims]
    json.dump(out, open(os.path.join(OUT, "clusters.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print(f"\n高相似对(>0.55): {len(sims)}")
    for s, c1, n1, c2, n2 in sims[:40]:
        flag = "  <<< 名字不同!" if n1 != n2 else ""
        print(f"{s:.3f}  {c1}[{n1}]  ~  {c2}[{n2}]{flag}")

if __name__ == "__main__":
    main()
