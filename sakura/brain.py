"""Sakura's brain — everything in a turn that is not transport (web page or Discord).

Owns:
- persona (config/sakura.json) and per-user profiles (data/profiles.json)
- the global EmotionState + 10s decay loop + favorability drift loop
- the actor LLM call with per-user memory injection (llm.py, role="actor")
- favorability / promotion bookkeeping and the memory director trigger

Ported from the Discord-era backend. The web user is user_id 0 and is always the
owner; Discord ids listed in settings.owner.user_ids are owners too.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import favorability as fav_mod
import llm
import memory_note_taker
import memory_store
from emotion_config import EmotionState, format_deltas_brief, ALL_EMOTIONS
from settings import settings, DATA_DIR

try:
    import web_search as ws
    HAS_SEARCH = True
except Exception:  # noqa: BLE001 — ddgs is optional
    HAS_SEARCH = False

PROFILES_PATH = DATA_DIR / "profiles.json"
WEB_USER_ID = 0


# ==== persona + profiles ====
def _load_json(path: Path, default):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def is_owner(user_id: int) -> bool:
    if user_id == WEB_USER_ID:
        return True
    ids = settings.get("owner.user_ids", []) or []
    return str(user_id) in {str(i) for i in ids}


class Brain:
    def __init__(self) -> None:
        self.emotion = EmotionState()
        self.persona_cfg: dict = {}
        self.profiles: dict = {}
        self.start_time = time.time()
        self.last_activity = time.time()
        self.halted = False
        self.halt_reason: str | None = None
        self.turns = 0
        self._tasks: list[asyncio.Task] = []
        self.reload()

    def reload(self) -> None:
        self.persona_cfg = _load_json(settings.path("persona_file"), {"persona": {"name": "Sakura"}})
        self.profiles = _load_json(PROFILES_PATH, {})

    # ---- persona ----
    @property
    def persona(self) -> dict:
        return self.persona_cfg.get("persona", {})

    @property
    def name(self) -> str:
        return str(self.persona.get("name", "Sakura"))

    def persona_description(self) -> str:
        p = self.persona
        return (
            f"{p.get('name', 'Sakura')}: {p.get('description', '')}\n"
            f"Traits: {', '.join(p.get('personality_traits', []))}\n"
            f"Quirks: {', '.join(p.get('quirks', []))}\n"
            f"{p.get('base_prompt', '')}"
        )

    def save_persona(self, persona: dict) -> None:
        self.persona_cfg["persona"] = persona
        _atomic_write(settings.path("persona_file"), self.persona_cfg)

    # ---- profiles ----
    def _default_profile(self, user_id: int, display_name: str) -> dict:
        owner = is_owner(user_id)
        return {
            "display_name": display_name or (settings.get("owner.name", "Master") if owner else f"user_{user_id}"),
            "relationship": "owner" if owner else "stranger",
            "favorability": 0.95 if owner else 0.65,
            "nickname": str(settings.get("owner.name", "Master")) if owner else "",
            "first_seen": time.time(),
            "message_count": 0,
        }

    def user_profile(self, user_id: int, display_name: str = "") -> dict:
        key = str(user_id)
        prof = self.profiles.get(key)
        if prof is None:
            prof = self._default_profile(user_id, display_name)
            self.profiles[key] = prof
            self.save_profiles()
        elif display_name and prof.get("display_name") != display_name:
            prof["display_name"] = display_name
            self.save_profiles()
        return prof

    def save_profiles(self) -> None:
        _atomic_write(PROFILES_PATH, self.profiles)

    def reset_profiles(self) -> None:
        for key, prof in self.profiles.items():
            fresh = self._default_profile(int(key), prof.get("display_name", ""))
            fresh["first_seen"] = None
            prof.update(fresh)
        self.save_profiles()

    # ---- emotion helpers ----
    def dominant_emotion(self) -> tuple[str, float]:
        """(emotion, intensity) — the strongest current emotion, or neutral."""
        best, val = "neutral", 0.0
        for k, v in self.emotion.values.items():
            if v > val:
                best, val = k, v
        return (best if val >= 0.05 else "neutral"), round(val, 3)

    def emotion_state_payload(self) -> dict:
        """The `emotion_state` field of /ws reply messages: base + scene buckets."""
        vals = self.emotion.values
        base = {k: round(vals.get(k, 0.0), 3) for k in ("happy", "sad", "angry", "fear", "surprise", "disgust")}
        scene = {k: round(v, 3) for k, v in vals.items() if k not in base and v > 0.01}
        return {"base_emotions": base, "scene_emotions": scene}

    def snapshot(self) -> dict:
        emo, inten = self.dominant_emotion()
        owner = self.profiles.get(str(WEB_USER_ID)) or self._default_profile(WEB_USER_ID, "")
        return {
            "name": self.name,
            "emotions": {k: round(v, 3) for k, v in self.emotion.values.items()},
            "dominant": {"emotion": emo, "intensity": inten},
            "arousal": round(self.emotion.peak_arousal(), 3),
            "owner_profile": {k: owner.get(k) for k in ("display_name", "relationship", "favorability", "nickname", "message_count")},
            "turns": self.turns,
            "uptime_s": round(time.time() - self.start_time, 1),
            "halted": self.halted,
            "halt_reason": self.halt_reason,
        }

    def set_emotions(self, values: dict) -> None:
        for k, v in (values or {}).items():
            if k in self.emotion.values:
                try:
                    self.emotion.values[k] = max(0.0, min(0.99, float(v)))
                except (TypeError, ValueError):
                    continue

    # ---- lifecycle ----
    async def _decay_loop(self) -> None:
        while True:
            try:
                self.emotion.apply_decay()
                memory_store.prune_ignore_list_count()
            except Exception as e:  # noqa: BLE001
                print(f"[DECAY] {e!r}")
            await asyncio.sleep(10)

    async def _favorability_drift_loop(self) -> None:
        target, step = 0.5, 0.01
        while True:
            try:
                changed = False
                for prof in self.profiles.values():
                    fav = float(prof.get("favorability", target))
                    if fav > target:
                        new = max(target, round(fav - step, 4))
                    elif fav < target:
                        new = min(target, round(fav + step, 4))
                    else:
                        continue
                    if new != fav:
                        prof["favorability"] = new
                        changed = True
                if changed:
                    self.save_profiles()
            except Exception as e:  # noqa: BLE001
                print(f"[FAV-DRIFT] {e!r}")
            await asyncio.sleep(60)

    def start(self) -> None:
        if not self._tasks:
            self._tasks = [asyncio.create_task(self._decay_loop()),
                           asyncio.create_task(self._favorability_drift_loop())]

    def reset_all(self) -> None:
        memory_store.wipe_all()
        self.reset_profiles()
        self.emotion.reset()
        self.turns = 0
        self.halted = False
        self.halt_reason = None

    def unhalt(self) -> None:
        self.halted = False
        self.halt_reason = None


# ==== actor prompt ====
_ACTOR_SYSTEM_TEMPLATE = """{persona_description}

