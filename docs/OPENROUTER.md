# Using OpenRouter with OpenSakura

OpenSakura can run Sakura's brain on [OpenRouter](https://openrouter.ai) or on a local
[Ollama](https://ollama.com) model. OpenRouter is the easy, no-GPU option: one API key gives you
access to many models, you pay per request, and Sakura shows you the exact billed cost of every
call in the **State** tab.

This guide takes about five minutes.

## 1. Get a key

1. Create an account at <https://openrouter.ai>.
2. Add credits at <https://openrouter.ai/settings/credits>. $5 is plenty to start: with the default
   model it is roughly 1,500 conversation turns.
3. Create a key at <https://openrouter.ai/settings/keys>. Give it a name (for example `OpenSakura`)
   and set a **credit limit** on the key. The limit is your safety net: if the key is ever leaked,
   it cannot spend more than that.
4. Copy the key. It starts with `sk-or-v1-`. You will not be able to see it again on the site, so
   keep it somewhere safe.

## 2. Give the key to Sakura

Either way below works. The key is stored only in the `.env` file next to `launch.py`, which is
ignored by git and never leaves your PC.

**From the page (recommended)**

1. Start OpenSakura (`Start_OpenSakura.bat` or `python launch.py`) and open <http://localhost:8010>.
2. Open the **Setup** tab, paste the key into the **OpenRouter** field and press **Save**.
3. **Health** should now show the OpenRouter line as OK, with the key's label, how much it has
   used and its limit. No restart is needed.

**By hand**

1. Copy `.env.example` to `.env`.
2. Put the key on the `OPENROUTER_API_KEY=` line.
3. Start OpenSakura. `python launch.py --check` prints `OPENROUTER_API_KEY  set` when it is picked up.

## 3. Choose which roles use OpenRouter

Sakura is not one prompt. Each turn uses up to four "roles", and every role can point at
OpenRouter or Ollama independently (Setup tab → **LLM**, or `config/settings.json` → `llm.roles`):

| Role | What it does | Called |
|---|---|---|
| `actor` | writes her reply, picks her emotion and voice tag | every turn |
| `action` | chooses the body motions she plays while speaking | every turn (one or two calls) |
| `director` | writes her memory notes about you | every few turns |
| `mod` | the optional safety filter on her replies | only when `reply.safety_filter` is on |

The default is everything on OpenRouter with `google/gemini-2.5-flash`. Good cheap alternatives:

- **Semi-local:** `actor` on OpenRouter (quality where it matters), `action` and `director` on
  Ollama. This cuts the OpenRouter bill by roughly two thirds, because the action chain is the
  biggest token user.
- **Fully local:** every role on Ollama (`ollama pull qwen3:8b`). No OpenRouter key needed.

## 4. Pick models

Model ids are OpenRouter ids such as `google/gemini-2.5-flash`. They live in Setup → LLM or in
`config/settings.json`:

```json
"llm": {
  "roles": {"actor": "openrouter", "director": "ollama", "action": "ollama", "mod": "openrouter"},
  "openrouter": {
    "actor_model": "google/gemini-2.5-flash",
    "director_model": "google/gemini-2.5-flash",
    "action_model": "google/gemini-2.5-flash",
    "mod_model": "google/gemini-2.5-flash"
  }
}
```

Things to know when choosing:

- Sakura asks the model for **JSON** (`response_format: json_object`). Mainstream models from
  Google, OpenAI, Anthropic, DeepSeek and Meta handle this. Very small or "free" models sometimes
  return broken JSON; Sakura retries once and salvages what it can, but her replies get worse.
- The `actor` model decides her personality. Try a few: a model that is great at code is not
  always the one that is best at being Sakura.
- Browse ids and prices at <https://openrouter.ai/models>. Prices change; what matters most for
  Sakura is the **output** price, because most of her cost is the text the models write.

## 5. What it costs

Measured on 2026-10-24 with everything on `google/gemini-2.5-flash`:

| | |
|---|---|
| one conversation turn | about 4,350 tokens, about **$0.003** |
| casual text chat (25 turns/hour) | about $0.08 per hour |
| chatty text (50 turns/hour) | about $0.09 to $0.18 per hour |
| continuous voice conversation (100 turns/hour) | about $0.31 to $0.36 per hour |
| semi-local (only `actor` on OpenRouter), voice | about $0.08 to $0.12 per hour |

The **State** tab has a **Cost** card with the session and lifetime totals, split by role, and a
reset button. Every OpenRouter call records its exact billed cost; Ollama calls are counted as $0.

Ways to spend less, in order of effect:

1. Move `action` and `director` to Ollama (see above).
2. Use a cheaper model for `action` and `mod`; they only need to return small JSON.
3. Raise `memory.consolidation_interval` so the memory director runs less often.
4. Set the credit limit on the key so a runaway session cannot surprise you.

## 6. Privacy

When a role runs on OpenRouter, that role's prompt leaves your PC: your message, her persona, the
recent conversation and the memory notes that are relevant to it. OpenRouter forwards it to the
model's provider. Review and restrict which providers may see your data at
<https://openrouter.ai/settings/privacy> (you can exclude providers that train on prompts).

Everything else stays on your PC: her voice, speech recognition, the memory files and profiles in
`data/`, and the cost ledger. With every role on Ollama, nothing leaves your PC at all.

## Troubleshooting

| Message | Meaning | Fix |
|---|---|---|
| `OPENROUTER_API_KEY is not set` | no key in `.env` and none saved from Setup | step 2 |
| Health shows OpenRouter `401` | the key is wrong or was revoked | make a new key |
| `402` / "insufficient credits" | the key's limit or your balance is used up | add credits or raise the key limit |
| `429` | rate limited, common on `:free` models | pick a paid model or wait |
| she answers with a bare `{` or stays silent | the model returned broken JSON | use a larger model for `actor` |
| very slow replies | the chosen model or provider is slow right now | switch model; OpenRouter routes around outages but not always quickly |

Logs are in `logs/`; the backend prints every LLM call with its role, provider, model and cost.
