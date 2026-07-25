#!/usr/bin/env python3
"""Generate a narration track + exact caption timings with Kokoro TTS.

Free and CPU-only: Kokoro-82M is Apache-2.0 and runs several times faster than
real time on a CPU runner, so this adds a few seconds to a render rather than
needing a GPU or a paid API.

Caption timings are EXACT rather than estimated: each caption chunk is
synthesized on its own, its real duration measured from the returned samples,
and the chunks concatenated. No forced alignment, no extra model.

Usage:
    generate_narration.py --spec spec.json --outdir public

spec.json:
    {
      "voice": "af_heart",
      "speed": 1.0,
      "chunks": ["Most home-based food businesses", "undercharge by 25 to 40%."]
    }

Writes:
    <outdir>/narration.wav
    <outdir>/captions.json   [{"text": ..., "startMs": ..., "endMs": ...}, ...]
    prints the total duration in seconds to stdout
"""
import argparse
import json
import os
import sys

SAMPLE_RATE = 24000  # Kokoro's native rate
GAP_SECONDS = 0.12   # small breath between chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    with open(args.spec) as fh:
        spec = json.load(fh)

    chunks = [c.strip() for c in (spec.get("chunks") or []) if c and c.strip()]
    if not chunks:
        print("ERROR: spec has no chunks", file=sys.stderr)
        return 1

    voice = spec.get("voice") or "af_heart"
    speed = float(spec.get("speed") or 1.0)

    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code=voice[0] if voice else "a")

    os.makedirs(args.outdir, exist_ok=True)

    audio_parts: list = []
    captions: list[dict] = []
    cursor = 0.0
    gap = np.zeros(int(SAMPLE_RATE * GAP_SECONDS), dtype="float32")

    for chunk in chunks:
        samples = []
        for _, _, audio in pipeline(chunk, voice=voice, speed=speed):
            samples.append(np.asarray(audio, dtype="float32"))
        if not samples:
            print(f"WARNING: no audio for chunk {chunk!r}", file=sys.stderr)
            continue
        part = np.concatenate(samples)
        duration = len(part) / SAMPLE_RATE

        captions.append(
            {
                "text": chunk,
                "startMs": int(round(cursor * 1000)),
                "endMs": int(round((cursor + duration) * 1000)),
            }
        )
        audio_parts.append(part)
        audio_parts.append(gap)
        cursor += duration + GAP_SECONDS

    if not audio_parts:
        print("ERROR: nothing synthesized", file=sys.stderr)
        return 1

    track = np.concatenate(audio_parts)
    wav_path = os.path.join(args.outdir, "narration.wav")
    sf.write(wav_path, track, SAMPLE_RATE)

    with open(os.path.join(args.outdir, "captions.json"), "w") as fh:
        json.dump(captions, fh)

    total = len(track) / SAMPLE_RATE
    print(f"{total:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