=== Current relationship with this user ===
- Display name: {display_name}
- User id: {user_id}
- Relationship: {relationship}
- Favorability: {favorability:.2f}
- Nickname (only if owner): {nickname}

=== Per-user memory about them ===
{memory_block}

{others_block}=== Your current emotional state ===
{emotion_block}

{relationship_block}{hostility_block}{intimacy_block}{addressed_block}{channel_block}=== Output format ===
Respond with a JSON object ONLY. No prose around it. Schema:
{{
  "reply": "what {name} actually says (plain text, no markdown)",
  "emotion_deltas": {{
     "<emotion_name>": <float in -1..1>,
     ...
  }},
  "emotion_target": "asker" or "third_party",
  "search": null or "search query string",
  "image_search": null or "image search query string"
}}

emotion_deltas is optional — omit it or send {{}} if nothing changes. Only include deltas for emotions that actually move. Keep each delta in roughly -0.4..+0.4.
Valid emotion names: {emotion_names}.

ABOUT 'emotion_target' (CRITICAL — affects favorability + ignore logic):
- "asker" (default) — your emotional reaction is genuinely about the user you're replying to. Their favorability moves accordingly (positive deltas help them, negative deltas hurt them).
- "third_party" — your emotions exist because the user is asking you about / mentioning / talking about someone else. The deltas still color YOUR mood, but the asker themselves did NOTHING to earn favorability change. Do NOT punish them for surfacing the topic.
- When the user IS the cause (they insulted you, complimented you, made you laugh, said something annoying), emotion_target="asker".
- When in doubt, default to "asker".

