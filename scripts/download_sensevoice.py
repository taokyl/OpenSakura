#!/usr/bin/env python3
"""Download the SenseVoiceSmall weights the STT service needs (model.pt, ~936 MB).

The small companion files (config.yaml, am.mvn, tokens.json, bpe model) are
committed; only model.pt is fetched. Source: Hugging Face mirror of the
official FunAudioLLM release. ModelScope works too (see README).
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

URL = "https://huggingface.co/FunAudioLLM/SenseVoiceSmall/resolve/main/model.pt"
DEST = Path(__file__).resolve().parent.parent / "services" / "stt" / "models" / "model.pt"


def main() -> int:
    if DEST.exists() and DEST.stat().st_size > 800_000_000:
        print(f"already present: {DEST} ({DEST.stat().st_size/1e6:.0f} MB)")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    part = DEST.with_suffix(".pt.part")
    print(f"downloading {URL}\n      → {DEST}")

    def hook(blocks: int, bs: int, total: int) -> None:
        done = blocks * bs
        if total > 0:
            pct = min(100, done * 100 // total)
            sys.stdout.write(f"\r  {done/1e6:7.0f} / {total/1e6:.0f} MB  {pct:3d}%")
            sys.stdout.flush()

    urllib.request.urlretrieve(URL, part, hook)
    part.replace(DEST)
    print(f"\ndone: {DEST.stat().st_size/1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
