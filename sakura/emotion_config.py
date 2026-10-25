"""Emotion state + relationship-tiered scaling (ported from the Discord-era backend).

The live EmotionState instance lives in brain.py; this module owns the schema, decay math,
and relationship-tiered config.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict

BASE_EMOTIONS = ["happy", "sad", "angry", "fear", "surprise", "disgust"]
SCENE_EMOTIONS = [
    "jealous", "tsun", "shy", "caring", "playful", "content", "worried",
    "embarrassed", "mischievous", "relieved", "proud", "lonely", "protective",
    "annoyed", "disappointed", "frustrated", "sarcastic", "cold", "distant", "excited",
]
ALL_EMOTIONS = BASE_EMOTIONS + SCENE_EMOTIONS

# Broader "negative" set — anything Sakura should shake off faster than positives.
NEGATIVE_ALL = {
    "sad", "angry", "fear", "disgust",
    "jealous", "annoyed", "disappointed", "frustrated",
    "cold", "distant", "sarcastic",
}

# Asymmetric rates: Sakura gets hit at normal gain but sheds negatives quickly.
NEGATIVE_TIME_DECAY_MULT = 3.0   # 3× faster natural fade
NEGATIVE_DELTA_DECAY_MULT = 2.0  # 2× gain on negative deltas that reduce a negative emotion

# Relationship tier table — owner gets more headroom
TIERS = {
    "owner":    {"surge": 5.0, "max": 0.99, "decay_threshold": 0.6, "base_start": 0.10},
    "friend":   {"surge": 2.0, "max": 0.60, "decay_threshold": 0.4, "base_start": 0.05},
    "stranger": {"surge": 1.0, "max": 0.40, "decay_threshold": 0.3, "base_start": 0.02},
    "unknown":  {"surge": 1.0, "max": 0.40, "decay_threshold": 0.3, "base_start": 0.02},
}

# Decay: -DECAY_PER_SECOND per second, applied by the decay loop
DECAY_PER_SECOND = 0.02 / 60.0   # -0.02 per minute


@dataclass
class EmotionState:
    values: Dict[str, float] = field(default_factory=lambda: {e: 0.0 for e in ALL_EMOTIONS})
    last_decay: float = field(default_factory=time.time)

    def apply_decay(self, now: float | None = None) -> None:
        now = now or time.time()
        dt = max(0.0, now - self.last_decay)
        if dt <= 0:
            return
        base_shrink = DECAY_PER_SECOND * dt
        neg_shrink = base_shrink * NEGATIVE_TIME_DECAY_MULT
        for k, v in self.values.items():
            if v > 0:
                s = neg_shrink if k in NEGATIVE_ALL else base_shrink
                self.values[k] = max(0.0, v - s)
        self.last_decay = now

    def apply_deltas(self, deltas: dict, relationship: str, favorability: float) -> dict:
        """Apply deltas produced by the actor, scaled by relationship tier + favorability.
        Negative deltas on negative emotions (Sakura calming down) get 2× gain so she
        recovers faster than she flares up.
        Returns the per-emotion actual delta applied (for logging/memory)."""
        tier = TIERS.get(relationship, TIERS["unknown"])
        surge = tier["surge"] * (0.5 + favorability)
        cap = min(tier["max"], 0.3 + favorability * 0.7)
        applied = {}
        for k, raw in (deltas or {}).items():
            if k not in self.values:
                continue
            try:
                raw_f = float(raw)
            except (TypeError, ValueError):
                continue
            if raw_f < 0 and k in NEGATIVE_ALL:
                raw_f *= NEGATIVE_DELTA_DECAY_MULT
            before = self.values[k]
            target = before + raw_f * surge
            target = max(0.0, min(cap, target))
            applied[k] = target - before
            self.values[k] = target
        return applied

    def reset(self) -> None:
        for k in self.values:
            self.values[k] = 0.0
        self.last_decay = time.time()

    def peak(self, emotions: list[str] | set[str]) -> float:
        return max((self.values.get(e, 0.0) for e in emotions), default=0.0)

    def peak_arousal(self) -> float:
        arousal_set = {"happy", "excited", "playful", "mischievous", "angry", "frustrated", "surprise", "annoyed"}
        return self.peak(arousal_set)

    def snapshot(self) -> dict:
        return {"values": dict(self.values), "last_decay": self.last_decay}


def format_deltas_brief(applied: dict) -> str:
    """Render '↑happy+0.15 ↓angry-0.05' for memory logs."""
    parts = []
    for k, d in applied.items():
        if abs(d) < 0.01:
            continue
        arrow = "↑" if d > 0 else "↓"
        parts.append(f"{arrow}{k}{d:+.2f}")
    return " ".join(parts)