ABOUT 'search' (WEB SEARCH TOOL — AVAILABLE TO FRIENDS AND OWNERS):
- If the person is your FRIEND or OWNER and they ask you to look something up, or ask about specific events, news, products, games, people or places you are unsure about, set "search" to a concise query string. Also give a temporary "reply" like "hmm let me check~" (it will be replaced once results come back).
- Strangers never get search. Most turns need no search — set it to null.
- NEVER search for or share IP addresses, home addresses, phone numbers, real names, SSNs, passwords, bank info, or anything that could be used to dox someone. Refuse like a real person would.

ABOUT 'image_search' (IMAGE SEARCH TOOL — FRIENDS AND OWNERS ONLY):
- Set it to a descriptive query only when they explicitly ask to see / be shown / be sent a picture of something. Otherwise null.

{system_flavor_block}"""


def _format_emotion_block(state: EmotionState) -> str:
    non_zero = sorted(((k, v) for k, v in state.values.items() if v > 0.05), key=lambda kv: kv[1], reverse=True)
    if not non_zero:
        return "Calm, neutral."
    return ", ".join(f"{k}:{v:.2f}" for k, v in non_zero[:10])


def _addressed_block(addressed: Optional[bool]) -> str:
    if addressed is True:
        return ("=== This message is directed AT you ===\n"
                "They're talking to you specifically — a direct question, a ping, or a clear "
                "continuation of your ongoing exchange. Respond to them head-on.\n\n")
    if addressed is False:
        return ("=== This message is NOT directed at you ===\n"
                "They're chatting with someone else or just broadcasting to the room. You're "
                "chiming in uninvited because it caught your attention. Keep it casual and "
                "lateral — don't act like you were asked.\n\n")
    return ""


def _channel_block(channel: str) -> str:
    if channel == "voice":
        return ("=== Channel: VOICE ===\n"
                "Your reply will be spoken aloud by your voice. Keep it conversational and short "
                "(1-3 sentences), no lists, no emoji, no markdown — write how you'd actually talk.\n\n")
    if channel == "web":
        return ("=== Channel: PRIVATE CHAT ===\n"
                "You're in a one-on-one chat with this person. No markdown, keep it natural and short.\n\n")
    return ""


def _flavor_block(flavor: Optional[str]) -> str:
    if not flavor:
        return ""
    flavors = {
        "welcome": ("=== Special: WELCOME a new member ===\n"
                    "A new person just joined. React to their name in character (tease it playfully if it's funny, "
                    "be curious if it's cool). Keep it 1-3 short sentences."),
        "intro": ("=== Special: INTRO ===\n"
                  "This user just introduced themselves. React in character — ask one follow-up question, tease "
                  "something lightly, or comment on a specific thing they mentioned. Keep it short."),
        "proactive": ("=== Special: PROACTIVE ===\n"
                      "It's been quiet for a while and you felt like saying something. Ping them with a question, a "
                      "weird thought, an observation. Keep it natural and short. Don't explain why."),
        "introspect": ("=== Special: SELF-REFLECTION ===\n"
                       "They asked what you honestly think of them. Answer in your own voice from the memory and "
                       "emotional state above. No stats, no numbers; 2-4 sentences."),
    }
    if flavor.startswith("sensitive:"):
        tier = flavor.split(":", 1)[1]
        return ("=== Special: SENSITIVE WORD ===\n"
                f"This user just said a {tier}-tier word you do NOT tolerate. Roast them in character. "
                "Short, sharp, in your own voice.")
    return flavors.get(flavor, "")


@dataclass
class ReplyResult:
    reply: str
    emotion: str
    intensity: float
    applied_deltas: dict = field(default_factory=dict)
    emotion_values: dict = field(default_factory=dict)
    favorability: float = 0.65
    relationship: str = "stranger"
    message_count: int = 0
    promoted_to: Optional[str] = None
    image_url: Optional[str] = None
    emotion_target: str = "asker"
    halted: bool = False
    rejected: bool = False
    error: Optional[str] = None
    provider: str = ""
    model: str = ""
    latency_ms: int = 0


def _build_others_block(mentioned: list, profiles: dict) -> str:
    if not mentioned:
        return ""
    lines = ["=== Other people mentioned in this message ===",
             "What you know about each one is below — use it as context for your reply."]
    for m in mentioned:
        uid = int(getattr(m, "user_id", m.get("user_id") if isinstance(m, dict) else 0))
        name = getattr(m, "display_name", m.get("display_name") if isinstance(m, dict) else "") or f"user_{uid}"
        prof = profiles.get(str(uid)) or {}
        rel = prof.get("relationship", "unknown")
        fav = float(prof.get("favorability", 0.5))
        nick = prof.get("nickname", "") or ""
        memory = memory_note_taker.summarize_for_actor(uid, name)
        header = f"--- {name} (id={uid}, relationship={rel}, favorability={fav:.2f}"
        if nick:
            header += f", nickname={nick}"
        header += ") ---"
        lines += ["", header, memory if memory else f"Unknown to you. You have no prior memory of {name}."]
    return "\n".join(lines) + "\n\n"


brain = Brain()


_REPLY_RE = re.compile(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)"', re.S)


def _parse_actor(content: str) -> dict | None:
    """Strict parse first; then tolerate the common LLM glitches (doubled quotes
    around keys, trailing commas) before giving up."""
    obj = llm.parse_json(content)
    if obj is not None and isinstance(obj.get("reply"), str):
        return obj
    cleaned = re.sub(r'""(\w+)""', r'"\1"', content)          # ""emotion_deltas"" -> "emotion_deltas"
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)           # trailing commas
    obj = llm.parse_json(cleaned)
    if obj is not None and isinstance(obj.get("reply"), str):
        return obj
    return None


def _salvage_reply(content: str) -> str:
    """Pull the "reply" string out of broken JSON; else return the prose, never the braces."""
    m = _REPLY_RE.search(content or "")
    if m:
        try:
            return json.loads(f'"{m.group(1)}"')
        except json.JSONDecodeError:
            return m.group(1)
    text = re.sub(r"[{}\[\]]", " ", content or "")
    text = re.sub(r'"?(reply|emotion_deltas|emotion_target|search|image_search)"?\s*:', " ", text)
    return " ".join(text.split())[:500] or "..."


async def _call_actor(profile: dict, memory_block: str, emotion_block: str, text: str, images: list[str],
                      system_flavor: Optional[str], addressed: Optional[bool], others_block: str,
                      channel: str) -> tuple[dict, str]:
    rel = profile.get("relationship", "unknown")
    fav = float(profile.get("favorability", 0.65))
    system = _ACTOR_SYSTEM_TEMPLATE.format(
        persona_description=brain.persona_description(),
        name=brain.name,
        display_name=profile.get("display_name", ""),
        user_id=profile.get("_user_id", 0),
        relationship=rel,
        favorability=fav,
        nickname=profile.get("nickname", "") or "(none)",
        memory_block=memory_block or "(no prior memory about this user yet)",
        others_block=others_block,
        emotion_block=emotion_block,
        relationship_block=fav_mod.generate_relationship_prompt(rel, fav),
        hostility_block=fav_mod.generate_low_fav_cursing_prompt(rel, fav),
        intimacy_block=(fav_mod.generate_high_fav_flirty_prompt(rel, fav)
                        if settings.get("reply.intimacy_mode", True) else ""),
        addressed_block=_addressed_block(addressed),
        channel_block=_channel_block(channel),
        system_flavor_block=_flavor_block(system_flavor),
        emotion_names=", ".join(ALL_EMOTIONS),
    )
    user_content: list | str
    if images:
        user_content = [{"type": "text", "text": text}]
        for url in images[:4]:
            user_content.append({"type": "image_url", "image_url": {"url": url}})
    else:
        user_content = text
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_content}]

    content = await llm.chat("actor", messages, temperature=0.9, json_mode=True)
    obj = _parse_actor(content)
    if obj is None:
        # malformed JSON (doubled quotes, truncated object...) — one retry, then salvage the reply text
        print(f"[ACTOR] malformed JSON, retrying once: {content[:160]!r}")
        content = await llm.chat("actor", messages, temperature=0.7, json_mode=True)
        obj = _parse_actor(content) or {"reply": _salvage_reply(content), "emotion_deltas": {}}

    # Search tool — friends/owners only. Re-query the actor with results injected.
    search_query = obj.get("search")
    if HAS_SEARCH and isinstance(search_query, str) and search_query.strip() and rel in ("friend", "owner"):
        try:
            results = await ws.web_search(search_query.strip(), max_results=5)
            search_context = (
                f"\n=== WEB SEARCH RESULTS ===\nYou searched for: \"{search_query.strip()}\"\n\n{results}\n\n"
                "=== END SEARCH RESULTS ===\nWeave the key facts into a natural in-character reply. "
                "Set \"search\" to null this time.\n"
            )
            content2 = await llm.chat("actor", [{"role": "system", "content": system + search_context},
                                                 {"role": "user", "content": user_content}],
                                      temperature=0.9, json_mode=True)
            obj2 = llm.parse_json(content2)
            if obj2 and (obj2.get("reply") or "").strip():
                obj = obj2
        except Exception as e:  # noqa: BLE001
            print(f"[SEARCH] re-query failed: {e!r} — keeping pre-search reply")

    image_url = None
    img_query = obj.get("image_search")
    if HAS_SEARCH and isinstance(img_query, str) and img_query.strip() and rel in ("friend", "owner"):
        try:
            urls = await ws.image_search(img_query.strip(), max_results=5)
            if urls:
                image_url = random.choice(urls)
        except Exception as e:  # noqa: BLE001
            print(f"[IMAGE-SEARCH] failed: {e!r}")
    obj["_image_url"] = image_url
    return obj, system


async def reply(text: str, user_id: int = WEB_USER_ID, display_name: str = "", *, images: Optional[list[str]] = None,
                system_flavor: Optional[str] = None, addressed: Optional[bool] = None,
                mentioned_others: Optional[list] = None, channel: str = "web") -> ReplyResult:
    """One conversational turn. Applies emotion deltas, favorability, memory."""
    images = images or []
    if brain.halted:
        return ReplyResult(reply="", emotion="neutral", intensity=0.0, emotion_values=dict(brain.emotion.values),
                           halted=True, error=brain.halt_reason)
    brain.last_activity = time.time()
    profile = brain.user_profile(user_id, display_name)
    profile["_user_id"] = user_id

    memory_block = memory_note_taker.summarize_for_actor(user_id, profile.get("display_name", display_name))
    emotion_block = _format_emotion_block(brain.emotion)
    others_block = _build_others_block(mentioned_others or [], brain.profiles)

    t0 = time.perf_counter()
    try:
        obj, _ = await _call_actor(profile, memory_block, emotion_block, text, images, system_flavor,
                                   addressed, others_block, channel)
    except llm.LLMRejected as e:
        print(f"[ACTOR] rejected status={e.status} model={e.model} body={e.body[:300]!r}")
        emo, inten = brain.dominant_emotion()
        return ReplyResult(reply="", emotion=emo, intensity=inten, emotion_values=dict(brain.emotion.values),
                           favorability=float(profile.get("favorability", 0.65)),
                           relationship=profile.get("relationship", "stranger"),
                           message_count=int(profile.get("message_count", 0)), rejected=True, error=str(e)[:300])
    except Exception as e:  # noqa: BLE001
        brain.halted = True
        brain.halt_reason = f"actor LLM error: {e!r}"
        print(f"[ACTOR] failure: {e!r}")
        emo, inten = brain.dominant_emotion()
        return ReplyResult(reply="", emotion=emo, intensity=inten, emotion_values=dict(brain.emotion.values),
                           halted=True, error=str(e)[:300])
    latency_ms = int((time.perf_counter() - t0) * 1000)

    reply_text = (obj.get("reply") or "").strip()
    deltas = obj.get("emotion_deltas") or {}
    if not isinstance(deltas, dict):
        deltas = {}
    target_raw = obj.get("emotion_target")
    emotion_target = target_raw if target_raw in ("asker", "third_party") else "asker"

    applied = brain.emotion.apply_deltas(deltas, profile.get("relationship", "stranger"),
                                         float(profile.get("favorability", 0.65)))
    deltas_brief = format_deltas_brief(applied)

    promoted, new_rel = False, None
    if emotion_target == "third_party":
        profile["message_count"] = int(profile.get("message_count", 0)) + 1
        new_fav = float(profile.get("favorability", 0.65))
    else:
        old_fav, new_fav, promoted, new_rel = fav_mod.apply_fav_and_promotion(profile, applied)
        if promoted:
            print(f"[PROMOTED] {profile.get('display_name')} ({user_id}): → {new_rel}, fav reset to {new_fav:.2f}")
        elif abs(new_fav - old_fav) > 1e-4:
            print(f"[FAV] {profile.get('display_name')} ({user_id}): {old_fav:.4f} → {new_fav:.4f}")

    # Auto-ignore (Discord semantics; harmless for the web owner whose fav never gets this low)
    if not promoted and emotion_target == "asker" and new_fav < 0.03 and user_id != WEB_USER_ID:
        memory_store.ignore_user(user_id, 600)
        profile["favorability"] = 0.10
        new_fav = 0.10
        print(f"[AUTO-IGNORE] {profile.get('display_name')} ({user_id}) → 10min ignore")

    brain.save_profiles()
    brain.turns += 1

    memory_note_taker.record_turn(
        user_id=user_id, display_name=profile.get("display_name", display_name),
        relationship=profile.get("relationship", "unknown"), favorability=float(profile.get("favorability", 0.65)),
        nickname=profile.get("nickname", ""), user_msg=text, ai_reply=reply_text, emotion_deltas=deltas_brief,
    )
    asyncio.create_task(memory_note_taker.maybe_consolidate(
        user_id=user_id, consolidation_interval=int(settings.get("memory.consolidation_interval", 4)),
        persona_description=brain.persona_description(),
    ))

    emo, inten = brain.dominant_emotion()
    return ReplyResult(
        reply=reply_text, emotion=emo, intensity=inten, applied_deltas=applied,
        emotion_values={k: round(v, 3) for k, v in brain.emotion.values.items()},
        favorability=float(profile.get("favorability", 0.65)), relationship=profile.get("relationship", "stranger"),
        message_count=int(profile.get("message_count", 0)), promoted_to=new_rel if promoted else None,
        image_url=obj.get("_image_url"), emotion_target=emotion_target,
        provider=llm.provider_for("actor"), model=llm.model_for("actor"), latency_ms=latency_ms,
    )
