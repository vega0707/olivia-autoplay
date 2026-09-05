# -*- coding: utf-8 -*-
"""批量写入前的状态核实：
1) 两个缓存根的目录数、Uploaded_YICUTE 归属、差异集合
2) manifest / injected_songs 结构抽样
3) 源视频总大小估算
"""
import json
import os

APPDATA_ROOT = os.path.join(os.environ.get("APPDATA", ""),
                            "miHoYo", "Olivia-steam", "cache", "studio", "video")
D_ROOT = r"D:\Olivia_Lin_Songs"
HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "uploaded_songs_manifest.json")
INJECTED = os.path.join(HERE, "injected_songs.json")


def list_dirs(root):
    if not os.path.isdir(root):
        return None
    return set(d for d in os.listdir(root)
               if os.path.isdir(os.path.join(root, d)))


a = list_dirs(APPDATA_ROOT)
d = list_dirs(D_ROOT)
print("APPDATA 根:", APPDATA_ROOT)
print("  存在:", a is not None, " 目录数:", len(a) if a else "-")
print("D 盘根  :", D_ROOT)
print("  存在:", d is not None, " 目录数:", len(d) if d else "-")

if a and d:
    print("  APPDATA 含 Uploaded_YICUTE:", "Uploaded_YICUTE" in a)
    print("  D盘     含 Uploaded_YICUTE:", "Uploaded_YICUTE" in d)
    only_a = sorted(a - d)
    only_d = sorted(d - a)
    print("  仅在 APPDATA (%d):" % len(only_a), only_a[:6])
    print("  仅在 D盘     (%d):" % len(only_d), only_d[:6])
    same = a & d
    print("  交集:", len(same))
    # 抽查交集内某个目录是否内容一致（同盘镜像 or 独立拷贝）
    sample = sorted(same)[0]
    fa = os.path.join(APPDATA_ROOT, sample)
    fd = os.path.join(D_ROOT, sample)
    na = set(os.listdir(fa)) if os.path.isdir(fa) else set()
    nd = set(os.listdir(fd)) if os.path.isdir(fd) else set()
    print("  抽样目录:", sample, " APPDATA文件数:", len(na), " D盘文件数:", len(nd),
          " 文件名一致:", na == nd)

print()
print("=== manifest 结构 ===")
man = json.load(open(MANIFEST, encoding="utf-8"))
print("条目数:", len(man))
it = man[0]
print("字段:", sorted(it.keys()))
print("样例 code/name/src:", it.get("code"), "/", it.get("name"), "/", it.get("src"))
print("样例 videos:")
for v in it.get("videos", []):
    print("   ", v, "%.1f MB" % (os.path.getsize(v) / 2**20) if os.path.exists(v) else "[缺失]")

print()
print("=== injected_songs 结构 ===")
inj = json.load(open(INJECTED, encoding="utf-8"))
print("条目数:", len(inj))
it0 = inj[0]
print("字段:", sorted(it0.keys()))
print("样例:", json.dumps({k: it0[k] for k in list(it0)[:8]}, ensure_ascii=False)[:300])

print()
print("=== 源视频总大小估算（前 20 条实测 + 外推） ===")
total = 0
n_files = 0
missing = 0
checked = 0
for i, e in enumerate(man):
    for v in e.get("videos", []):
        if os.path.exists(v):
            total += os.path.getsize(v)
            n_files += 1
        else:
            missing += 1
    checked += 1
    if checked >= 20:
        break
per_song = total / max(checked, 1)
est_all = per_song * len(man)
print("前 %d 首实测: %.1f MB/首, 文件 %d 个, 缺失 %d 个" % (checked, per_song / 2**20, n_files, missing))
print("532 首外推总量: %.1f GB" % (est_all / 2**30))
import shutil
for drive in ("C:", "D:"):
    if os.path.exists(drive + "\\"):
        free = shutil.disk_usage(drive + "\\").free
        print("  %s 剩余 %.1f GB" % (drive, free / 2**30))
