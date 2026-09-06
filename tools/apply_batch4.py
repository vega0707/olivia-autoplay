# -*- coding: utf-8 -*-
"""应用批4核验结论到 manual_verdicts.json (何者/再度和你裁决 + 春日影/红莲华同名异曲)"""
import json, io

P = "ai_fast/manual_verdicts.json"
v = json.load(open(P, encoding="utf-8"))
items = v["items"]
by_code = {it["code"]: it for it in items}

def upsert(code, name, verdict, evidence, detail):
    if code in by_code:
        it = by_code[code]
        it.update({"name": name, "verdict": verdict, "evidence": evidence, "detail": detail})
    else:
        it = {"code": code, "name": name, "verdict": verdict, "evidence": evidence, "detail": detail}
        items.append(it)
        by_code[code] = it

# 1. 何者/再度和你 4簇裁决
upsert("V89YNA", "何者 (崩铁)", "OK", "strong",
    "批4块级判别: 与 0UY0AT 音频完全相同(sim=1.000), 共享音频与 WTZP3L[何者#2] 块级同位互配"
    "(块0×块0@10半音=0.9671, 块9×块9@0=0.9529), 旋律同为 E大调家族(E5/G#5/A5/B5, G#5重复链), "
    "WTZP3L 为同家族低八度(E4/G#4/B4) → 共享音频真身=《何者》, 本条标签正确。")
upsert("0UY0AT", "何者（崩铁）·重复版", "FIXED", "strong",
    "原标签 再度和你（崩铁 昔涟 pv）, 经批4裁决为错标: 与 V89YNA[何者] 音频完全相同(sim=1.000), "
    "共享音频与 WTZP3L[何者#2] 块级同位互配(0.9671/0.9529)证实为《何者》; "
    "与 CX7A4W[再度和你#2] 的 0.9525 块峰系三全音(6半音)/纯五度(11半音)双峰纹理伪峰且无同位块, "
    "全窗仅0.846随机带, 已排除。已改名: 何者（崩铁）·重复版。")
upsert("WTZP3L", "何者 (崩铁)", "OK", "strong",
    "批4转录核验: 旋律 E4/G#4/B4, 与共享音频(V89YNA≡0UY0AT)块级同位互配(0.9671/0.9529), "
    "同属 E大调家族低八度形态; 与 CX7A4W[再度和你#2] 全窗0.877+块级散乱(≤0.947)确认为不同曲。"
    "作为《何者》独立副本标签成立。")
upsert("CX7A4W", "再度和你 (崩铁 昔涟 pv)", "CHECK", "medium",
    "批4转录核验: 旋律为黑键 G#m/B 大调家族(G#4/C#5/D#5), 与何者共享音频明确不同(全窗0.846/块级伪峰排除)。"
    "4簇裁决后本条成为库内唯一《再度和你》标签且无内部矛盾, 但库内无其他《再度和你》副本可作独立参照, 暂定成立。")

# 2. 春日影 同名异曲对
upsert("WTCHR3", "春日影（《MYGO！！！》）", "SUSPECT", "strong",
    "同名异曲(批4): 与 7TVB8W[春日影#2] 全窗仅0.7367(不可能同曲, 同名不同音频至少其一错标)。"
    "本条旋律为全黑键集合(C#/D#/F#/G#/A#)稀疏抒情ballad, 14-18s长音D#5+A#3低音铺底。"
    "全库近邻搜索最高仅0.8899(风格带), 真身不在库内, 需人工听辨。")
upsert("7TVB8W", "春日影（《MYGO！！！》）", "SUSPECT", "strong",
    "同名异曲(批4): 与 WTCHR3[春日影#1] 全窗仅0.7367, 至少其一错标。"
    "本条 C#6 开场长音+A#5连锁, 但混入 E5/E3/A4 白键音, 调性家族与 WTCHR3 不同。"
    "全库近邻最高0.8913(风格带), 真身不在库内, 需人工听辨。")

# 3. 红莲华 同名异曲对
upsert("9EOAEQ", "红莲华（《鬼灭》）", "SUSPECT", "strong",
    "同名异曲(批4): 与 97RNJ6[红莲华#2] 全窗0.8183(低于随机带下限0.83), 至少其一错标。"
    "本条旋律黑键为主(G#5/A#5/C#6/D#5)+少量B5/E5。全库近邻最高0.8838(风格带), "
    "真身不在库内, 需人工听辨。")
upsert("97RNJ6", "红莲华（《鬼灭》）", "CHECK", "medium",
    "同名异曲(批4): 与 9EOAEQ[红莲华#1] 全窗0.8183, 至少其一错标。"
    "本条旋律为 E大调音集(B5/E6/E5/G#5/C#5/D#5/B4), 与《红莲华》原曲调性(C#小调/E大调音集)相容, "
    "是两份中更可能正确的一份。全库近邻最高0.9141(仍为风格带)。暂定成立, 待人工复核。")

# 4. copy_groups 更新
groups = v["copy_groups"]
for g in groups:
    if g.get("song") == "红莲华 (《鬼灭之刃》)":
        g["verdict"] = "SUSPECT"
        g["evidence"] = "strong"
        g["detail"] = ("批4复核: 全窗相似度实测0.8183(低于随机带下限), 且两份转录调性家族不同"
                       "(9EOAEQ黑键为主 vs 97RNJ6 E大调音集) → 同名异曲, 至少其一错标, 需人工听辨。")
# 新增 何者 三副本组 与 春日影 异曲组
groups.append({
    "song": "何者 (崩铁)",
    "codes": ["V89YNA", "WTZP3L", "0UY0AT"],
    "verdict": "FIXED",
    "evidence": "strong",
    "detail": ("V89YNA≡0UY0AT 音频完全相同(1.000); 块级同位互配+旋律家族比对证实共享音频与 WTZP3L 同为《何者》"
               "(E大调家族, 0UY0AT 错标再度和你已改名)。再度和你 仅剩 CX7A4W 一份。")
})
groups.append({
    "song": "春日影 (《MYGO!!!》)",
    "codes": ["WTCHR3", "7TVB8W"],
    "verdict": "SUSPECT",
    "evidence": "strong",
    "detail": ("同名异曲: 全窗0.7367不可能同曲, 两份调性家族不同(全黑键 vs 混白键), "
               "全库近邻均风格带 → 至少其一错标且真身不在库内, 需人工听辨。")
})

json.dump(v, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
from collections import Counter
print("items:", len(items), Counter(it["verdict"] for it in items))
print("groups:", len(groups))
