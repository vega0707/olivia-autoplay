# -*- coding: utf-8 -*-
"""批量把 532 首玩家上传曲写入本地视频缓存（D:\\Olivia_Lin_Songs）。

依据已验证的成功案例（Uploaded_YICUTE，probe_tod.py 产物）：
    目录名 = nameKey = "Uploaded_" + 分享码
    文件名 = <nameKey>_TOD1200_NI_L.mp4 / _TOD1730_NI_L.mp4 / _TOD2000_NI_L.mp4
    源视频按大小降序依次对应 TOD1200 / TOD1730 / TOD2000

特性:
    * 断点续跑：目标目录内 3 个文件齐全且大小与源一致 -> 跳过
    * 半截文件防御：先写 .tmp 再改名
    * 源缺失不中断，最后汇总
"""
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MANIFEST = os.path.join(HERE, "uploaded_songs_manifest.json")
CACHE_ROOT = r"D:\Olivia_Lin_Songs"
TOD_NAMES = ["TOD1200", "TOD1730", "TOD2000"]


def expected_files(name_key, srcs_desc):
    """返回 [(dst_path, src_path, size), ...] 按 TOD 顺序"""
    out = []
    for i, src in enumerate(srcs_desc[:3]):
        dst = os.path.join(CACHE_ROOT, name_key,
                           "%s_%s_NI_L.mp4" % (name_key, TOD_NAMES[i]))
        out.append((dst, src, os.path.getsize(src)))
    return out


def main():
    man = json.load(open(MANIFEST, encoding="utf-8"))
    print("manifest 条目: %d" % len(man))

    ok = skipped = missing = failed = 0
    total_bytes = 0
    failed_list, missing_list = [], []
    t0 = time.time()

    for idx, item in enumerate(man, 1):
        code = item["code"]
        name_key = "Uploaded_" + code
        videos = item.get("videos") or []
        srcs = [v for v in videos if os.path.exists(v)]

        if len(srcs) < 3:
            missing += 1
            missing_list.append((code, item.get("name"),
                                 "%d/3 个源存在" % len(srcs)))
            continue

        srcs_desc = sorted(srcs, key=os.path.getsize, reverse=True)
        dst_dir = os.path.join(CACHE_ROOT, name_key)

        # 完整性检查：3 个目标文件都存在且大小一致 -> 跳过
        complete = True
        for dst, src, size in expected_files(name_key, srcs_desc):
            if not (os.path.exists(dst) and os.path.getsize(dst) == size):
                complete = False
                break
        if complete:
            skipped += 1
            continue

        try:
            os.makedirs(dst_dir, exist_ok=True)
            for dst, src, size in expected_files(name_key, srcs_desc):
                if os.path.exists(dst) and os.path.getsize(dst) == size:
                    continue
                tmp = dst + ".tmp"
                shutil.copyfile(src, tmp)
                os.replace(tmp, dst)
                total_bytes += size
            ok += 1
        except Exception as e:
            failed += 1
            failed_list.append((code, item.get("name"), repr(e)))
            continue

        if idx % 10 == 0 or idx == len(man):
            el = time.time() - t0
            spd = total_bytes / 2**20 / max(el, 0.1)
            print("[%d/%d] 完成=%d 跳过=%d 缺源=%d 失败=%d 平均 %.1f MB/s (已用时 %.0fs)"
                  % (idx, len(man), ok, skipped, missing, failed,
                     spd if total_bytes else 0, el), flush=True)

    print()
    print("=" * 60)
    print("汇总: 新建 %d, 已存在跳过 %d, 源缺失 %d, 失败 %d (共 %d)"
          % (ok, skipped, missing, failed, len(man)))
    print("写入数据量: %.1f GB, 耗时 %.1f 分钟"
          % (total_bytes / 2**30, (time.time() - t0) / 60))
    if missing_list:
        print("源缺失清单:")
        for c, n, why in missing_list:
            print("   %s %s (%s)" % (c, n, why))
    if failed_list:
        print("失败清单:")
        for c, n, e in failed_list:
            print("   %s %s -> %s" % (c, n, e))
    print("=" * 60)
    return 0 if (failed == 0 and missing == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
