# vendor/tts-engine: the OpenSakura voice server

Sakura speaks through `main.py`, the **OpenSakura voice server, a MekaHime build of GPT-SoVITS (v2ProPlus)**.
It is a small MIT-licensed server on top of an unmodified upstream
[GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) checkout. Everything else in this folder is assembled
from public sources by `scripts/setup_tts.py`, and Sakura's voice comes from a gated Hugging Face repository.
Only `main.py`, `requirements-tts.txt`, this README, `LICENSE` and `THIRD_PARTY_NOTICES.md` are in git.

## Install

```bash
python scripts/setup_tts.py            # Windows 10/11 with an NVIDIA GPU (CUDA 12.8 torch): tested
python scripts/setup_tts.py --cpu      # no GPU: works, about half real time on a desktop CPU
python launch.py --check               # every "tts" row should be OK
```

**Linux and macOS are untested.** The script has Linux (NVIDIA GPU or `--cpu`) and Apple Silicon (CPU torch
with MPS) paths, but neither has been run yet; see [Platforms](#platforms).

Needs Python 3.11 or 3.12 (3.11 is the tested one: the script takes the first 3.11 it finds, itself,
`py -3.11` or `python3.11`, and falls back to 3.12; 3.10 and 3.13 cannot install the pinned packages), about
9 GB of disk, about 2.5 GB of free VRAM, and git (optional: without it the pinned commit is fetched as a zip).
On Linux, glibc 2.28 or newer (Ubuntu 20.04+, Debian 10+, RHEL / Rocky 8+); on Ubuntu 22.04, whose `python3`
is 3.10, install `python3.11` and `python3.11-venv` first. On a Mac, macOS 14 or newer on Apple Silicon with a
native arm64 Python (not one running under Rosetta). The script checks all of this before installing anything.
RTX 50-series cards need the CUDA 12.8 build, which is the default. On Windows, keep the folder path short
(under about 100 characters) unless long paths are enabled.

**ffmpeg** is needed only for Opus output (`audio_format: "opus"`). The script downloads a build on Windows and
Linux x86_64 (on macOS: `brew install ffmpeg`); without it, Opus requests get WAV and a `warning`. WAV output and
speed changes (`--speed`, or `speed` in a request) do not need it: at the pinned commit upstream applies the
speed inside the SoVITS decoder and never calls its ffmpeg-based `speed_change()`. `main.py` checks this when
it loads upstream; should a different upstream need ffmpeg for speed and none is found, it speaks at speed
1.0 and says so in the `warning` field.

**Sakura's voice** is the gated Hugging Face repository
[MekaHime/MekaHime_Sakura](https://huggingface.co/MekaHime/MekaHime_Sakura). Open that page while
logged in to Hugging Face, accept the personal-use license ("Agree and access repository"), then give the
script a token in one of three ways: `hf auth login` once (any `huggingface_hub` install works, including
`vendor/tts-engine/.venv/Scripts/hf` (Windows) or `.venv/bin/hf` after a first run), `HF_TOKEN=hf_...`, or
`--hf-token hf_...`. The token
is only passed to the download and is never written into the repository. Without access the script finishes
everything else and tells you what to do; re-run it afterwards. The voice is downloaded at a pinned revision of
that repository (`f81065fa`, 68 emotion tags) and its two weight files are checked by size and SHA-256 like
every other download.

Re-running is safe: finished steps are verified (SHA-256) and skipped; a re-run of a complete install takes about
10 s. A venv an earlier run left unfinished (no pip, or an interpreter that no longer starts) is created again;
an existing GPT-SoVITS checkout must still have the pinned `TTS.py`, and other locally edited upstream files are
listed as a warning. A step that fails is reported and the steps that do not need it still run; the summary at
the end lists every step (`OK`, `--` skipped or optional, `!!` failed) and the exit code is non-zero if any
failed. Useful flags: `--skip-voice`, `--voice-from <folder>` (copy a voice you already have),
`--update-voice`, `--voice-revision <rev>` (another revision of the voice repository; its weights are then not
checked against the pins), `--skip-ffmpeg`, `--reinstall`, `--engine-dir <path>`, `--python <interpreter>`,
`--self-test` (starts the server once and speaks a line).

What it builds:

```
vendor/tts-engine/
  main.py                    the server (this repository, MIT)
  requirements-tts.txt       its Python packages (inference subset of upstream's list, see below)
  .venv/                     Python venv: torch + torchaudio 2.9.1 (+cu128 / +cpu) and requirements-tts.txt
  GPT-SoVITS/                RVC-Boss/GPT-SoVITS @ b4570b876f5c (2026-10-19), MIT, unmodified
    GPT_SoVITS/pretrained_models/chinese-hubert-base/            HuBERT speech features   (lj1995/GPT-SoVITS)
    GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large/  BERT text features       (lj1995/GPT-SoVITS)
    GPT_SoVITS/pretrained_models/sv/pretrained_eres2netv2w24s4ep4.ckpt  speaker embedding for v2Pro models
    GPT_SoVITS/pretrained_models/fast_langdetect/lid.176.bin     fastText language ID
    GPT_SoVITS/text/G2PWModel/                                   Chinese polyphone model  (XXXXRT/GPT-SoVITS-Pretrained)
    GPT_SoVITS/text/ja_userdic/user.dict                         Japanese user dictionary, built by upstream's own code
  nltk_data/                 English POS tagger + CMUdict
  ffmpeg/                    ffmpeg + ffprobe (Windows: gyan.dev 8.0.1; Linux: BtbN static), only for Opus output
                             (WAV output and speed changes do not use it)
  Speakers/MekaHime_Sakura/  Sakura's voice: MekaHime_Sakura.ckpt (GPT), MekaHime_Sakura.pth (SoVITS),
                             character.json, references/emotions.json + one reference clip per emotion
  cache/                     derived files the server writes (padded clips, prompt config, re-marked weights)
```

Every model and data file, and the voice weights, are pinned by repository revision, size and SHA-256 in
`scripts/setup_tts.py`. GPT-SoVITS is pinned by commit. Without git, the zip GitHub serves for that commit is
checked before unpacking against a pinned SHA-256 over all 282 of its files, and the unpacked
`GPT_SoVITS/TTS_infer_pack/TTS.py` against its own pinned SHA-256 (again on every re-run, also for a git
checkout). A download that does not match its pinned size or SHA-256 is deleted and stops that step at once
instead of being retried; network errors and timeouts are retried.

## Run

`launch.py` starts it for you (one process, port from `tts.url`, `--character` from `tts.character_id`,
`--device` from `tts.device` if you set one in `config/settings.json`). By hand:

```bash
vendor/tts-engine/.venv/Scripts/python vendor/tts-engine/main.py --port 8002     # Windows
vendor/tts-engine/.venv/bin/python vendor/tts-engine/main.py --port 8002         # Linux / macOS
```

| flag | default | |
|---|---|---|
| `--port` / `--host` | `8002` / `127.0.0.1` | bind address |
| `--device` | `auto` | `cuda` (or `cuda:N`) when available, then Apple `mps`, then `cpu` |
| `--half` / `--no-half` | fp16 on CUDA | |
| `--character` | first folder in `Speakers/` | speaker loaded at start; requests for another speaker switch to it |
| `--text-split` | `sentence` | `sentence`: every sentence of a run is its own GPT fragment (see [How it uses upstream](#how-it-uses-upstream)); or one of upstream's split methods for the whole run: `cut0` none, `cut1` every 4 phrases, `cut5` every punctuation mark |
| `--batch-size` | `4` | sentences the GPT stage decodes together (CUDA graphs are captured for 1, 2 and 4; each slot holds ~50 MB of VRAM) |
| `--top-k` `--top-p` `--temperature` `--repetition-penalty` `--speed` `--seed` | `15` `1.0` `1.0` `1.35` `1.0` `-1` | sampling (a request may also send `top_k`, `top_p`, `temperature`, `speed`, `seed`; ranges under [Contract](#contract-any-server-that-speaks-this-works)) |
| `--fragment-interval` | `0.25` | pause between sentences (fragments), seconds |
| `--trim-silence` / `--no-trim-silence` | on | cut the silence before and after the speech to 0.12 s (see below) |
| `--dropout-guard` / `--no-dropout-guard` | on | speak a sentence again when its audio is far too short for its text (see below) |
| `--dropout-retries` | `2` | at most this many extra takes of such a sentence |
| `--no-cuda-graph` | off | disable upstream's CUDA-graph acceleration of the GPT stage |
| `--no-warmup` | off | skip the start-up synthesis that makes the first real request fast |
| `--verbose` | off | show upstream's console output |
| `--cors` | off | let browser pages on other origins connect (local testing) |

Start-up loads the models and runs three short warm-up lines (English, Chinese, and English with a kana word,
which loads the language splitter and the Japanese front-end); `/ping` answers `503 loading` until then and
`ok` afterwards, which is what `launch.py` waits for. The console logs one line per request with the
audio length, synthesis time, real-time factor and the language mode used (`lang=en>auto` when an English run
went through auto mode, see below); `/api/health` also lists the settings in use (`text_split`, `batch_size`,
`eos_floor`, ...) and counts the dropout guard's extra takes under `retries`. Ctrl-C stops the server within about
a second, also while a client is connected or a synthesis is running.

## Contract (any server that speaks this works)

```
emit  tts_request_gateway  {task_id, turn_id, text: "【happy2】Hello!", character_id, language, audio_format}
on    task_queued          {task_id, turn_id, sentence_count, queue_position}
on    audio_ready          {task_id, turn_id, audio: <bytes>, audio_format, audio_duration, sample_rate,
                            is_final, text, character_id, language, emotions, elapsed_ms}
on    error                {task_id, turn_id, error}
GET   /ping  -> ok         GET /api/characters -> {characters: {...}, current}      GET /api/health -> JSON
```

- **Emotion tags** are `【<name><intensity>】` (`happy1-4`, `sad1-4`, `angry1-4`, `shy1-3`, `tsun1-3`,
  `whisper1-3`, ...): the keys of `Speakers/<id>/references/emotions.json`, each naming a reference clip and its
  (Chinese) transcript. Sakura's `emotions.json` has 68 tags, each with its clip (`angry5`, which never had a
  recording, was removed from the Hugging Face repository; a voice downloaded before that still lists it, and it
  falls back to `neutral1` like any tag without a recording). A text may switch tags mid-way
  (`【neutral1】Well. 【happy1】Hi!`): each run is spoken with its own reference and the pieces are joined.
  `sakura/tts_emotion_mapper.py` turns Sakura's emotion state into these tags. A run of only punctuation or
  symbols (`【shy1】……`, `【happy1】~`) is left out, since upstream would answer it with an error or with a second
  of 16 kHz silence. A text with nothing to speak at all (only tags, punctuation or emoji) gets 0.3 s of
  silence and a `warning` instead of an error; a blank `text` is `bad request: empty text`.
- **`/api/characters`** lists, per speaker folder: `name`, `language` (of the reference transcripts), the
  `emotions` that have a clip, `no_clip` (listed tags without one), `default_emotion` and `loaded`. No other
  text from a voice pack's `character.json` is served.
- **language**: `English`, `Chinese`, `Japanese`, `Korean`, `Cantonese` or `auto` (also `en`, `zh`, `ja`, ...).
  The reference transcripts are Chinese; GPT-SoVITS speaks the target language in her voice. Upstream's English
  front-end reads Latin letters only and silently drops a word written in kana, Hangul or Chinese characters,
  and the emotion mapper writes her name (`さくら`), "Master" (`ごしゅじんさま`), the family words, the
  `-san` / `-chan` honorifics and "haha" (`哈哈`) that way inside English text. So an English run that contains
  any of those characters is spoken in upstream's `auto` mode, which splits it by language and reads each part
  with its own front-end (Latin text stays English); runs without them use the English front-end as before. The
  other languages are used as asked: in `Chinese` mode kana are still dropped, and auto mode is not used there
  because it can read Chinese characters next to kana as Japanese (send `auto` for mixed Chinese and Japanese).
- **turn mode** (a non-empty `turn_id`, what OpenSakura sends): one `audio_ready` for the whole text.
  Without `turn_id` every sentence is sent as soon as it is ready and the last one has `is_final: true`.
  Requests are spoken one at a time in arrival order, so one request's sentences are never interleaved with
  another's. When a client disconnects, its requests that have not started, and the sentences of a request not
  yet spoken, are dropped (a synthesis already running finishes).
- **audio_format**: `wav` (16-bit PCM mono at the model's 32 kHz, the default, plays in every browser) or
  `opus` (Ogg/Opus 48 kHz through ffmpeg). Without ffmpeg an `opus` request gets WAV, `audio_format: "wav"`
  and a `warning` field; any other value also gets WAV and a `warning`. Audio larger than 3 MiB arrives as
  consecutive chunks of one file (`chunk_index` / `chunk_count`, `is_final` on the last);
  `sakura/tts_client.py` joins them.
- **sampling options** (optional numbers): `speed` 0.5-2.0, `top_k` a whole number 1-100, `top_p` above 0 and
  at most 1, `temperature` above 0 and at most 2, `seed` a whole number from 0 to 4294967295 or -1 (random). A
  value outside its range, or one that is not a number, gets an `error` event such as
  `bad request: speed must be between 0.5 and 2.0 (got 3)`; `null` counts as not sent.
- **warning** (optional on `audio_ready`): set when the audio is not quite what was asked for: WAV sent instead
  of Opus, a text with nothing to speak, or speech that came out too short for its text in every take (see the
  dropout guard below).

## How it uses upstream

`main.py` imports `GPT_SoVITS/TTS_infer_pack/TTS.py` (class `TTS` with a `TTS_Config`, the same library
upstream's `api_v2.py` uses) and adds:

- speaker folders, emotion tags, tag fallback and mid-text tag switches;
- one prompt cache per reference clip, so switching emotions does not recompute the reference features;
- reference clips shorter than 3 s (upstream rejects them) are padded with silence into `cache/`;
- **SoVITS weights header.** Upstream saves v2Pro / v2ProPlus fine-tunes with the first two bytes of the torch
  zip (`PK`) replaced by a version marker (`05` / `06`) and reads the model version back from that marker.
  Such a file loads as is. A file whose marker was turned back into `PK` is guessed as a plain v2 model from
  its size: upstream drops its speaker-embedding layers (`sv_emb`, `ge_to512`, `prelu`) and synthesis then fails
  with a channel mismatch. For that case `main.py` writes a copy with the marker restored to
  `cache/speakers/<id>/` (byte-identical to the file upstream saved) and loads that;
- small compatibility shims: `jieba_fast` (no wheels) is served by `jieba`, and with torchaudio 2.9 (which
  decodes through torchcodec + FFmpeg DLLs) the WAV reference clips are read with `soundfile` instead;
- **silence trimming**: the model sometimes opens a line with up to 1.3 s of silence (her whispered `shy1`
  lines most often) and upstream ends every run with a 0.25 s pause. Each run keeps 0.12 s of silence before
  and after its speech. On 10 ms frames, silence is what lies more than 45 dB under the loudest frame of the
  run, or under -80 dBFS: the model's own silence sits at -87 dBFS and below, while the softest onsets and word
  endings of her whispers stay within 45 dB of their loudest frame. Over 96 recorded takes, nothing removed was
  louder than 46.7 dB under the loudest frame, and speech recognition gave the same words before and after
  trimming for 93 of them; in each of the other 3 one word differed although only silence (under -75 dBFS)
  had been removed. Each tagged run is trimmed on its own before the runs are joined, so a two-tag turn has
  0.24 s of silence at the joint (0.12 + 0.12) whatever the natural pause was. `audio_duration` is the length
  after trimming (for Opus, of the PCM before encoding: the Ogg file adds its pre-skip and padding);
- every run comes back at the model's sample rate: when upstream finds nothing to read in a run it returns a
  second of silence at 16 kHz, which is dropped, and any other audio at another rate would be resampled;
- **one GPT fragment per sentence**: upstream's text-to-semantic (GPT) stage reads each fragment after the
  reference clip's transcript and sometimes starts at the fragment's second sentence, as if the reference clip had
  already said the first one. With a whole reply as one fragment (upstream's `cut1`, the default before) speech
  recognition found a phrase missing in 18 of 125 takes of 25 Sakura-style replies (2-4 sentences, lowercase,
  with `?` `!` `~` `...`, kana and 哈; ~10 s of speech each), 17 of them the opening sentence; three replies lost
  it in 5 of 5 takes. Sampling settings (top-k, temperature, repetition penalty), upstream's plain (non-CUDA-graph)
  GPT loop and a leading pause on the whole text did not fix it, while the same sentence on its own was always
  spoken. So each tagged run is cut into sentences (at `。！？!?…` and `.`; a sentence under 4 syllables such as
  `okay!` joins the next one), every sentence gets a leading `.` (a short pause, as upstream gives its own short
  first sentences; not before a 1-3 letter head with a comma such as `oh,` / `嗯，`, nor before a one-word
  sentence), and the sentences go to upstream in one request, one fragment per line (`cut0`), decoded
  `--batch-size` (4) at a time. On the same 125 takes no phrase was missing, nor on 70 takes of 14 other replies
  (8 with `cut1`), and the time per reply halved (see [Performance](#performance-rtx-5070-12-gb-windows-11-fp16));
  the replies that `cut1` spoke in full came out about 8 % shorter (4.1 instead of 3.75 syllables per second,
  pauses included). Known limit: a short exclamation that joins the sentence before it can still be left out
  (`you're late. again!` lost `again!` in 4 of 5 takes, against 2 of 5 with `cut1`). With quiet or whispery
  references (`sleepy1`, `tired1`, `sad3`, `sad4`) a sentence can still come out silent in every take: about 3 %
  of takes lost a sentence on a 25-line test over many tags, all on one `sleepy1` line. `fear1`'s transcript does
  not match its clip, so the model speaks that reference text before each sentence. The emotion mapper never
  picks `fear1`, `sleepy1`, `tired1` or `sad4`; they only play when a request names them directly;
- **EOS floor**: upstream's plain GPT loop does not let a fragment end before 11 tokens (0.44 s), but its
  CUDA-graph loop (`GPT_SoVITS/Accel/PyTorch/AR/runner.py`, `ModelRunner.decode_step`) only forbids ending on the
  first token, and a sentence on its own then sometimes ended after 1-2 tokens, with no speech
  (`did something happen at work?` in 3 of 4 takes). At start-up on CUDA `main.py` compiles upstream's own
  `decode_step` source with that one comparison changed (`== 0` to `< 11`) and puts it in place of the method; the
  files on disk are not changed. If that line is not in upstream's source (another upstream version) it logs a
  warning and leaves upstream as it is. `/api/health` shows `eos_floor`: `11 tokens`, `built in` (CPU and MPS
  use the plain loop) or `not installed (...)`;
- **dropout guard**: the GPT stage can still end a sentence early. The expected length of a sentence is its
  syllable count (vowel groups per English word, one per Chinese character; Japanese kana and Korean Hangul count
  0.5 and 0.6, estimated) at 4.4 syllables per second. If its speech (first to last frame within 40 dB of the
  loudest) lasts under 55 % of that, that sentence alone is synthesized again with another seed (at the same
  batch size, so upstream does not rebuild its GPT decoder), up to `--dropout-retries` (2) more times while it
  stays short, and the take with the most speech is kept. A sentence under 6 syllables (where the estimate is too
  rough) counts as short only when it comes out nearly silent, with under 0.2 s of speech. With an upstream
  `cut*` split the whole run is checked instead, and its last extra take is split at every punctuation mark
  (`cut5`). The log has a warning either way, `/api/health` counts the extra takes under `retries`, and if every
  take of a sentence is short `audio_ready` carries a `warning`. Natural takes measured 1.9-6.4 syllables per
  second over 143 takes of six English and Chinese lines; short takes came out at 9-14, against the limit of
  8.0, so the guard only catches large losses. Before the per-sentence split and the EOS floor it re-synthesized
  about 6-9 % of short replies and two-sentence lines (roughly +0.3 s each); since then it took no extra take in
  327 requests of mostly `neutral1` replies, but 26 in 342 requests spread over all 68 tags (mostly quiet
  references), and it cannot rescue a sentence that every take leaves silent. It cannot loop (at
  most `--dropout-retries` extra takes per sentence);
- the Socket.IO + HTTP server, WAV / Opus encoding, queueing (one request at a time on one daemon worker
  thread, so Ctrl-C does not wait for a synthesis in flight; connected clients are disconnected on shutdown),
  warm-up and per-request timing logs. Upstream's console output is captured per request on the worker
  thread (for the timing split and error reports) without swapping `sys.stdout` while running;
  `--verbose` shows it instead.

## Python packages: what differs from upstream's requirements.txt

Upstream's list also serves training, dataset tools and the Gradio WebUI. `requirements-tts.txt` keeps the
inference subset and prefers packages that ship wheels, so no compiler is needed on Windows:

| upstream | here | why |
|---|---|---|
| `gradio<5` | left out | WebUI only |
| `tensorboard` | left out | training only |
| `funasr`, `faster-whisper` (extra-req.txt), `ctranslate2`, `modelscope` | left out | speech recognition / dataset preparation and model downloads; not imported for inference |
| `fastapi[standard]`, `pydantic<=2.10.6` | left out | upstream's `api_v2.py` HTTP server; `main.py` serves with aiohttp + python-socketio |
| `av`, `sentencepiece`, `chardet`, `rotary_embedding_torch` | left out | not imported by the inference path at this commit |
| `jieba_fast` | `jieba` | jieba_fast is a source-only C extension; jieba has the same API and dictionary (`main.py` aliases it) |
| `pyopenjtalk` | `pyopenjtalk-plus` | pyopenjtalk is source-only (cmake + C++); the -plus fork has wheels and bundles the Open JTalk dictionary |
| `onnxruntime-gpu` (x86_64) | `onnxruntime` | only the Chinese G2PW model uses it; the CPU build avoids a second CUDA/cuDNN stack |
| `--no-binary=opencc` | OpenCC wheel | the wheel works; building OpenCC needs cmake + a C++ compiler |
| `torchaudio` (unpinned) + `torchcodec` | torch/torchaudio 2.9.1 pinned, no torchcodec | torchcodec needs FFmpeg shared libraries; the references are WAV |
| (only transitive upstream) | `resampy`, `matplotlib`, `rich`, `loguru`, `einops`, `soundfile`, `huggingface_hub` | imported by the inference code; upstream gets them through the packages left out above |
| | `python-socketio`, `aiohttp` | the server |

Korean (`g2pk2`) and Cantonese (`ToJyutping`) are installed but not exercised by OpenSakura's tests.

## Performance (RTX 5070 12 GB, Windows 11, fp16)

| | |
|---|---|
| install from scratch | ~5.3 GB of downloads (the CUDA torch wheel alone is 2.9 GB), 8.4 GB on disk; 3 min here with torch already in the pip cache |
| start-up | 25-33 s to `/ping ok` (models ~7-9 s, three warm-up lines 18-24 s, mostly CUDA-graph capture); `/api/health` answers within 0.6 s throughout |
| a 3 s English line | ~0.45-0.5 s warm (real-time factor ~0.15) |
| a reply of 2-4 sentences (25 Sakura-style replies, median 10.2 s of audio, 5 takes each) | 0.75 s median, 90 % within 0.98 s, max 1.61 s (real-time factor 0.073); with the whole reply as one fragment (`cut1`, batch 1) 1.46 s, 1.91 s and 3.38 s. 14 other replies (median 7.6 s): 0.67 s median, 90 % within 0.92 s (`cut1`: 1.15 s) |
| replies from live chats (14, with the emotion mapper's tags, kana and 哈) | a 2.1 s reply in 0.41 s, 4-30 s replies in 0.5-2.2 s (real-time factor 0.05-0.10 from 9 s up) |
| an English line with kana and 哈 (`哈哈哈, ごしゅじんさま, welcome home! さくら missed you so much today.`) | 5.2-6.2 s of audio in 0.55-0.63 s (~0.85 s with `cut1`); before the auto routing the same line gave 2.5-3.1 s, with those words left out |
| silence before the first word | median 0.13 s (max 0.16 s) over 40 takes of a two-sentence line; whispered `shy1` median 0.15 s (max 0.33 s over 20 takes, 0.45 s in an earlier run: a breathy onset quieter than -50 dBFS that is kept); measured as 10 ms windows under -50 dBFS (with `cut1`; the trimming is the same since). Untrimmed, the same two lines had medians of 0.20 s and 0.66 s (max 1.25 s) |
| skipped phrases | speech recognition over those 125 takes found no phrase missing (18 with `cut1`), nor over the 70 takes of the other 14 replies (8 with `cut1`); in 7 of the 125 a stretch of 3+ words was misheard, mostly one phrase the model mispronounces (`soup or a sandwich`), as in every configuration tested. The 14 chat replies: none missing |
| silent short replies | 100 takes of five 2-4 syllable lines ("Bye now.", "Thank you!", ...): none came out silent (least speech 0.36 s) and the dropout guard took no extra take; before the EOS floor, 6 first takes of 100 came out silent and were synthesized again (+0.3-0.6 s) |
| 84 s of text in one request | 4.4 s (real-time factor 0.05), delivered as two 3 MiB chunks (90 s took ~12 s with `cut1`) |
| first use of an emotion tag | +0.1-0.4 s once (reference features are then cached) |
| VRAM | ~2.2 GB while idle, ~2.4 GB after long requests (`--batch-size 4` adds ~0.15 GB to batch size 1) |
| `--device cpu` (same machine) | 3.5 s of audio in ~1.8 s (measured with `cut1`, not again since) |

Each request logs its split (`ref + text + gpt + sovits` seconds); the GPT (text-to-semantic) stage
dominates. Startup and per-request numbers are from `cache/` being warm; the very first start also writes
a 170 MB copy of the weights when the `.pth` has a plain `PK` header (see above).

## Platforms

Tested: Windows 11, RTX 5070 12 GB, CUDA 12.8 driver, Python 3.11 (GPU and `--device cpu`).

Untested:

- **Linux**: the script takes the same steps (CUDA 12.8 wheels with an NVIDIA GPU, CPU wheels with `--cpu`;
  BtbN's static ffmpeg or the system one), but none of it has been run yet. It needs glibc 2.28 or newer
  (Ubuntu 20.04+, Debian 10+, RHEL / Rocky 8+): torch 2.9.1, onnxruntime 1.31.0 and soundfile 0.14.0 ship
  `manylinux_2_28` wheels only, onnxruntime has no source package, and on an older system pip would try to
  build pyopenjtalk-plus from source (cmake + a C++ compiler). The script stops with that reason first.
- **macOS**: Apple Silicon gets the PyPI torch build (CPU, and `--device mps` for the GPU) and needs
  `brew install ffmpeg` for Opus; none of it has been run yet. It needs macOS 14 or newer (onnxruntime 1.31.0
  has a single macOS wheel, `macosx_14_0_arm64`, and no source package) and a native arm64 Python: an x86_64
  Python running under Rosetta gets x86_64 wheels, which do not exist for these packages, and the script says
  so. Intel Macs have no torch 2.9 wheels.

Note for the first Linux run: the pins in `requirements-tts.txt` were resolved and tested on Windows only
(numpy 1.26.4, transformers 4.57.6, onnxruntime 1.31.0, ...; the previous engine ran numpy 2.3.3,
transformers 4.57.3 and onnxruntime 1.22.1). Upstream needs numpy < 2. If pip cannot resolve the set on Linux,
the first thing to try is relaxing a pin to upstream's own range (noted next to each pin). The Linux ffmpeg
comes from BtbN's rolling `latest` release, which is re-published daily: the script reads the release's asset
list from the GitHub API, takes the newest release branch (`ffmpeg-nX.Y-latest-linux64-gpl-X.Y.tar.xz`) and
checks the download against the size and SHA-256 listed there; if the build is replaced mid-download it reads
the list once more. `--skip-ffmpeg` or a system ffmpeg works as well.

## Licenses

`main.py` is MIT, © 2026 MekaHime Inc. (`LICENSE`). GPT-SoVITS is MIT (RVC-Boss); the pretrained models,
nltk data and ffmpeg builds keep their own licenses (`THIRD_PARTY_NOTICES.md`). Sakura's voice model,
fine-tuned weights and reference audio are MekaHime Inc. assets for personal, hobbyist use only (no
distillation, training, extraction, resale or commercial use); they are not covered by the MIT license.
