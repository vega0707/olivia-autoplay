# -*- coding: utf-8 -*-
"""为 12 首"源只有 2 个视频"的上传曲补齐缓存目录：
大源 -> TOD1200，小源 -> TOD1730，小源复用 -> TOD2000。
目录已有 3 个合格文件则跳过（幂等）。
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "uploaded_songs_manifest.json")
CACHE_ROOT = r"D:\Olivia_Lin_Songs"
TOD = [1200, 1730, 2000]

man = json.load(open(MANIFEST, encoding="utf-8"))
fixed = skipped = 0
for item in man:
    srcs = [v for v in (item.get("videos") or []) if os.path.exists(v)]
    if len(srcs) >= 3:
        continue  # 主批量脚本已处理
    if not srcs:
        print("[无源] %s %s" % (item["code"], item["name"]))
        continue
    nk = "Uploaded_" + item["code"]
    dst_dir = os.path.join(CACHE_ROOT, nk)
    srcs_desc = sorted(srcs, key=os.path.getsize, reverse=True)
    # TOD1200=大源, TOD1730=小源, TOD2000=小源复用
    plan = [srcs_desc[0], srcs_desc[-1], srcs_desc[-1]]
    os.makedirs(dst_dir, exist_ok=True)
    done = True
    for i, src in enumerate(plan):
        dst = os.path.join(dst_dir, "%s_TOD%d_NI_L.mp4" % (nk, TOD[i]))
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
            continue
        tmp = dst + ".tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        done = False
    if done:
        skipped += 1
        print("[跳过-已齐] %s %s" % (nk, item["name"]))
    else:
        fixed += 1
        print("[补齐] %s %s (%d 源 -> 3 文件)" % (nk, item["name"], len(srcs)))

print()
print("补齐 %d 首, 已完整 %d 首" % (fixed, skipped))

# 最终目录数核对
n = len([d for d in os.listdir(CACHE_ROOT)
         if os.path.isdir(os.path.join(CACHE_ROOT, d))])
print("D 盘缓存根目录总数: %d (期望 130 + 532 = 662)" % n)
