# -*- coding: utf-8 -*-
"""缓存级错配修正执行器: 在 D:\\Olivia_Lin_Songs\\Uploaded_<CODE> 目录间直接交换视频。
不依赖 D:\\download, 不触碰游戏目录; 交换前自动备份到 correction_backup\\<时间戳>\\。
用法:
  python apply_corrections.py --plan corrections.json   # 按计划执行
  python apply_corrections.py --swap CODE_A CODE_B      # 快捷互换两曲视频
corrections.json 格式: [{"op":"swap","a":"XXXXXX","b":"YYYYYY"}, ...]
"""
import os, sys, json, shutil, datetime

CACHE = r"D:\Olivia_Lin_Songs"
VIDEO = "Uploaded_{code}_TOD1200_NI_L.mp4"

def video_path(code):
    return os.path.join(CACHE, f"Uploaded_{code}", VIDEO.format(code=code))

def precheck(code):
    p = video_path(code)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"{code} 视频不存在: {p}")
    return p

def swap(a, b, backup_dir):
    pa, pb = precheck(a), precheck(b)
    for p in (pa, pb):                       # 先备份
        dst = os.path.join(backup_dir, os.path.basename(p))
        if not os.path.exists(dst):
            shutil.copy2(p, dst)
    tmp = pa + ".swaptmp"
    os.rename(pa, tmp)
    try:
        os.rename(pb, pa)
        os.rename(tmp, pb)
    except OSError:                          # 回滚
        if os.path.exists(tmp):
            if not os.path.exists(pa):
                os.rename(tmp, pa)
        raise
    print(f"[SWAP] {a} <-> {b} 完成 (已备份至 {backup_dir})")

def main():
    args = sys.argv[1:]
    ops = []
    if "--swap" in args:
        i = args.index("--swap")
        a, b = args[i + 1], args[i + 2]
        ops = [{"op": "swap", "a": a.upper(), "b": b.upper()}]
    elif "--plan" in args:
        plan = args[args.index("--plan") + 1]
        ops = json.load(open(plan, encoding="utf-8"))
    else:
        print(__doc__)
        return
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(CACHE, "correction_backup", ts)
    os.makedirs(backup_dir, exist_ok=True)
    log = []
    for op in ops:
        if op.get("op") == "swap":
            try:
                swap(op["a"], op["b"], backup_dir)
                log.append({"op": op, "result": "OK"})
            except Exception as e:
                print(f"[FAIL] {op}: {e}")
                log.append({"op": op, "result": f"FAIL: {e}"})
    lp = os.path.join(backup_dir, "swap_log.json")
    json.dump(log, open(lp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("log ->", lp)
    print("提示: 如需游戏内生效, 还需重建 injected_songs.json 并 olivia_patch.py build (缓存与清单同步)。")

if __name__ == "__main__":
    main()
