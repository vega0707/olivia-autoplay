# -*- coding: utf-8 -*-
"""
Olivia webplayer 观测探针 —— 给 webplayer.dat 注入诊断脚本

用法:
    python olivia_webplayer_patch.py status
    python olivia_webplayer_patch.py build     # 从 webplayer.dat.orig 重建探针包
    python olivia_webplayer_patch.py install   # 写入游戏目录（自动备份）
    python olivia_webplayer_patch.py restore   # 回滚

探针内容（assets/wp-probe.js，先于主 bundle 执行）:
    1. hook console.log —— 捕获 [PlaybackView] onPlayerControlCmd（native 下发的
       完整 cmd，含 url！与 notifyPlayerEvent）
    2. 轮询挂 video 元素事件（canplaythrough/error/stalled/playing/...）
    全部经 ToyPianistClient.invoke('eventTrack') 转发到主日志，actionName=wpProbe。
"""
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile

APP_DIR = os.environ.get(
    "OLIVIA_APP_DIR",
    r"C:\Program Files (x86)\Steam\steamapps\common\BSide Olivia Lin Test\0.0.9.627")
TARGET = os.path.join(APP_DIR, "resources", "webplayer.dat")
HERE = os.path.dirname(os.path.abspath(__file__))
BACKUP = os.path.join(HERE, "backup")
ORIG = os.path.join(BACKUP, "webplayer.dat.orig")
PATCHED = os.path.join(BACKUP, "webplayer.dat.patched")
PROBE_JS = os.path.join(HERE, "src", "wp_probe.js")
ASSET_NAME = "assets/wp-probe.js"
SCRIPT_TAG = b'<script src="./assets/wp-probe.js"></script>'
EXE_NAME = "Olivia.exe"

