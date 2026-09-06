# -*- coding: utf-8 -*-
"""
Olivia 自动连播 —— 前端补丁工具

用法:
    python olivia_patch.py status    查看当前状态（是否已打补丁 / 应用是否运行）
    python olivia_patch.py build     从原始备份重新构建出 feapp.dat.patched
    python olivia_patch.py install   把补丁包装进游戏目录（自动备份原文件）
    python olivia_patch.py restore   回滚到原始 feapp.dat

设计要点:
    * build 永远基于 backup/feapp.dat.orig，保证可重复执行、不会叠加注入
    * install 前自动备份当前现场文件，restore 可完整还原
    * 安装前检测 Olivia 进程，运行中则拒绝写入（文件被占用会写坏）
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

APP_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\BSide Olivia Lin Test\0.0.9.627"
TARGET = os.path.join(APP_DIR, "resources", "feapp.dat")
HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "backup")
ORIG = os.path.join(BACKUP, "feapp.dat.orig")
PATCHED = os.path.join(BACKUP, "feapp.dat.patched")
INJECT_JS = os.path.join(HERE, "..", "src", "autoplay.js")
ASSET_NAME = "assets/autoplay.js"
SCRIPT_TAG = b'<script src="./assets/autoplay.js"></script>'
EXE_NAME = "Olivia.exe"
# 本地歌曲缓存目录（官方 songStoragePath 对应位置）
CACHE_VIDEO_DIR = os.path.join(
    os.environ.get("APPDATA", ""), "miHoYo", "Olivia-steam", "cache", "studio", "video")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def app_running():
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}"],
                             capture_output=True, text=True, encoding="gbk",
                             errors="ignore").stdout
        return EXE_NAME.lower() in out.lower()
    except Exception:
        return False


def ensure_orig():
    """确保原始备份存在"""
    if not os.path.exists(ORIG):
        if not os.path.exists(TARGET):
            print(f"[错误] 既没有原始备份，也找不到目标文件：{TARGET}")
            sys.exit(1)
        os.makedirs(BACKUP, exist_ok=True)
        shutil.copy2(TARGET, ORIG)
        print(f"[备份] 已保存原始包 -> {ORIG}")
    return ORIG


def cmd_status():
    print("=" * 64)
    print("Olivia 自动连播 · 状态")
    print("=" * 64)
    print(f"目标文件 : {TARGET}")
    print(f"存在     : {os.path.exists(TARGET)}")
    if os.path.exists(TARGET):
        print(f"SHA256   : {sha256(TARGET)}")
        if os.path.exists(ORIG):
            same = sha256(TARGET) == sha256(ORIG)
            print(f"与原始一致: {same}  -> 当前为【{'原始版' if same else '已打补丁'}】")
    print(f"原始备份 : {ORIG} ({'存在' if os.path.exists(ORIG) else '缺失'})")
    print(f"补丁包   : {PATCHED} ({'存在' if os.path.exists(PATCHED) else '未构建'})")
    print(f"Olivia 运行中: {app_running()}")
    print("=" * 64)


def collect_cache_dirs():
    """枚举本地歌曲缓存目录名，作为离线曲库清单注入脚本"""
    dirs = []
    try:
        if os.path.isdir(CACHE_VIDEO_DIR):
            for name in sorted(os.listdir(CACHE_VIDEO_DIR)):
                full = os.path.join(CACHE_VIDEO_DIR, name)
                if os.path.isdir(full) and name not in (".", ".."):
                    dirs.append(name)
    except Exception as e:
        print(f"[警告] 枚举缓存目录失败: {e}")
    return dirs


def cmd_build():
    ensure_orig()
    if not os.path.exists(INJECT_JS):
        print(f"[错误] 找不到注入脚本：{INJECT_JS}")
        sys.exit(1)

    js = open(INJECT_JS, "rb").read()

    # 注入本地缓存目录清单（离线曲库数据源）
    cache_dirs = collect_cache_dirs()
    manifest = ("window.__OLIVIA_CACHE_DIRS=" +
                repr(cache_dirs).replace("'", '"') + ";").encode()
    js = js.replace(b"/*__CACHE_DIRS__*/", manifest, 1)
    print(f"[构建] 本地缓存曲目: {len(cache_dirs)} 首（{CACHE_VIDEO_DIR}）")

    # 注入玩家上传曲目元数据（Uploaded_<CODE>，与缓存目录一一对应；
    # autoplay.js 的 ensureOfflineData() 会把它们合并进离线曲库）
    injected_json = os.path.join(HERE, "injected_songs.json")
    if os.path.exists(injected_json):
        with open(injected_json, encoding="utf-8") as f:
            songs = json.load(f)
        payload = ("window.__OLIVIA_INJECTED_SONGS=" +
                   json.dumps(songs, ensure_ascii=False,
                              separators=(",", ":")) + ";").encode()
        if b"/*__INJECTED_SONGS__*/" in js:
            js = js.replace(b"/*__INJECTED_SONGS__*/", payload, 1)
            print(f"[构建] 玩家上传曲目元数据: {len(songs)} 首")
        else:
            print("[警告] 注入脚本中找不到 /*__INJECTED_SONGS__*/ 占位符")
    else:
        print("[警告] 未找到 injected_songs.json，跳过玩家上传曲注入")

    print(f"[构建] 基础包: {ORIG}")
    print(f"[构建] 注入脚本: {INJECT_JS} ({len(js):,} 字节)")

    injected = False
    replaced = False
    # 功能开关翻转（官方在构建期硬编码关闭的前端功能）
    #   Ss: 主界面「定制演奏」（MIDI 上传）卡片   —— !o(w)&&o(Ss) 才渲染
    #   N3: 信箱「写信」按钮                      —— hide-write: p||!N3
    #   另：渲染条件里的 !o(w)&& 一并移除（w 为跨模块隐藏条件，离线
    #       环境下恒真导致卡片仍不显示）
    BUNDLE_FLAGS = [
        (b"!o(w)&&o(Ss)", b"o(Ss)"),
        (b"Ss=!1", b"Ss=!0"),
        (b"N3=!1", b"N3=!0"),
    ]
    with zipfile.ZipFile(ORIG) as zin, \
            zipfile.ZipFile(PATCHED, "w", zipfile.ZIP_DEFLATED) as zout:
        # 1) 按原顺序搬运所有条目
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "index.html":
                if SCRIPT_TAG in data:
                    print("  · index.html 已含注入标记，跳过重复注入")
                else:
                    marker = b"</body>"
                    if marker in data:
                        data = data.replace(marker, SCRIPT_TAG + b"\n  " + marker, 1)
                        injected = True
                        print("  · index.html 已插入脚本引用")
                    else:
                        data += b"\n" + SCRIPT_TAG + b"\n"
                        injected = True
                        print("  · index.html 未找到 </body>，已追加到末尾")
            elif info.filename.startswith("assets/") and \
                    info.filename.endswith(".js"):
                # 前端 bundle：翻转功能开关（断言恰好出现一次再替换）
                for old, new in BUNDLE_FLAGS:
                    n = data.count(old)
                    if n == 1:
                        data = data.replace(old, new, 1)
                        print(f"  · {info.filename}: {old.decode()} -> {new.decode()} ✓")
                    elif n > 1:
                        print(f"  · {info.filename}: {old.decode()} 出现 {n} 次，跳过（需人工确认）")
            zout.writestr(info, data)

        # 2) 写入注入脚本（如已存在则覆盖）
        replaced = ASSET_NAME in zin.namelist()
        zinfo = zipfile.ZipInfo(ASSET_NAME)
        zinfo.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zinfo, js)

    print(f"[构建] 新增/覆盖资源: {ASSET_NAME} ({'覆盖' if replaced else '新增'})")
    print(f"[构建] 完成 -> {PATCHED} ({os.path.getsize(PATCHED):,} 字节)")
    return injected


def cmd_install():
    ensure_orig()
    if not os.path.exists(PATCHED):
        print("[提示] 尚未构建，先执行 build …")
        cmd_build()

    if app_running():
        print(f"[中止] {EXE_NAME} 正在运行，文件被占用。请先关闭 Olivia 再安装。")
        sys.exit(2)

    # 安装前备份当前现场
    stamp_backup = os.path.join(BACKUP, "feapp.dat.before_install")
    shutil.copy2(TARGET, stamp_backup)
    print(f"[备份] 安装前现场 -> {stamp_backup}")

    shutil.copy2(PATCHED, TARGET)
    print(f"[安装] 已写入 {TARGET}")
    print(f"[安装] 新 SHA256: {sha256(TARGET)}")
    print("\n现在可以启动 Olivia，右下角应出现「♪ 自动连播」面板。")


def cmd_restore():
    if not os.path.exists(ORIG):
        print("[错误] 没有原始备份，无法回滚")
        sys.exit(1)
    if app_running():
        print(f"[中止] {EXE_NAME} 正在运行，请先关闭 Olivia 再回滚。")
        sys.exit(2)
    shutil.copy2(ORIG, TARGET)
    print(f"[回滚] 已还原 {TARGET}")
    print(f"[回滚] SHA256: {sha256(TARGET)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1].lower()
    {"status": cmd_status, "build": cmd_build,
     "install": cmd_install, "restore": cmd_restore}.get(
        cmd, lambda: print(__doc__))()
