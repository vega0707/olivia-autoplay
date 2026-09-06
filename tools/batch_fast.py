# -*- coding: utf-8 -*-
"""全量快速识别: 每首 30s 音频 → top3 半音卷帘图 (无神经网络 ~3.5s/首)。
断点续跑。用法: python batch_fast.py [limit]
输出: ai_fast/<CODE>_spec.png + ai_fast/<CODE>.json
"""
import os, sys, json, time, re, tempfile
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "ai_fast")
CACHE = r"D:\Olivia_Lin_Songs"
sys.path.insert(0, HERE)

def lang_of(n):
    if re.search(r"[\u3040-\u30ff]", n): return "ja"
    if re.search(r"[\uac00-\ud7af]", n): return "ko"
    if re.search(r"[\u4e00-\u9fff]", n): return "zh"
    return "other"

def main():
    os.makedirs(OUT, exist_ok=True)
    from fast_iden import extract_wav, chroma_spectrogram, spec_png, NOTE_NAMES
    import soundfile as sf
    man = json.load(open(os.path.join(HERE, "uploaded_songs_manifest.json"), encoding="utf-8"))
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10 ** 9
    log = open(os.path.join(OUT, "fast_log.txt"), "a", encoding="utf-8")
    done = 0; t0 = time.time()
    for m in man:
        code = m["code"]
        png = os.path.join(OUT, f"{code}_spec.png")
        js = os.path.join(OUT, f"{code}.json")
        if os.path.isfile(png) and os.path.isfile(js):
            continue
        if done >= limit:
            break
        vid = os.path.join(CACHE, f"Uploaded_{code}", f"Uploaded_{code}_TOD1200_NI_L.mp4")
        if not os.path.isfile(vid):
            log.write(f"{code} NO_VIDEO\n"); log.flush(); continue
        t1 = time.time()
        try:
            tmp = tempfile.mkdtemp(prefix="fid_")
            wav = os.path.join(tmp, "a.wav")
            extract_wav(vid, wav)
            y, sr = sf.read(wav, dtype="float32")
            if y.ndim > 1: y = y.mean(axis=1)
            grid, times = chroma_spectrogram(y)
            title = f"{code}  {m['name']}"
            spec_png(grid, times, png, title)
            g = grid / (grid.max() + 1e-9)
            act = np.where(g.max(axis=1) > 0.05)[0]
            stats = {"code": code, "name": m["name"], "lang": lang_of(m["name"]),
                     "active": [int(act.min() + 21), int(act.max() + 21)] if len(act) else [],
                     "n_strong": int((g.max(axis=1) > 0.2).sum())}
            json.dump(stats, open(js, "w", encoding="utf-8"), ensure_ascii=False)
            done += 1
            el = time.time() - t1
            log.write(f"{code} OK {el:.1f}s total={(time.time()-t0)/60:.1f}m\n"); log.flush()
            if done % 20 == 0:
                print(f"...{done} done {(time.time()-t0)/60:.1f}m", flush=True)
        except Exception as e:
            log.write(f"{code} FAIL {type(e).__name__} {str(e)[-120:]}\n"); log.flush()
    log.write(f"FAST BATCH DONE done={done} {(time.time()-t0)/60:.1f}m\n"); log.flush()
    print(f"ALL DONE {done} in {(time.time()-t0)/60:.1f}m", flush=True)

if __name__ == "__main__":
    main()