PROBE_SRC = r"""(function () {
    'use strict';
    // ---- 数据外传：notifyPlayerEvent 的 event 字段会原样出现在主日志
    //      的 "Unknown player event notified:<name>" 行里 → 用事件名携带
    //      base64url 数据块。
    function b64u(s) {
        try {
            return btoa(unescape(encodeURIComponent(s)))
                .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        } catch (e) { return 'ERR'; }
    }
    var outq = [];          // 待发消息队列
    function pushMsg(tag, s) {
        if (outq.length > 60) return;   // 防爆队列
        s = String(s == null ? '' : s).slice(0, 700);
        outq.push(tag + '|' + s);
    }
    var seq = 0;
    setInterval(function () {
        if (!outq.length) return;
        var msg = outq.shift();
        try {
            var t = window.ToyPianistClient;
            if (t && typeof t.invoke === 'function') {
                var chunk = (seq++) + '#' + msg;
                // event 名 = P + b64(chunk)，最长 ~1KB 分片
                var name = 'P' + b64u(chunk).slice(0, 900);
                t.invoke('notifyPlayerEvent', { event: name });
                if (chunk.length > 900) {   // 分片续传
                    var rest = chunk.slice(900);
                    while (rest.length) {
                        t.invoke('notifyPlayerEvent',
                            { event: 'C' + b64u(rest.slice(0, 900)) });
                        rest = rest.slice(900);
                    }
                }
            }
        } catch (e) { }
        try { document.title = 'WP|' + msg.slice(0, 140); } catch (e) { }
    }, 300);

    // ---- console.log 捕获：onPlayerControlCmd（native 下发的完整 cmd！）
    try {
        var origLog = console.log.bind(console);
        console.log = function () {
            try {
                var s = '';
                for (var i = 0; i < arguments.length; i++) {
                    var a = arguments[i];
                    if (typeof a === 'object' && a !== null) {
                        try { s += JSON.stringify(a) + ' '; }
                        catch (e) { s += '[obj] '; }
                    } else { s += String(a) + ' '; }
                }
                if (s.indexOf('onPlayerControlCmd') >= 0) {
                    pushMsg('CMD', s);              // 最高价值
                } else if (s.indexOf('onEnded') >= 0) {
                    pushMsg('ENDED', s);
                }
            } catch (e) { }
            return origLog.apply(null, arguments);
        };
    } catch (e) { }

    // ---- video 元素事件（src 变化 / 加载失败 / 起播）
    var hooked = [];
    function hookVideo(v, id) {
        for (var k = 0; k < hooked.length; k++) if (hooked[k] === v) return;
        hooked.push(v);
        ['loadstart', 'loadedmetadata', 'canplaythrough', 'playing', 'pause',
         'ended', 'error', 'emptied', 'abort'].forEach(function (evName) {
            v.addEventListener(evName, function () {
                var info = { e: evName, id: id,
                    src: String(v.src || '').slice(0, 300) };
                if (evName === 'error' && v.error) info.code = v.error.code;
                if (v.duration && isFinite(v.duration)) info.dur = v.duration;
                pushMsg('VID', JSON.stringify(info));
            }, true);
        });
        pushMsg('HOOK', JSON.stringify({ id: id,
            src: String(v.src || '').slice(0, 300) }));
    }
    setInterval(function () {
        try {
            var vs = document.querySelectorAll('video');
            for (var i = 0; i < vs.length; i++) hookVideo(vs[i], i);
        } catch (e) { }
    }, 500);
    pushMsg('BOOT', String(location.href).slice(0, 300));
})();
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def app_running():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}"],
            capture_output=True, text=True, encoding="gbk",
            errors="ignore").stdout
        return EXE_NAME.lower() in out.lower()
    except Exception:
        return False


def ensure_orig():
    if not os.path.exists(ORIG):
        if not os.path.exists(TARGET):
            print(f"[错误] 找不到目标文件：{TARGET}")
            sys.exit(1)
        os.makedirs(BACKUP, exist_ok=True)
        shutil.copy2(TARGET, ORIG)
        print(f"[备份] 原始 webplayer.dat -> {ORIG}")
    return ORIG


def cmd_status():
    print(f"目标: {TARGET}  存在: {os.path.exists(TARGET)}")
    if os.path.exists(TARGET) and os.path.exists(ORIG):
        print(f"与原始一致: {sha256(TARGET) == sha256(ORIG)}")
    print(f"原始备份: {os.path.exists(ORIG)}  探针包: {os.path.exists(PATCHED)}")
    print(f"Olivia 运行中: {app_running()}")


def cmd_build():
    ensure_orig()
    with zipfile.ZipFile(ORIG) as zin, \
            zipfile.ZipFile(PATCHED, "w", zipfile.ZIP_DEFLATED) as zout:
        injected = False
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "index.html":
                if SCRIPT_TAG in data:
                    print("  · index.html 已含探针标记，跳过")
                else:
                    anchor = b'<script type="module"'
                    if anchor in data:
                        data = data.replace(
                            anchor, SCRIPT_TAG + b'\n  ' + anchor, 1)
                        injected = True
                        print("  · index.html 已在 module 脚本前插入探针")
                    else:
                        data += b"\n" + SCRIPT_TAG + b"\n"
                        injected = True
                        print("  · index.html 末尾追加探针")
            zout.writestr(info, data)
        zinfo = zipfile.ZipInfo(ASSET_NAME)
        zinfo.compress_type = zipfile.ZIP_DEFLATED
        zout.writestr(zinfo, PROBE_SRC.encode("utf-8"))
    print(f"[构建] 完成 -> {PATCHED} ({os.path.getsize(PATCHED):,} 字节)")


def cmd_install():
    ensure_orig()
    if not os.path.exists(PATCHED):
        cmd_build()
    if app_running():
        print("[中止] Olivia 正在运行，请先关闭。")
        sys.exit(2)
    shutil.copy2(TARGET, os.path.join(BACKUP, "webplayer.dat.before_install"))
    shutil.copy2(PATCHED, TARGET)
    print(f"[安装] 已写入 {TARGET}")
    print(f"[安装] SHA256: {sha256(TARGET)}")


def cmd_restore():
    if app_running():
        print("[中止] Olivia 正在运行。")
        sys.exit(2)
    shutil.copy2(ORIG, TARGET)
    print(f"[回滚] 已还原 {TARGET}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    {"status": cmd_status, "build": cmd_build, "install": cmd_install,
     "restore": cmd_restore}.get(sys.argv[1].lower(), cmd_status)()
