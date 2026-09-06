# -*- coding: utf-8 -*-
"""全量批处理: 对每个 Uploaded_<CODE> 目录转录音频 → mid + 旋律图 + notes json。
断点续跑(已存在输出则跳过), 串行避免 CPU 竞争。
用法: python batch_transcribe.py [limit] [--redo CODE,CODE]
输出目录: ai_iden/  (mid/png/json + batch_log.txt)
"""
import os, sys, json, subprocess, time, tempfile, re

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ai_iden")
CACHE = r"D:\Olivia_Lin_Songs"
PY = sys.executable
DUR = "60"

def lang_of(n):
    if re.search(r"[\u3040-\u30ff]", n): return "ja"
    if re.search(r"[\uac00-\ud7af]", n): return "ko"
    if re.search(r"[\u4e00-\u9fff]", n): return "zh"
    return "other"

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, (r.stdout or "") + (r.stderr or "")

def main():
    os.makedirs(OUT, exist_ok=True)
    man = json.load(open(os.path.join(HERE, "uploaded_songs_manifest.json"), encoding="utf-8"))
    limit = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 10**9
    redo = set()
    if "--redo" in sys.argv:
        redo = set(sys.argv[sys.argv.index("--redo") + 1].split(","))
    langs = None
    if "--lang" in sys.argv:
        langs = set(sys.argv[sys.argv.index("--lang") + 1].split(","))
    log = open(os.path.join(OUT, "batch_log.txt"), "a", encoding="utf-8")
    done = 0
    t0 = time.time()
    for m in man:
        code = m["code"]
        if langs and lang_of(m["name"]) not in langs:
            continue
        if done >= limit:
            break
        mid = os.path.join(OUT, f"{code}.mid")
        png = os.path.join(OUT, f"{code}_mel.png")
        js  = os.path.join(OUT, f"{code}_notes.json")
        if os.path.isfile(mid) and os.path.isfile(png) and code not in redo:
            continue
        vid = os.path.join(CACHE, f"Uploaded_{code}", f"Uploaded_{code}_TOD1200_NI_L.mp4")
        if not os.path.isfile(vid):
            log.write(f"{code} NO_VIDEO\n"); log.flush(); continue
        t1 = time.time()
        rc, out = run([PY, os.path.join(HERE, "transcribe_video.py"), vid, os.path.join(OUT, code), DUR])
        if rc != 0 or not os.path.isfile(mid):
            log.write(f"{code} FAIL rc={rc} {out[-200:]}\n"); log.flush(); continue
        rc2, out2 = run([PY, os.path.join(HERE, "draw_melody.py"), mid, png])
        if rc2 != 0:
            log.write(f"{code} MELODY_FAIL {out2[-200:]}\n"); log.flush(); continue
        # 摘要 json (notes 统计)
        import pretty_midi
        pm = pretty_midi.PrettyMIDI(mid)
        notes = [{"p": n.pitch, "s": round(n.start, 2), "e": round(n.end, 2), "v": n.velocity}
                 for inst in pm.instruments for n in inst.notes]
        json.dump({"code": code, "name": m["name"], "lang": lang_of(m["name"]),
                   "n_notes": len(notes), "notes": notes},
                  open(js, "w", encoding="utf-8"), ensure_ascii=False)
        done += 1
        el = time.time() - t1
        log.write(f"{code} OK notes={len(notes)} {el:.0f}s total={(time.time()-t0)/60:.1f}m\n"); log.flush()
        print(f"{code} OK notes={len(notes)} {el:.0f}s")
    log.write(f"BATCH DONE done={done} {(time.time()-t0)/60:.1f}m\n"); log.flush()

if __name__ == "__main__":
    main()
