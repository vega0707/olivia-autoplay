# -*- coding: utf-8 -*-
"""全量审计：526 个 Uploaded_* 缓存目录逐一核对
1) 每目录恰好 3 个 .mp4（无 .tmp 残留）
2) 每个文件大小与源文件一致
3) 输出坏目录清单
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "uploaded_songs_manifest.json")
CACHE_ROOT = r"D:\Olivia_Lin_Songs"
TOD = [1200, 1730, 2000]

man = json.load(open(MANIFEST, encoding="utf-8"))
seen = set()
bad = []
ok_cnt = 0
tmp_leftover = []

for item in man:
    code = item["code"]
    if code in seen:
        continue
    seen.add(code)
    nk = "Uploaded_" + code
    d = os.path.join(CACHE_ROOT, nk)
    if not os.path.isdir(d):
        bad.append((nk, "目录不存在"))
        continue
    files = os.listdir(d)
    tmps = [f for f in files if f.endswith(".tmp")]
    if tmps:
        tmp_leftover.append((nk, tmps))
    mp4s = [f for f in files if f.endswith(".mp4")]
    if len(mp4s) != 3:
        bad.append((nk, "mp4 数量=%d" % len(mp4s)))
        continue
    srcs = [v for v in (item.get("videos") or []) if os.path.exists(v)]
    srcs_desc = sorted(srcs, key=os.path.getsize, reverse=True)
    # 期望：TOD1200=最大源；TOD1730/TOD2000=最小源（2源曲）或第2/3大源
    exp = [os.path.getsize(srcs_desc[0])]
    if len(srcs_desc) >= 3:
        exp += [os.path.getsize(srcs_desc[1]), os.path.getsize(srcs_desc[2])]
    else:
        exp += [os.path.getsize(srcs_desc[-1])] * 2
    got = []
    for t in TOD:
        f = os.path.join(d, "%s_TOD%d_NI_L.mp4" % (nk, t))
        got.append(os.path.getsize(f) if os.path.exists(f) else -1)
    if got != exp:
        bad.append((nk, "大小不匹配 got=%s exp=%s" % (got, exp)))
        continue
    ok_cnt += 1

print("唯一上传曲: %d" % len(seen))
print("审计通过  : %d" % ok_cnt)
print("异常目录  : %d" % len(bad))
for nk, why in bad[:20]:
    print("   [异常]", nk, "->", why)
print(".tmp 残留 : %d" % len(tmp_leftover))
for nk, t in tmp_leftover[:10]:
    print("   [残留]", nk, t)
if not bad and not tmp_leftover:
    print(">>> 全部 526 目录完整性审计通过")
