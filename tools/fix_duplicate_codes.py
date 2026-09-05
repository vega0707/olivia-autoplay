# -*- coding: utf-8 -*-
"""修复 6 个重复分享码目录：
1) 用第一条记录的源重写目录（与 injected_songs.json 对齐）
2) manifest 去重为 526 条（保留第一条），写回
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "uploaded_songs_manifest.json")
CACHE_ROOT = r"D:\Olivia_Lin_Songs"
TOD = [1200, 1730, 2000]

man = json.load(open(MANIFEST, encoding="utf-8"))
seen = {}
for m in man:
    seen.setdefault(m["code"], m)

fixed = 0
for code, item in seen.items():
    recs = [m for m in man if m["code"] == code]
    if len(recs) < 2:
        continue
    nk = "Uploaded_" + code
    srcs = [v for v in (item.get("videos") or []) if os.path.exists(v)]
    srcs_desc = sorted(srcs, key=os.path.getsize, reverse=True)
    plan = ([srcs_desc[0], srcs_desc[1], srcs_desc[2]] if len(srcs_desc) >= 3
            else [srcs_desc[0], srcs_desc[-1], srcs_desc[-1]])
    os.makedirs(os.path.join(CACHE_ROOT, nk), exist_ok=True)
    for i, src in enumerate(plan):
        dst = os.path.join(CACHE_ROOT, nk, "%s_TOD%d_NI_L.mp4" % (nk, TOD[i]))
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
            continue
        tmp = dst + ".tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    fixed += 1
    print("[重写] %s <- 第一条源 %s" % (nk, item["src"][-40:]))

# manifest 去重（保留第一条出现顺序）
out = []
seen2 = set()
for m in man:
    if m["code"] in seen2:
        continue
    seen2.add(m["code"])
    out.append(m)
json.dump(out, open(MANIFEST, "w", encoding="utf-8"), ensure_ascii=False)
print("manifest 去重: %d -> %d 条" % (len(man), len(out)))
print("重写目录数:", fixed)
