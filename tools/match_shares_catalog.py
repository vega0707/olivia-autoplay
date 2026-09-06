# -*- coding: utf-8 -*-
"""把 2midi4lin 作品集目录(shares_catalog.json)与 uploaded_songs_manifest.json 按 code 匹配，
输出三类结果：consistent(名字一致) / review(码命中但名字需人工判断) / unmatched(未命中)。"""
import json, os, re, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
CAT = os.path.join(HERE, "shares_catalog.json")
MAN = os.path.join(HERE, "uploaded_songs_manifest.json")
OUT = os.path.join(HERE, "shares_match_report.json")

STRIP_WORDS = [
    "钢琴演奏", "钢琴版", "钢琴独奏", "钢琴谱", "钢琴曲", "钢琴改编", "钢琴",
    "pia版", "piano", "cover", "ver", "version", "hi-res", "mqms2", "sq",
    "伴奏版", "伴奏", "纯享版", "完整版", "live", "演奏", "翻自", "附谱", "附指法",
    "效果差", "超好听", "进来听歌", "百万级装备试听", "为你展现奇迹", "高品质",
]
PUNCT = re.compile(r"[\s\-—_–·・,:：;；!！?？~～'\"“”‘’`()\[\]【】《》〈〉「」『』（）().。/\\|＊*＋+&#@…⋯]+")

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = PUNCT.sub("", s)
    for w in STRIP_WORDS:
        s = s.replace(w.lower(), "")
    return s.strip()

def has_cjk(s: str) -> bool:
    return any(unicodedata.name(ch, "").startswith("CJK") or 0x4E00 <= ord(ch) <= 0x9FFF for ch in s)

def name_related(manifest_name: str, title: str) -> bool:
    """manifest 官方名是否出现在作品集标题里(双向, 归一化后)。"""
    n1, n2 = norm(manifest_name), norm(title)
    if not n1 or not n2:
        return False
    if n1 in n2 or n2 in n1:
        return True
    # 短名(>=3 字符)直接子串在 title 原文里
    raw = re.sub(r"\s+", "", manifest_name or "")
    if len(raw) >= 3 and raw in re.sub(r"\s+", "", title or ""):
        return True
    return False

def main():
    cat = json.load(open(CAT, encoding="utf-8"))["shares"]
    man = json.load(open(MAN, encoding="utf-8"))
    cat_by_code = {}
    for x in cat:
        cat_by_code.setdefault(x["share_code"].strip().upper(), x)

    consistent, review, unmatched = [], [], []
    for m in man:
        code = m["code"].strip().upper()
        hit = cat_by_code.get(code)
        if not hit:
            unmatched.append({"code": code, "name": m["name"]})
        elif name_related(m["name"], hit["title"]):
            consistent.append({"code": code, "name": m["name"], "title": hit["title"]})
        else:
            review.append({"code": code, "name": m["name"], "title": hit["title"]})

    rep = {"total_manifest": len(man), "total_catalog": len(cat),
           "consistent": consistent, "review": review, "unmatched_count": len(unmatched)}
    json.dump(rep, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print(f"名单 {len(man)} | 作品集 {len(cat)}")
    print(f"码命中且名字一致: {len(consistent)}")
    print(f"码命中但名字需人工判断: {len(review)}")
    print(f"未命中作品集: {len(unmatched)}  (作品集仅覆盖 {len(cat)} 条, 上线晚于多数上传)")
    print("\n===== REVIEW 明细 (名单名 vs 作品集标题) =====")
    for r in review:
        print(f"  {r['code']}  名单[{r['name']}]  作品集[{r['title']}]")
    print("\n===== CONSISTENT 明细 =====")
    for r in consistent:
        print(f"  {r['code']}  {r['name']}  <=  {r['title']}")

if __name__ == "__main__":
    main()
