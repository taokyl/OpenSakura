# OpenSakura 🌸

Sakura is MekaHime's first prototype companion — a mood, a memory, a voice and a body —
now open source. Talk to her in a web page (mic or text) where a three.js avatar acts out
what she feels on a little countryside street, or point her at a Discord server.

Project page: https://www.mekahime.com/sakura · Source: https://github.com/zeekk0/OpenSakura ·
Support the project: https://www.mekahime.com/donate

> Sakura is MekaHime's **legacy prototype**: the harness, voice and memory stack from her Discord
> run, released as-is. She is not representative of MekaHime's newest technology.

## 18+ only

Sakura is an adult-oriented companion. At high favorability she flirts and can be sexually suggestive
(never explicit); at very low favorability she gets rude. You must be 18 or older, or the age of
majority where you live, to run her. The owner flirting can be switched off with `reply.intimacy_mode`
(Setup → Reply behaviour). The full notice is in the About tab of the page.

```
 you ──mic──▶ STT (MekaHime-modified SenseVoiceSmall, local) ──▶ Sakura brain ──▶ TTS (MekaHime build of GPT-SoVITS, local) ──▶ 🔊
                                                                  │  OpenRouter or Ollama
                                                                  │  26-emotion state · favorability · per-user memory
                                                                  └─▶ action chain ──▶ three.js VRM avatar (26 motions)
```

## What's inside

| folder | what |
|---|---|
| `sakura/` | the brain (FastAPI). `brain.py` emotion / favorability / memory + actor prompt, `llm.py` OpenRouter ⇄ Ollama per role with a cost ledger, `tts_client.py` Socket.IO client for the TTS engine, `stt_client.py`, `action_controller.py` body-action chains, `server.py` HTTP + `/ws` |
| `web/` | the page: VRM stage (`avatar.js` retargets GLB/FBX motion clips onto any VRM, `environment.js` the street), Play / Setup / State / About tabs |
| `services/stt/` | the STT service (MekaHime-modified SenseVoiceSmall) |
| `vendor/tts-engine/` | the voice server (`main.py`, a MekaHime build of GPT-SoVITS); `scripts/setup_tts.py` installs upstream GPT-SoVITS, its models and Sakura's voice next to it (see `vendor/tts-engine/README.md`) |
| `config/` | `sakura.json` persona + sensitive words, `settings.example.json` runtime settings |
| `discord/` | Discord bot mode (pending) |
| `launch.py` | starts STT + the voice server + the backend, opens the browser (`--text-only` skips the voice services) |
| `docs/` | [`OPENROUTER.md`](docs/OPENROUTER.md): key setup, roles, models, costs |

## Three ways to run her

| | brain | ears + voice | needs | cost |
|---|---|---|---|---|
| **Fully local** (100% free) | Ollama, `qwen3:8b` | on your GPU | Windows 10/11 (Linux untested), NVIDIA RTX, 16 GB VRAM recommended (8–12 GB: use a 4B model), 16 GB RAM, ~20 GB disk | electricity only (~$0.01–0.03/h) |
| **Semi-local** | OpenRouter (default `google/gemini-2.5-flash`) | on your GPU | Windows 10/11 (Linux untested), NVIDIA RTX, 6 GB VRAM, 16 GB RAM, ~15 GB disk | ~$0.003 per turn: ~$0.08/h of text chat, ~$0.31–0.36/h of continuous voice |
| **Fully online** (text only) | OpenRouter | not available | any Windows / macOS / Linux PC with Python 3.11+ and a WebGL browser, no GPU | ~$0.003 per message |

Her voice and ears need a local NVIDIA GPU; everything else runs anywhere. Measured on an RTX 5070
(12 GB), semi-local, on replies with 6–10 s of speech: speech recognition ~0.06 s, text reply ~1 s, voice
ready ~1.9 s (~2 s after you stop talking); the voice server speaks 7 s of speech in ~0.75 s using ~2.3 GB
of VRAM. Fully local is slower on that 12 GB card because the 8B model, speech recognition and her voice
share its memory: text reply ~7.6 s, voice ready ~12 s (median of 18 turns); with `qwen3:4b`, ~1.6 s and
~5 s. Costs are from real OpenRouter
billing on 2026-10-24 — see [`docs/OPENROUTER.md`](docs/OPENROUTER.md) for the key setup, model choice and
how to spend less.

## Requirements

- **Python 3.11+** for the backend (the text-only mode also runs on 3.13 / macOS). The voice server needs
  **Python 3.11 or 3.12** (on Ubuntu 22.04 install `python3.11` and `python3.11-venv`).
