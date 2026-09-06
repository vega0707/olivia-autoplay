# -*- coding: utf-8 -*-
"""偏移转录: 取视频第 off~off+dur 秒音频 → AMT-APC 转录 → 旋律图。
用法: python transcribe_offset.py <video> <prefix> <off> <dur>
"""
import os, sys, subprocess, tempfile
REPO = r"C:\Users\locea\AppData\Local\Temp\2m4l"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import imageio_ffmpeg

def main():
    video, prefix, off, dur = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
    tmp = tempfile.mkdtemp(prefix="to_")
    wav = os.path.join(tmp, "seg.wav")
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    r = subprocess.run([ff, "-y", "-ss", str(off), "-t", str(dur), "-i", video,
                        "-ac", "1", "-ar", "16000", "-vn", wav],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(wav):
        raise RuntimeError("ffmpeg failed: " + r.stderr[-300:])
    from src.transcription.onnx_transcriber import ONNXTranscriber
    t = ONNXTranscriber(style="level2", mode="apc")
    mid = prefix + ".mid"
    t.transcribe(wav, mid)
    from transcribe_video import roll_png
    roll_png(mid, prefix + "_roll.png", dur)
    from draw_melody import draw
    draw(mid, prefix + "_mel.png", 0, dur)
    print("done", prefix)

if __name__ == "__main__":
    main()
