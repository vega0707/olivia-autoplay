# -*- coding: utf-8 -*-
"""计算指定 code 对的细指纹相似度 (复用 fine_cluster.feat_of, 含12个转调移位)。
用法: python pair_sim.py CODE1 CODE2 [CODE3 ...]  两两打印相似度矩阵。
"""
import os, sys, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from fine_cluster import feat_of

def main():
    codes = [c.upper() for c in sys.argv[1:]]
    feats = {}
    for c in codes:
        f, rms = feat_of(c)
        feats[c] = (f, rms)
        print(f"{c}: rms={rms:.4f} feat={'OK' if f is not None else 'MISSING'}")
    print()
    for a, b in itertools.combinations(codes, 2):
        fa, _ = feats[a]; fb, _ = feats[b]
        if fa is None or fb is None:
            print(f"{a} ~ {b}: N/A")
            continue
        n = fa.shape[0] // 96
        best = max(float(np.roll(fa, k * 96) @ fb) for k in range(n))
        print(f"{a} ~ {b}: sim={best:.4f}")

if __name__ == "__main__":
    main()