- Voice modes: Windows 10/11 with an NVIDIA GPU (RTX 50-series needs CUDA 12.8 wheels — the setup scripts
  install them). Linux (glibc 2.28+, e.g. Ubuntu 20.04+) and macOS 14+ on Apple Silicon with a native arm64
  Python should work the same way but are untested. ffmpeg is only needed for Opus output (WAV is the default). `scripts/setup_tts.py` builds the voice server from public sources and downloads
  Sakura's voice from the gated Hugging Face repo
  [MekaHime/MekaHime_Sakura](https://huggingface.co/MekaHime/MekaHime_Sakura): accept its
  personal-use license there and log in with `hf auth login` (or pass `--hf-token`) — `vendor/tts-engine/README.md`
- An [OpenRouter](https://openrouter.ai) key **or** [Ollama](https://ollama.com) with a model (`ollama pull qwen3:8b`)

## Quick start

```powershell
git clone https://github.com/zeekk0/OpenSakura.git && cd OpenSakura
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1   # venvs, cu128 torch, STT weights
python scripts\setup_tts.py     # the voice: GPT-SoVITS + models + Sakura's voice (~9 GB, asks for your Hugging Face login)
python launch.py --check
Start_OpenSakura.bat            # → http://localhost:8010
```

On Linux (untested so far), `python3 scripts/setup_tts.py` installs the voice the same way; the
speech-recognition service is set up by hand there (`services/stt/README.md`), or run
`python launch.py --no-stt` and type.

Text-only, on any OS (no GPU, no voice):

```bash
git clone https://github.com/zeekk0/OpenSakura.git && cd OpenSakura
python3 -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                               # put your OpenRouter key on the OPENROUTER_API_KEY= line
python launch.py --text-only                       # → http://localhost:8010
```

In the page: **Setup** → paste your OpenRouter key (or point the roles at Ollama), check the health
grid is green, pick the voice, save. **Play** → 🎙 for hands-free (voice activity detection), hold
⏺ or **Space** to push-to-talk, or type. Left-drag orbits, wheel zooms, right-drag up/down slides the
focus from her head to her shoes; the ❯ tab hides the panel.

## Modes

- **Chat in this page** (`mode: web`) — mic/text in the Play tab; replies are spoken and acted.
- **Chat in Discord** (`mode: discord`) — **not yet available.** Setup has the switch, the token field and
  the `discord` settings block, and the backend keeps the bot contract (`POST /reply`, `POST /discord/state`),
  but the bot process has not been ported to this repository. Selecting Discord mode today only disables
  the Play tab. See `discord/README.md`.

Reply behaviour toggles (Setup): speak replies, respond to typed text, respond to voice, sensitive-word
reaction, body actions, intimacy mode (18+). The toggles marked "(Discord mode, coming soon)" do nothing yet.

## How she works (short)

- **Emotion state** — 26 emotions in `[0, cap]`; the actor returns deltas scaled by relationship tier ×
  favorability; they decay over time (negatives fade 3× faster). The face shows a soft baseline of the
  mood and a full-strength pulse while she reacts/speaks.
- **Favorability + promotion** — stranger → friend → owner by message count + favorability; the web user is
  always the owner.
- **Memory** — one JSON per user under `data/memories/`; a director LLM pass every N turns rewrites notes,
  archives finished topics and leaves strategic guidance for the actor.
- **Voice** — dominant emotion + intensity → a TTS tag like `【happy2】` (S-curve, quadrant lag); synthesized in
  turn mode (one audio per reply).
- **Body** — a second LLM call picks 1–3 named motions (from a library of 26) with durations; the page plays
  them on the VRM and returns to the idle loop, plus a delayed follow-up chain. Every clip can also be played
  from the State tab.
- **Cost** — every OpenRouter call records its exact billed cost; the State tab shows session / lifetime
  totals per role (`data/usage.json`).

## Configuration

- `config/settings.json` — everything that isn't a secret (created from the example on first run; live-editable from Setup).
- `.env` — `OPENROUTER_API_KEY`, `DISCORD_BOT_TOKEN` (Setup writes these).
- `config/sakura.json` — persona and sensitive-word tiers (Setup → Persona, or by hand). A sensitive-word
  hit does not censor anything: Sakura calls the word out in character.
- Avatar: any VRM at `web/assets/avatar.vrm` (expressions `happy angry sad relaxed surprised`, visemes `aa oh`, `blink`).
  Motions: GLB (or FBX) clips listed in `web/assets/clips.json`; per-clip flags `once`, `fade`, `speed`, `clip`, `rig`,
  `hidden`, `lockXZ`. Humanoid rigs (Quaternius/UE5-mannequin, Mixamo, KayKit) are detected by bone names.

## Ports

| service | port | config key |
|---|---|---|
| OpenSakura server + page | 8010 | `server.port` |
| voice server (TTS) | 8002 | `tts.url` |
| STT service | 50000 | `stt.url` |
| Ollama | 11434 | `llm.ollama.url` |

## Notes

- The page shows a small "Support MekaHime" popup two minutes after loading and every 30 minutes; it has
  a "never show this again" option.
- The voice server sends WAV by default (`tts.audio_format`), which every browser plays; `opus` is smaller
  but Safari cannot decode Ogg/Opus.

## License

- The harness (everything in this repository written by MekaHime) — **MIT**, as authorized by MekaHime Inc. (`LICENSE`).
- STT — MekaHime-modified SenseVoiceSmall: code **MIT** (upstream SenseVoice / FunASR are MIT, see
  `services/stt/LICENSE-SenseVoice`); the small support files in `services/stt/models/` and the downloaded
  weights are under the FunASR model license.
- TTS — the OpenSakura voice server, a MekaHime build of GPT-SoVITS: code **MIT** (`vendor/tts-engine/main.py`;
  upstream GPT-SoVITS is MIT and is downloaded by `scripts/setup_tts.py` together with public models under
  their own licenses, see `vendor/tts-engine/THIRD_PARTY_NOTICES.md`).
- Sakura's voice model, fine-tuned weights and reference audio — © MekaHime Inc., **personal / hobbyist use
  only**: no distillation, training, extraction, resale or commercial use.
- Sakura's character (design, name, likeness, the VRM) — © MekaHime Inc., made with VRoid Studio. You may
  publish videos and streams with her (credit MekaHime visibly) and sell up to US$1,000 lifetime of merch
  with visible credit; beyond that write to hi@mekahime.com. Full terms: About tab → Licenses.
- Body-motion clips (`web/assets/clips/*.glb`) — **CC0 1.0**: derived from Quaternius' Universal Animation
  Library 1 and 2 and KayKit Character Animations (both CC0), plus gestures keyed by MekaHime on top of them
  and dedicated to the public domain too; sources and credits in `web/assets/clips/LICENSE.txt`.

Support the open-sourcing work: https://www.mekahime.com/donate
