# -*- coding: utf-8 -*-
"""汇总所有证据生成 AI 校对报告 (HTML)。
证据来源:
  1. manual_verdicts.json  — 神经网络转录硬证据 + 名曲/副本人工读谱
  2. clusters.json         — 音频指纹聚类(转调不变), 名字冲突的高相似对 = 错配实锤候选
  3. uploaded_songs_manifest.json — 526 全量
输出: ai_fast/AI_report.html (ASCII名, 避免预览服务中文路径兼容问题)
"""
import os, sys, json, html, datetime, base64, io

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ai_fast")
_INLINE = {}
def thumb_uri(code):
    """标记行的快谱缩略图 → data URI (预览环境无兄弟文件也能看证据)。"""
    if code in _INLINE:
        return _INLINE[code]
    uri = ""
    p = os.path.join(OUT, f"{code}_spec.png")
    if os.path.isfile(p):
        try:
            uri = "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()
        except Exception:
            uri = ""
    _INLINE[code] = uri
    return uri

def load(p, default=None):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default

def main():
    man = load(os.path.join(HERE, "uploaded_songs_manifest.json"), [])
    code2name = {m["code"]: m["name"] for m in man}
    verdicts = load(os.path.join(OUT, "manual_verdicts.json"), {"items": [], "copy_groups": []})
    fp = load(os.path.join(OUT, "fine_pairs.json"), None)
    clusters = fp["pairs"] if isinstance(fp, dict) and "pairs" in fp else \
               (fp if isinstance(fp, list) else load(os.path.join(OUT, "clusters.json"), []))

    # --- 聚类分析: 细指纹(12x96)仅采信 sim>=0.99 ---
    # 基准: 同音频=1.000, 随机对=0.83~0.87, 0.96~0.985=低音区等风格相似假阳性带(不采信)
    TRUST = 0.99
    conflict_pairs, dup_ok_pairs = [], []
    for c in clusters:
        if c["sim"] < TRUST:
            continue
        a, b = c["a"], c["b"]
        if a["name"] != b["name"]:
            conflict_pairs.append(c)
        else:
            dup_ok_pairs.append(c)

    # --- 汇总每首状态 ---
    status = {}   # code -> (level, note)
    def setst(code, level, note):
        old = status.get(code)
        if old is None or LEVEL_ORDER[level] > LEVEL_ORDER[old[0]]:
            status[code] = (level, note)

    LEVEL_ORDER = {"MISMATCH": 5, "FIXED": 4, "SUSPECT": 3, "CHECK": 2, "OK": 1}
    for it in verdicts["items"]:
        setst(it["code"], it["verdict"], it["detail"])
    for g in verdicts["copy_groups"]:
        for c in g["codes"]:
            setst(c, g["verdict"], f"[副本组:{g['song']}] {g['detail']}")

    # 聚类名字冲突 → 两侧升级为 SUSPECT; 但人工已判 OK/FIXED(如同曲双版本、已改名)的不降级
    manual_keep = {it["code"] for it in verdicts["items"] if it["verdict"] in ("OK", "FIXED")}
    for c in conflict_pairs:
        for side in ("a", "b"):
            other = "b" if side == "a" else "a"
            code = c[side]["code"]
            if code in manual_keep:
                continue
            note = (f"聚类 sim={c['sim']} 与 [{c[other]['name']}] 音频结构相同但名单名不同 "
                    f"→ 二者之一错配(同音频, 应做名字级修正而非换视频)")
            setst(code, "SUSPECT", note)
    # 同名高相似且无其他标记 → 副本互证 OK
    for c in dup_ok_pairs:
        if c["a"]["code"] not in status:
            setst(c["a"]["code"], "OK", f"聚类 sim={c['sim']} 与同名副本 {c['b']['code']} 结构一致, 互证通过")
        if c["b"]["code"] not in status:
            setst(c["b"]["code"], "OK", f"聚类 sim={c['sim']} 与同名副本 {c['a']['code']} 结构一致, 互证通过")

    n_ok = sum(1 for v in status.values() if v[0] == "OK")
    n_mm = sum(1 for v in status.values() if v[0] == "MISMATCH")
    n_fx = sum(1 for v in status.values() if v[0] == "FIXED")
    n_sp = sum(1 for v in status.values() if v[0] == "SUSPECT")
    n_ck = sum(1 for v in status.values() if v[0] == "CHECK")
    n_un = len(man) - len(status)

    def badge(lv):
        return {"MISMATCH": '<span class="b b-mm">错配实锤</span>',
                "FIXED":    '<span class="b b-fx">已修正✓</span>',
                "SUSPECT":  '<span class="b b-sp">错配嫌疑</span>',
                "CHECK":    '<span class="b b-ck">待定</span>',
                "OK":       '<span class="b b-ok">已验证正确</span>'}[lv]

    def row(code):
        name = code2name.get(code, "?")
        st = status.get(code)
        if st:
            lv, note = st
            note_html = html.escape(note)
        else:
            lv, note_html = None, "—"
        b = badge(lv) if lv else '<span class="b b-un">未覆盖</span>'
        spec = f'<a href="{code}_spec.png">谱</a>'
        img = ""
        if lv in ("MISMATCH", "FIXED", "SUSPECT", "CHECK"):
            u = thumb_uri(code)
            if u:
                img = f'<a href="{code}_spec.png"><img src="{u}" style="max-width:420px;width:100%;border:1px solid #ddd;border-radius:4px;display:block;margin-top:4px" alt="{code}"></a>'
        return (f'<tr><td class="mono">{code}</td><td>{html.escape(name)}</td>'
                f'<td>{b}</td><td class="note">{note_html}{img}</td><td>{spec}</td></tr>')

    # 排序: 实锤 > 已修正 > 嫌疑 > 待定 > 已验证 > 未覆盖, 组内按code
    def sortkey(code):
        lv = status.get(code, (None,))[0]
        order = {"MISMATCH": 0, "FIXED": 1, "SUSPECT": 2, "CHECK": 3, "OK": 4}.get(lv, 5)
        return (order, code)
    ordered = sorted([m["code"] for m in man], key=sortkey)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    conflict_html = "".join(
        f'<tr><td class="mono">{c["a"]["code"]}</td><td>{html.escape(c["a"]["name"])}</td>'
        f'<td class="mono">{c["b"]["code"]}</td><td>{html.escape(c["b"]["name"])}</td>'
        f'<td>{c["sim"]}</td></tr>'
        for c in conflict_pairs[:60])

    page = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>AI 校对报告 · 526 注入歌曲</title><style>
