"""Per-user isolated memory file store.

One JSON per user id under data/memories/users/{id}.json.
memories/index.json is a cross-user index {user_id: {display_name, last_seen, turn_count}}.

Atomic writes via tempfile + rename.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from settings import DATA_DIR

ROOT = DATA_DIR / "memories"
USERS_DIR = ROOT / "users"
INDEX_PATH = ROOT / "index.json"
IGNORE_PATH = ROOT / "ignore_list.json"


def _empty_user_memory(user_id: int, display_name: str = "") -> dict:
    return {
        "user_id": user_id,
        "display_name_last_seen": display_name,
        "relationship": "unknown",
        "favorability": 0.65,
        "nickname": "",
        "current_notes": "",
        "notes_history": [],
        "completed_events": [],
        "ongoing_topics": [],
        "strategic_guidance": {},
        "total_turns": 0,
        "last_updated": None,
    }


def _atomic_write(path: Path, data: Any) -> None:
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


def user_path(user_id: int) -> Path:
    return USERS_DIR / f"{user_id}.json"


def load_user(user_id: int, display_name: str = "") -> dict:
    p = user_path(user_id)
    if not p.exists():
        return _empty_user_memory(user_id, display_name)
    try:
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        if display_name and data.get("display_name_last_seen") != display_name:
            data["display_name_last_seen"] = display_name
        return data
    except (OSError, json.JSONDecodeError):
        return _empty_user_memory(user_id, display_name)


def save_user(mem: dict) -> None:
    mem["last_updated"] = time.time()
    _atomic_write(user_path(mem["user_id"]), mem)
    _touch_index(mem["user_id"], mem.get("display_name_last_seen", ""), mem.get("total_turns", 0))


def load_index() -> dict:
    if not INDEX_PATH.exists():
        return {}
    try:
        with INDEX_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_index(idx: dict) -> None:
    _atomic_write(INDEX_PATH, idx)


def _touch_index(user_id: int, display_name: str, turn_count: int) -> None:
    idx = load_index()
    idx[str(user_id)] = {
        "display_name": display_name,
        "last_seen": time.time(),
        "turn_count": turn_count,
    }
    save_index(idx)


def load_ignore_list() -> dict:
    if not IGNORE_PATH.exists():
        return {}
    try:
        with IGNORE_PATH.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def save_ignore_list(data: dict) -> None:
    _atomic_write(IGNORE_PATH, data)


def prune_ignore_list_count() -> int:
    """Drop expired ignore-list entries from disk; return how many were removed.
    Called every 10 s by brain.py's decay loop; writes nothing when nothing expired."""
    data = load_ignore_list()
    now = time.time()
    expired = [uid for uid, until in data.items() if now >= float(until)]
    if not expired:
        return 0
    for uid in expired:
        data.pop(uid, None)
    save_ignore_list(data)
    return len(expired)


def ignore_user(user_id: int, seconds: float) -> float:
    data = load_ignore_list()
    until = time.time() + seconds
    data[str(user_id)] = until
    save_ignore_list(data)
    return until


def wipe_all() -> None:
    """Setup → Danger → wipe: remove all per-user files, clear the index and the ignore list."""
    if USERS_DIR.exists():
        for p in USERS_DIR.glob("*.json"):
            try:
                p.unlink()
            except OSError:
                pass
    save_index({})
    save_ignore_list({})


def format_turn_line(turn_num: int, display_name: str, user_id: int, relationship: str,
                     favorability: float, nickname: str, user_msg: str, ai_reply: str,
                     emotion_deltas: str = "") -> str:
    rel_zh = {"owner": "主人", "friend": "朋友", "stranger": "陌生人", "unknown": "未知"}.get(relationship, relationship)
    nick_part = f"[{nickname}]" if nickname else ""
    return (
        f"[{turn_num}] {display_name}(ID:{user_id})→{rel_zh}(♥{favorability:.2f}){nick_part}: "
        f"{user_msg} | AI: {ai_reply}{(' ' + emotion_deltas) if emotion_deltas else ''}"
    )
