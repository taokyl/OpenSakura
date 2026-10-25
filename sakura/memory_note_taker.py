"""Per-user memory director.

Each user gets their own counter and their own director pass. The director
sees only that user's past notes/events/topics and their own recent turns.
No cross-user leak. The LLM call goes through llm.py (role="director").
"""
from __future__ import annotations

import json
import time

import llm
from memory_store import load_user, save_user, format_turn_line

RELATIONSHIP_STRATEGY = {
    "owner": "Build a deep bond with them. Be clingy, playful, seek attention. Show your own needs — you're not a service.",
    "friend": "Warm but independent. Share opinions, tease, maintain distance.",
    "stranger": "Polite but cool. Short replies. Watch for weirdness.",
    "unknown": "Observe first, minimal investment.",
}

DIRECTOR_PROMPT = """You are Sakura's memory director for a single user. Your job:
1. Maintain continuous per-user memory using "inherit notes + archive completed events."
2. Provide Sakura with a short strategic guidance block for this user.

=== Persona ===
{persona_description}

=== This user ===
- Display name: {display_name}
- User id: {user_id}
- Relationship: {relationship} (strategy: {relationship_strategy})
- Favorability: {favorability}
- Nickname (only if relationship is owner): {nickname}

=== Previous notes about THIS user ===
{previous_notes}

=== Previously flagged ongoing topics ===
{previous_ongoing_topics}

=== Previous strategic guidance ===
{previous_guidance}

=== New turns with THIS user (turns {start_turn}-{end_turn}) ===
{new_turns}

Turn format: [N] {{displayname}}(ID:{{id}})→{{relationship}}(♥{{fav}})[{{nickname}}]: user_msg | AI: ai_reply [emotion deltas]

Rules:
- notes: journal-style, first person from Sakura's POV. Do NOT start with time words ("Today...", "Just now..."); the system prepends time.
- completed_events: topics from previous notes that did NOT recur this batch → archive as a 3-5 sentence first-person blurb.
- ongoing_topics: list of short strings reminding yourself of unresolved threads with this user.
- strategic_guidance: object with keys: relationship_read, emotional_dynamics, user_needs, sakura_needs, risks, next_focus, proactive_topics (list of 2-3 short hook ideas Sakura could raise later if the mood fits).
- Output JSON ONLY, matching:
  {{
    "new_notes": "...",
    "completed_events": ["...", ...],
    "ongoing_topics": ["...", ...],
    "strategic_guidance": {{ ... }}
  }}
"""


async def call_director(persona_description: str, mem: dict, new_turns_text: str,
                        start_turn: int, end_turn: int) -> dict | None:
    prompt = DIRECTOR_PROMPT.format(
        persona_description=persona_description,
        display_name=mem.get("display_name_last_seen") or f"user_{mem['user_id']}",
        user_id=mem["user_id"],
        relationship=mem.get("relationship", "unknown"),
        relationship_strategy=RELATIONSHIP_STRATEGY.get(mem.get("relationship", "unknown"), ""),
        favorability=mem.get("favorability", 0.65),
        nickname=mem.get("nickname", "") or "(none)",
        previous_notes=mem.get("current_notes") or "(no prior notes)",
        previous_ongoing_topics=json.dumps(mem.get("ongoing_topics", []), ensure_ascii=False),
        previous_guidance=json.dumps(mem.get("strategic_guidance", {}), ensure_ascii=False),
        start_turn=start_turn,
        end_turn=end_turn,
        new_turns=new_turns_text,
    )
    try:
        return await llm.chat_json("director", [{"role": "user", "content": prompt}], temperature=0.4, timeout=60)
    except Exception as e:  # noqa: BLE001 — memory is best-effort; never take the actor down
        print(f"[MEMORY] director call failed for user {mem['user_id']}: {e}")
        return None


def record_turn(user_id: int, display_name: str, relationship: str, favorability: float,
                nickname: str, user_msg: str, ai_reply: str, emotion_deltas: str = "") -> dict:
    """Append a single turn to this user's recent_turns buffer. Returns updated mem."""
    mem = load_user(user_id, display_name)
    mem["display_name_last_seen"] = display_name or mem.get("display_name_last_seen", "")
    mem["relationship"] = relationship or mem.get("relationship", "unknown")
    mem["favorability"] = favorability if favorability is not None else mem.get("favorability", 0.65)
    if nickname:
        mem["nickname"] = nickname
    mem["total_turns"] = mem.get("total_turns", 0) + 1

    buf = mem.setdefault("_recent_turns_buffer", [])
    line = format_turn_line(mem["total_turns"], display_name, user_id, mem["relationship"],
                            mem["favorability"], mem.get("nickname", ""), user_msg, ai_reply, emotion_deltas)
    buf.append({"turn": mem["total_turns"], "line": line, "ts": time.time()})
    save_user(mem)
    return mem


async def maybe_consolidate(user_id: int, consolidation_interval: int, persona_description: str) -> bool:
    """If this user's buffer has >= consolidation_interval turns, run the director.
    Returns True if director actually ran and memory was updated.
    """
    mem = load_user(user_id)
    buf = mem.get("_recent_turns_buffer", [])
    if len(buf) < consolidation_interval:
        return False

    start_turn = buf[0]["turn"]
    end_turn = buf[-1]["turn"]
    new_turns_text = "\n".join(b["line"] for b in buf)

    result = await call_director(persona_description, mem, new_turns_text, start_turn, end_turn)
    if result is None:
        return False

    if result.get("new_notes"):
        existing = mem.get("current_notes", "")
        if existing:
            mem.setdefault("notes_history", []).append({"ts": time.time(), "notes": existing})
        mem["current_notes"] = result["new_notes"]

    completed = result.get("completed_events") or []
    if completed:
        mem.setdefault("completed_events", []).extend(
            [{"ts": time.time(), "event": e} for e in completed if isinstance(e, str) and e.strip()]
        )

    mem["ongoing_topics"] = result.get("ongoing_topics") or []
    mem["strategic_guidance"] = result.get("strategic_guidance") or {}
    mem["_recent_turns_buffer"] = []
    save_user(mem)
    return True


def summarize_for_actor(user_id: int, display_name: str) -> str:
    """Build a compact memory block to inject into the actor's system prompt for this user."""
    mem = load_user(user_id, display_name)
    parts = []
    if mem.get("current_notes"):
        parts.append(f"[Your memory about {display_name}]: {mem['current_notes']}")
    topics = mem.get("ongoing_topics") or []
    if topics:
        parts.append("[Unresolved threads]: " + "; ".join(topics))
    guidance = mem.get("strategic_guidance") or {}
    if guidance:
        compact = ", ".join(f"{k}={v}" for k, v in guidance.items() if isinstance(v, str))
        if compact:
            parts.append(f"[Strategic read]: {compact}")
    events = mem.get("completed_events") or []
    if events:
        last = events[-3:]
        parts.append("[Past events]: " + " / ".join(e.get("event", "") if isinstance(e, dict) else str(e) for e in last))
    return "\n".join(parts)