body{{font-family:"Microsoft YaHei",sans-serif;margin:0;background:#f5f6f8;color:#222}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:32px;border-left:4px solid #4a7dbe;padding-left:10px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap;margin:16px 0}}
.card{{background:#fff;border-radius:10px;padding:14px 20px;box-shadow:0 1px 4px rgba(0,0,0,.08);text-align:center}}
.card .num{{font-size:26px;font-weight:700}}
.card .lab{{font-size:12px;color:#666}}
.b{{padding:2px 10px;border-radius:10px;font-size:12px;white-space:nowrap}}
.b-mm{{background:#d93025;color:#fff}} .b-sp{{background:#e8710a;color:#fff}}
.b-ck{{background:#f9ab00;color:#222}} .b-ok{{background:#188038;color:#fff}}
.b-fx{{background:#1a73e8;color:#fff}} .b-un{{background:#dadce0;color:#555}}
table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px}}
td,th{{border:1px solid #e0e0e0;padding:6px 10px;text-align:left;vertical-align:top}}
th{{background:#eef2f7;position:sticky;top:0}}
.mono{{font-family:Consolas,monospace;font-weight:600}}
.note{{color:#555;font-size:12px;max-width:520px}}
a{{color:#1a73e8;text-decoration:none}}
.meta{{color:#888;font-size:12px}}
tr:hover{{background:#f8f9fb}}
</style></head><body><div class="wrap">
<h1>AI 校对报告 — 526 首注入歌曲 名称↔视频核验</h1>
<div class="meta">生成时间 {now} · 方法: AMT-APC 神经网络转录(硬证据) + 音频指纹聚类(转调不变) + 多副本交叉互验 + 名曲谱面对照 · 点"谱"查看该曲钢琴卷帘快谱</div>

<div class="cards">
<div class="card"><div class="num" style="color:#d93025">{n_mm}</div><div class="lab">错配实锤</div></div>
<div class="card"><div class="num" style="color:#1a73e8">{n_fx}</div><div class="lab">已修正</div></div>
<div class="card"><div class="num" style="color:#e8710a">{n_sp}</div><div class="lab">错配嫌疑</div></div>
<div class="card"><div class="num" style="color:#f9ab00">{n_ck}</div><div class="lab">待定复核</div></div>
<div class="card"><div class="num" style="color:#188038">{n_ok}</div><div class="lab">已验证正确</div></div>
<div class="card"><div class="num" style="color:#888">{n_un}</div><div class="lab">未覆盖(AI无法判定)</div></div>
</div>

<h2>① 聚类发现: 音频相同但名单名冲突的对 (互换型错配候选)</h2>
<p class="meta">两曲音频结构高度相似(转调不变指纹)却挂不同歌名 → 视频极可能被互换, 二者对调即可修复。</p>
{f'<table><tr><th>曲A code</th><th>曲A 名单名</th><th>曲B code</th><th>曲B 名单名</th><th>相似度</th></tr>{conflict_html}</table>' if conflict_pairs else '<p>无名字冲突的高相似对。</p>'}

<h2>② 全量核验清单 (按严重度排序)</h2>
<table><tr><th>Code</th><th>名单名</th><th>状态</th><th>证据说明</th><th>快谱</th></tr>
{''.join(row(c) for c in ordered)}
</table>

<h2>③ 方法与局限</h2>
<ul style="font-size:13px;line-height:1.8">
<li><b>硬证据(转录)</b>: 用 2midi4lin 同款 AMT-APC 模型把音频转成 MIDI 再对照原曲调性/织体, 对高价值单曲执行。</li>
<li><b>细指纹聚类</b>: 全部 526 首提取 转调不变指纹(12半音×96时间段), 两两比对。基准: 同音频=1.000, 随机对=0.83~0.87; ≥0.99 采信, 0.96~0.985 为低音区等风格相似假阳性带(已逐对读谱排除)。</li>
<li><b>副本互验</b>: 同一首歌上传了多个副本(如 One last kiss ×4), 副本间谱面结构应一致; 字节级复核确认 9 对"同音频"均为同一 MIDI 的两次独立渲染(文件大小各异)。</li>
<li><b>修正方式</b>: 同音频不同名的错配无法靠换视频修复(两边是同一段音频), 采用名字级修正(rename_entries.py), 改名前自动备份 injected_songs.json。</li>
<li><b>局限</b>: 无副本且非名曲的孤立歌曲无法仅凭音频判定名字对错(无参考答案), 计入"未覆盖"。这些可继续用 proofread.html 人工听校。</li>
</ul>
</div></body></html>"""

    outp = os.path.join(OUT, "AI_report.html")
    open(outp, "w", encoding="utf-8").write(page)
    print("report ->", outp)
    print(f"stats: MISMATCH={n_mm} FIXED={n_fx} SUSPECT={n_sp} CHECK={n_ck} OK={n_ok} UNCOVERED={n_un} / total={len(man)}")
    print(f"cluster pairs: conflict={len(conflict_pairs)} dup_ok={len(dup_ok_pairs)} (total>{0.55}: {len(clusters)})")

if __name__ == "__main__":
    main()
