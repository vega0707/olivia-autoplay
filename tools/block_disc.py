# -*- coding: utf-8 -*-
"""分段判别: 特征为 (12 chroma x 96 时间列) 摊平的 1152 维向量。
按时间切成 6 块(每块16列≈5s, 192维), 穷举块对 x 12 转调移位, 取块内余弦最大值。
整窗相似度会被不同乐段稀释, 块级最大值更能捕捉'有一段相同'的证据。
用法: python block_disc.py CODE1 CODE2 [CODE3 ...]
"""
import os, sys, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np
from fine_cluster import feat_of

NB = 12  # 12 个时间块, 每块 8 列≈2.5s

def blocks(code):
    v, _ = feat_of(code)
    m = v.reshape(12, 96)
    cols = 96 // NB  # 16
    out = []
    for i in range(NB):
        b = m[:, i * cols:(i + 1) * cols].flatten()
        n = np.linalg.norm(b)
        if n > 1e-9:
            out.append(b / n)
    return out

def main():
    codes = [c.upper() for c in sys.argv[1:]]
    bl = {c: blocks(c) for c in codes}
    for a, b in itertools.combinations(codes, 2):
        pairs = []
        for i, x in enumerate(bl[a]):
            for j, y in enumerate(bl[b]):
                for k in range(12):
                    s = float(x @ np.roll(y.reshape(12, -1), k, axis=0).flatten())
                    pairs.append((s, i, j, k))
        pairs.sort(reverse=True)
        top = pairs[:4]
        line = " | ".join(f"块{i}×块{j}@{k}半音={s:.4f}" for s, i, j, k in top)
        print(f"{a} ~ {b}: TOP {line}")
    # 自检: 同一首歌块对自身应=1.0
    c0 = codes[0]
    s0, _, _, _ = max(
        (float(x @ y), i, j, 0) for i, x in enumerate(bl[c0]) for j, y in enumerate(bl[c0])
    )
    print(f"自检 {c0}~{c0}: {s0:.4f} (应≈1.0)")

if __name__ == "__main__":
    main()
