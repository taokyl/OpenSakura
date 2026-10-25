# vendor/: the voice server

OpenSakura speaks through **`vendor/tts-engine/main.py`, the OpenSakura voice server: a MekaHime build of
GPT-SoVITS (v2ProPlus)**. The server code is in this repository (MIT); the upstream GPT-SoVITS checkout, its
pretrained models, the Python venv, ffmpeg and Sakura's voice are assembled from public sources by

```bash
python scripts/setup_tts.py
```

Sakura's voice is downloaded from the gated Hugging Face repository
[MekaHime/MekaHime_Sakura](https://huggingface.co/MekaHime/MekaHime_Sakura): accept its
personal-use license on that page once, then log in (`hf auth login`) or pass `--hf-token`.
Install details, flags, layout and the package list are in [`tts-engine/README.md`](tts-engine/README.md).

`launch.py` starts the server as one process on port 8002 (`tts.url`, `tts.engine_dir` and
`tts.character_id` in `config/settings.json`). Without a GPU, run `python launch.py --text-only`, or point
`tts.url` at any machine that runs a server speaking the contract below.

## Contract (any server that speaks this works)

```
emit  tts_request_gateway  {task_id, turn_id, text: "【happy2】Hello!", character_id, language, audio_format}
on    task_queued          {task_id, sentence_count}
on    audio_ready          {task_id, audio: <bytes>, audio_format, audio_duration, is_final}
on    error                {task_id, error}
GET   /ping  -> ok         GET /api/characters -> {characters: {...}}
```

Emotion tags are `【<name><intensity>】` (`happy1-4`, `sad1-4`, `angry1-4`, `shy1-3`, `tsun1-3`,
`whisper1-3`, ...), the keys of the speaker's `references/emotions.json`; a tag without a recording falls back
to `neutral1`. Sakura's voice has 68 tags, each with a recorded clip. `sakura/tts_emotion_mapper.py` turns Sakura's
emotion state into these tags. A non-empty `turn_id` asks for one audio for the whole reply. `audio_format` is
`wav` (default) or `opus`. Optional request fields: `speed` (0.5–2.0), `top_k` (1–100), `top_p` (0–1],
`temperature` (0–2], `seed`. `audio_ready` may carry a `warning` (for example when words may be missing, or when a
text had nothing to speak, which returns 0.3 s of silence instead of an error).

License: the server code is MIT (upstream GPT-SoVITS is MIT); the voice model is a MekaHime asset for
personal, hobbyist use only.
