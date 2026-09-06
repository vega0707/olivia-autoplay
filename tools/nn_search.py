# -*- coding: utf-8 -*-
"""全库最近邻检索: 对指定 code, 用细指纹(12x96, 转调不变)在全部526首中找最相似曲目。
首次运行计算并缓存全部特征到 ai_fast/feats_526.npz (约5-8分钟); 之后秒级。
用法: python nn_search.py CODE1 [CODE2 ...]   (每目标输出 top-15)
"""
import os, sys, json, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fine_cluster import feat_of

OUT = os.path.join(HERE, "ai_fast")
FEATS = os.path.join(OUT, "feats_526.npz")
CACHE = r"D:\Olivia_Lin_Songs"

def build_feats():
    man = json.load(open(os.path.join(HERE, "uploaded_songs_manifest.json"), encoding="utf-8"))
    feats, meta = [], []
    t0 = time.time()
    for i, m in enumerate(man):
        f, rms = feat_of(m["code"])
        if f is None:
            f = np.zeros(1152, dtype=np.float32)
        feats.append(f)
        meta.append({"code": m["code"], "name": m["name"]})
        if (i + 1) % 50 == 0:
            print(f"feat {i+1}/{len(man)} {time.time()-t0:.0f}s", flush=True)
    F = np.array(feats, dtype=np.float32)
    np.savez_compressed(FEATS, F=F,
                        codes=np.array([m["code"] for m in meta]),
                        names=np.array([m["name"] for m in meta]))
    print(f"saved {FEATS} {F.shape} {time.time()-t0:.0f}s", flush=True)
    return F, [m["code"] for m in meta], [m["name"] for m in meta]

def load_feats():
    if os.path.isfile(FEATS):
        z = np.load(FEATS, allow_pickle=False)
        codes = [c for c in z["codes"]]
        names = [n for n in z["names"]]
        return z["F"], codes, names
    return build_feats()

def top_matches(F, codes, names, target_code, k=15):
    ti = codes.index(target_code) if target_code in codes else -1
    fv = feat_of(target_code)[0]
    if fv is None:
        print(f"{target_code}: 无音频特征", flush=True)
        return
    n = fv.shape[0] // 96
    sims = np.zeros(len(codes), dtype=np.float32)
    for kk in range(n):
        sims = np.maximum(sims, np.roll(F, kk * 96, axis=1) @ fv)
    order = np.argsort(-sims)
    print(f"\n=== {target_code} 最近邻 top-{k} ===", flush=True)
    shown = 0
    for idx in order:
        if codes[idx] == target_code:
            continue
        # 零向量(缺音频)跳过
        if float(np.linalg.norm(F[idx])) < 0.01:
            continue
        print(f"{sims[idx]:.4f}  {codes[idx]}  {names[idx][:40]}", flush=True)
        shown += 1
        if shown >= k:
            break

def main():
    F, codes, names = load_feats()
    print(f"feats: {F.shape}", flush=True)
    for tc in sys.argv[1:]:
        top_matches(F, codes, names, tc.upper())

if __name__ == "__main__":
    main()
