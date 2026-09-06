# -*- coding: utf-8 -*-
"""批量神经网络转录: 输入 code 列表文件(每行一个), 逐首转录并出旋律图。
wav 优先用 ai_fast/wavcache 缓存(30s), 否则从视频提取。
输出: ai_iden/<CODE>.mid/_mel.png/_notes.json + 批量日志。
"""
import os, sys, json, time, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = r"C:\Users\locea\AppData\Local\Temp\2m4l"
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
CACHE = r"D:\Olivia_Lin_Songs"
WAVC = os.path.join(HERE, "ai_fast", "wavcache")

def get_wav(code):
    wp = os.path.join(WAVC, f"{code}.wav")
    if os.path.isfile(wp):
        return wp
    vid = os.path.join(CACHE, f"Uploaded_{code}", f"Uploaded_{code}_TOD1200_NI_L.mp4")
    tmp = os.path.join(tempfile.mkdtemp(prefix="bt_"), "a.wav")
    from transcribe_video import extract_audio
    extract_audio(vid, tmp, 30)
    os.makedirs(WAVC, exist_ok=True)
    os.replace(tmp, wp)
    return wp

def main():
    listfile = sys.argv[1]
    codes = [l.strip().split()[0].upper() for l in open(listfile, encoding="utf-8")
             if l.strip() and not l.startswith("#")]
    from src.transcription.onnx_transcriber import ONNXTranscriber
    from transcribe_video import roll_png
    from draw_melody import draw
    t = ONNXTranscriber(style="level2", mode="apc")
    outdir = os.path.join(HERE, "ai_iden")
    os.makedirs(outdir, exist_ok=True)
    log = open(os.path.join(outdir, "batch_pop_log.txt"), "a", encoding="utf-8")
    for i, code in enumerate(codes):
        mid = os.path.join(outdir, f"{code}.mid")
        if os.path.isfile(mid):
            print(f"[{i+1}/{len(codes)}] {code} 已有, 跳过", flush=True)
            continue
        t0 = time.time()
        try:
            wav = get_wav(code)
            t.transcribe(wav, mid)
            roll_png(mid, os.path.join(outdir, f"{code}_roll.png"), 30)
            draw(mid, os.path.join(outdir, f"{code}_mel.png"), 0, 30)
            dt = time.time() - t0
            print(f"[{i+1}/{len(codes)}] {code} OK {dt:.0f}s", flush=True)
            log.write(f"{code} OK {dt:.0f}s\n"); log.flush()
        except Exception as e:
            print(f"[{i+1}/{len(codes)}] {code} FAIL {type(e).__name__} {e}", flush=True)
            log.write(f"{code} FAIL {type(e).__name__} {e}\n"); log.flush()
    print("ALL DONE", flush=True)

if __name__ == "__main__":
    main()
