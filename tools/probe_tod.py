"""查看 videoByTodView 结构，并为 1 首歌建立试验目录"""
import json
import os
import shutil

DUMP = r"C:\Users\locea\WorkBuddy\2026-09-02-00-41-36\offline_catalog_dump.json"
MANIFEST = r"C:\Users\locea\WorkBuddy\2026-09-02-00-41-36\olivia_autoplay\uploaded_songs_manifest.json"
CACHE = r"D:\Olivia_Lin_Songs"

o = json.load(open(DUMP, encoding="utf-8"))
s = o["songs"][0]

print("=== videoByTodView 结构（样本曲 %s）===" % s["nameKey"])
vbt = s.get("videoByTodView") or []
print("条目数:", len(vbt))
for e in vbt:
    print("   ", json.dumps(e, ensure_ascii=False)[:170])

print()
print("=== 用 1 首上传曲做试验 ===")
man = json.load(open(MANIFEST, encoding="utf-8"))
item = man[0]
print("曲目:", item["code"], item["name"])
print("源目录:", item["src"])
print("源视频:")
for v in item["videos"]:
    print("   ", os.path.basename(v), "%.1f MB" % (os.path.getsize(v) / 2**20))

# nameKey 用 ASCII 安全标识（中文名放 name 字段显示）
name_key = "Uploaded_" + item["code"]
tod_names = ["TOD1200", "TOD1730", "TOD2000"]
dst_dir = os.path.join(CACHE, name_key)
os.makedirs(dst_dir, exist_ok=True)

# 源文件按大小降序 -> 依次对应 TOD1200/1730/2000
srcs = sorted(item["videos"], key=lambda p: os.path.getsize(p), reverse=True)
made = []
for i, src in enumerate(srcs[:3]):
    dst = os.path.join(dst_dir, "%s_%s_NI_L.mp4" % (name_key, tod_names[i]))
    shutil.copy2(src, dst)
    made.append(dst)
    print("   已复制 ->", os.path.basename(dst),
          "%.1f MB" % (os.path.getsize(dst) / 2**20))

print()
print("试验目录:", dst_dir)
print("内含文件:", [os.path.basename(x) for x in made])
