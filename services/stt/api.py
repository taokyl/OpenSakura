# Derived from FunAudioLLM/SenseVoice (https://github.com/FunAudioLLM/SenseVoice),
# MIT License, Copyright (c) FunASR.
# Modified by MekaHime Inc.
import os
import re
import time
import logging
import warnings
from io import BytesIO
from enum import Enum
from typing import List, Optional

warnings.filterwarnings("ignore", message=".*ffmpeg.*")

import torch
import soundfile as sf
import torchaudio
from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing_extensions import Annotated

from model import SenseVoiceSmall
from funasr.utils.postprocess_utils import rich_transcription_postprocess

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TARGET_FS = 16000


class Language(str, Enum):
    auto = "auto"
    zh = "zh"
    en = "en"
    yue = "yue"
    ja = "ja"
    ko = "ko"
    nospeech = "nospeech"


DEVICE = os.getenv("STT_DEVICE", "cuda:0")
MODEL_DIR = os.getenv(
    "STT_MODEL",
    os.path.join(os.path.dirname(__file__), "models"),
)

logger.info(f"Loading STT model from {MODEL_DIR} on {DEVICE} ...")
load_start = time.time()
m, kwargs = SenseVoiceSmall.from_pretrained(model=MODEL_DIR, device=DEVICE)
m.eval()
load_elapsed = time.time() - load_start
logger.info(f"Model loaded in {load_elapsed:.2f}s")

regex = r"<\|.*?\|>"

# Warm-up: the first CUDA inference pays for kernel selection / cuDNN autotune
# (tens of seconds on a cold GPU). Do it once here so the first real request is fast.
try:
    _warm_start = time.time()
    m.inference(data_in=[torch.zeros(16000, dtype=torch.float32)], language="auto", use_itn=True,
                ban_emo_unk=False, key=["warmup"], fs=16000, **kwargs)
    logger.info(f"Warm-up inference done in {time.time() - _warm_start:.2f}s")
except Exception as _e:  # noqa: BLE001 — warm-up is best-effort
    logger.warning(f"Warm-up inference failed (continuing): {_e}")

app = FastAPI(
    title="MekaHime STT API (modified SenseVoiceSmall)",
    description="MekaHime-modified SenseVoiceSmall: multilingual ASR with language, emotion and audio-event tags.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"service": "MekaHime STT (modified SenseVoiceSmall)", "docs": "/docs", "asr": "POST /api/v1/asr"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": MODEL_DIR,
        "device": DEVICE,
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


@app.post("/api/v1/asr")
async def asr(
    files: Annotated[List[UploadFile], File(description="audio files (wav/mp3/flac/ogg)")],
    keys: Annotated[Optional[str], Form(description="comma-separated keys, one per file")] = None,
    lang: Annotated[Language, Form(description="auto | zh | en | yue | ja | ko")] = "auto",
    use_itn: Annotated[bool, Form(description="inverse text normalization (punctuation, numbers)")] = True,
):
    if not files:
        raise HTTPException(status_code=400, detail="no audio file provided")

    request_start = time.time()
    audios = []
    audio_lengths = []

    for file in files:
        try:
            file_bytes = await file.read()
            file_io = BytesIO(file_bytes)
            data_np, audio_fs = sf.read(file_io, dtype="float32")
            audio_tensor = torch.from_numpy(data_np)
            if audio_tensor.dim() == 1:
                audio_tensor = audio_tensor.unsqueeze(0)
            else:
                audio_tensor = audio_tensor.T

            if audio_fs != TARGET_FS:
                resampler = torchaudio.transforms.Resample(orig_freq=audio_fs, new_freq=TARGET_FS)
                audio_tensor = resampler(audio_tensor)

            audio_tensor = audio_tensor.mean(0)
            audios.append(audio_tensor)
            audio_lengths.append(len(audio_tensor) / TARGET_FS)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"could not decode {file.filename}: {str(e)}")

    if lang == "":
        lang = "auto"

    if not keys:
        key = [f.filename for f in files]
    else:
        key = keys.split(",")

    inference_start = time.time()
    try:
        res = m.inference(
            data_in=audios,
            language=lang,
            use_itn=use_itn,
            ban_emo_unk=False,
            key=key,
            fs=TARGET_FS,
            **kwargs,
        )
    except Exception as e:
        logger.error(f"Inference failed: {e}")
        raise HTTPException(status_code=500, detail=f"inference failed: {str(e)}")

    inference_elapsed = time.time() - inference_start
    total_elapsed = time.time() - request_start

    if len(res) == 0:
        return {"result": [], "meta": {"inference_time": inference_elapsed, "total_time": total_elapsed}}

    for it in res[0]:
        it["raw_text"] = it["text"]
        it["clean_text"] = re.sub(regex, "", it["text"], 0, re.MULTILINE)
        it["text"] = rich_transcription_postprocess(it["text"])

    logger.info(
        f"ASR completed: {len(files)} file(s), "
        f"total_audio={sum(audio_lengths):.1f}s, "
        f"inference={inference_elapsed:.3f}s, "
        f"total={total_elapsed:.3f}s"
    )

    return {
        "result": res[0],
        "meta": {
            "inference_time": round(inference_elapsed, 3),
            "total_time": round(total_elapsed, 3),
            "audio_duration": round(sum(audio_lengths), 2),
        },
    }


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("STT_HOST", "127.0.0.1")
    port = int(os.getenv("STT_PORT", "50000"))
    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
