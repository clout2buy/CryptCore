from __future__ import annotations

import argparse
from pathlib import Path

import soundfile as sf
from kokoro_onnx import Kokoro


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate local Kokoro TTS audio.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--voices", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--text", required=True)
    parser.add_argument("--voice", default="af_heart")
    parser.add_argument("--speed", type=float, default=0.96)
    parser.add_argument("--lang", default="en-us")
    args = parser.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    kokoro = Kokoro(args.model, args.voices)
    samples, sample_rate = kokoro.create(
        args.text,
        voice=args.voice,
        speed=args.speed,
        lang=args.lang,
    )
    sf.write(str(out), samples, sample_rate)
    print(str(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
