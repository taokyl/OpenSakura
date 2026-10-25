# services/stt — speech-to-text

A MekaHime-modified **SenseVoiceSmall** service (FunAudioLLM / FunASR): multilingual ASR
(zh / en / yue / ja / ko) with language ID, speech-emotion and audio-event tags, served by
FastAPI. ~0.05–0.2 s per utterance on a GPU after the startup warm-up.

```
GET  /health
POST /api/v1/asr   multipart: files=<wav/mp3/flac...>, lang=auto|zh|en|yue|ja|ko, use_itn=true
     -> {"result": [{"key", "text", "clean_text", "raw_text"}], "meta": {inference_time, total_time, audio_duration}}
```

| env | default | |
|---|---|---|
| `STT_DEVICE` | `cuda:0` | `cpu` works, slower |
| `STT_MODEL` | `./models` | model directory |
| `STT_HOST` / `STT_PORT` | `127.0.0.1` / `50000` | bind address (`launch.py` always uses 127.0.0.1) |

`launch.py` starts it in `services/stt/.venv` (created by `scripts/setup_windows.ps1`,
which installs CUDA 12.8 torch for RTX 50-series). Weights: `models/model.pt` (~936 MB) via
`scripts/download_sensevoice.py`; the small companion files are committed.

License: this code is MIT (upstream SenseVoice and FunASR are MIT). The SenseVoiceSmall
weights are distributed separately under the FunASR Model Open Source License Agreement.
