# -*- coding: utf-8 -*-
"""名字级修复工具: 直接改 tools/injected_songs.json 里的游戏内显示名。
适用于 AI 校对报告里"同音频不同名"的裁决后修正(名字改对, 视频不动)。
改完自动备份, 之后需要执行:
    python tools/olivia_patch.py build && python tools/olivia_patch.py install
用法:
  python rename_entries.py --show CODE [CODE ...]   # 查看当前名字
  python rename_entries.py --set CODE "新名字"       # 改一条
  python rename_entries.py --swap A B               # 互换两条名字(经典互换错配)
"""
import os, sys, json, shutil, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "injected_songs.json")

def load():
    return json.load(open(JSON_PATH, encoding="utf-8"))

def save(d):
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = JSON_PATH + f".bak_{ts}"
    shutil.copy2(JSON_PATH, bak)
    json.dump(d, open(JSON_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"[备份] {bak}")
    print(f"[写入] {JSON_PATH} ({len(d)} 条)")
    print("[下一步] python tools/olivia_patch.py build && python tools/olivia_patch.py install")

def find(d, code):
    for x in d:
        if x.get("nameKey", "").replace("Uploaded_", "") == code.upper():
            return x
    raise KeyError(f"injected_songs.json 中找不到 code={code}")

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return
    d = load()
    if a[0] == "--show":
        for c in a[1:]:
            e = find(d, c)
            print(f"{c}: {e['name']!r}")
    elif a[0] == "--set":
        code, name = a[1], a[2]
        e = find(d, code)
        old = e["name"]
        e["name"] = name
        if e.get("title"):
            e["title"] = name
        print(f"[改名] {code}: {old!r} -> {name!r}")
        save(d)
    elif a[0] == "--swap":
        ca, cb = a[1], a[2]
        ea, eb = find(d, ca), find(d, cb)
        ea["name"], eb["name"] = eb["name"], ea["name"]
        print(f"[互换] {ca} <-> {cb} 名字已对调")
        save(d)
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
