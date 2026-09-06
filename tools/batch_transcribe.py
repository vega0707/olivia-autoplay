# -*- coding: utf-8 -*-
"""全量批处理(单进程内联版): 视频 → 音频 → apc.onnx 转录 → mid + 旋律图 + notes json。
断点续跑(已存在输出则跳过), 串行。默认全量 526 首。
用法: python batch_transcribe.py [--lang ja,ko,other] [--redo CODE,CODE] [--dur 60] [--limit N]
输出目录: ai_iden/  (mid/png/json + batch_log.txt)
"""
import os, sys, json, time, re, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ai_iden")
CACHE = r"D:\Olivia_Lin_Songs"
REPO = r"C:\Users\locea\AppData\Local\Temp\2m4l"   # 2midi4lin 源码 clone (转录代码)

def lang_of(n):
    if re.search(r"[\u3040-\u30ff]", n): return "ja"
    if re.search(r"[\uac00-\ud7af]", n): return "ko"
    if re.search(r"[\u4e00-\u9fff]", n): return "zh"
    return "other"

def main():
    os.makedirs(OUT, exist_ok=True)
    sys.path.insert(0, REPO)
    sys.path.insert(0, HERE)
    from src.transcription.onnx_transcriber import ONNXTranscriber
    import imageio_ffmpeg
    from transcribe_video import extract_audio, roll_png
    from draw_melody import draw as draw_mel
    import pretty_midi

    man = json.load(open(os.path.join(HERE, "uploaded_songs_manifest.json"), encoding="utf-8"))
    argv = sys.argv[1:]
    def opt(name, default=None):
        return argv[argv.index(name) + 1] if name in argv else default
    langs = opt("--lang"); langs = set(langs.split(",")) if langs else None
    redo = set(opt("--redo", "").split(",")) if "--redo" in argv else set()
    dur = float(opt("--dur", "60"))
    limit = int(opt("--limit", "10") ** 9 if False else opt("--limit", "999999999"))
    transcriber = ONNXTranscriber(style="level2", mode="apc")
    log = open(os.path.join(OUT, "batch_log.txt"), "a", encoding="utf-8")
    done = skip = 0
    t0 = time.time()
    for m in man:
        code = m["code"]
        if langs and lang_of(m["name"]) not in langs:
            continue
        mid = os.path.join(OUT, f"{code}.mid")
        png = os.path.join(OUT, f"{code}_mel.png")
        js  = os.path.join(OUT, f"{code}_notes.json")
        if os.path.isfile(mid) and os.path.isfile(png) and os.path.isfile(js) and code not in redo:
            skip += 1
            continue
        if done >= limit:
            break
        vid = os.path.join(CACHE, f"Uploaded_{code}", f"Uploaded_{code}_TOD1200_NI_L.mp4")
        if not os.path.isfile(vid):
            log.write(f"{code} NO_VIDEO\n"); log.flush(); continue
        t1 = time.time()
        try:
            tmpd = tempfile.mkdtemp(prefix="tr_")
            wav = os.path.join(tmpd, "a.wav")
            extract_audio(vid, wav, dur)
            transcriber.transcribe(wav, mid)
            draw_mel(mid, png)
            pm = pretty_midi.PrettyMIDI(mid)
            notes = [{"p": n.pitch, "s": round(n.start, 2), "e": round(n.end, 2), "v": n.velocity}
                     for inst in pm.instruments for n in inst.notes]
            json.dump({"code": code, "name": m["name"], "lang": lang_of(m["name"]),
                       "n_notes": len(notes), "notes": notes},
                      open(js, "w", encoding="utf-8"), ensure_ascii=False)
            el = time.time() - t1
            done += 1
            log.write(f"{code} OK notes={len(notes)} {el:.0f}s total={(time.time()-t0)/60:.1f}m\n"); log.flush()
            print(f"{code} OK notes={len(notes)} {el:.0f}s", flush=True)
        except Exception as e:
            log.write(f"{code} FAIL {type(e).__name__} {str(e)[-150:]}\n"); log.flush()
            print(f"{code} FAIL {type(e).__name__}", flush=True)
    log.write(f"BATCH DONE done={done} skip={skip} {(time.time()-t0)/60:.1f}m\n"); log.flush()
    print(f"ALL DONE done={done} skip={skip}", flush=True)

if __name__ == "__main__":
    main()
