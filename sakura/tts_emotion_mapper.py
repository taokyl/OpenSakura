# tts_emotion_mapper.py — Maps Sakura's emotion system to TTS emotion tags
#
# Three systems working together:
#   1. S-Curve Intensity Mapping   — compresses high TTS variants
#   2. Quadrant-Based Transition Lag — prevents jarring emotion jumps
#   3. Sentence-Split Transitions  — inserts escalating emotion tags mid-text
#
# Sakura emotions (all 26) → TTS emotion tags (【emotion#】 format)

import math
import re
from typing import Dict, List, Tuple, Optional


# =====================================================================
# TTS emotion variant map
# =====================================================================
# Maps Sakura emotion name → list of TTS variants (ordered by intensity)

TTS_EMOTION_VARIANTS: Dict[str, list] = {
    # --- Base emotions ---
    "happy":       ["happy1", "happy2", "happy3"],
    "sad":         ["sad1", "sad2", "sad3"],
    "angry":       ["angry1", "angry2", "angry3", "angry4"],
    "fear":        ["worried1", "fear2", "fear3", "fear4"],  # fear1's transcript does not match its clip; worried1 as sub
    "surprise":    ["surprise1", "surprise2"],
    "disgust":     ["annoyed3", "annoyed4"],          # No direct match; high-annoyance

    # --- Scene emotions (direct matches) ---
    "jealous":     ["jealous1", "jealous2", "jealous3"],
    "tsun":        ["tsun1", "tsun2", "tsun3"],
    "shy":         ["shy1", "shy2", "shy3"],
    "caring":      ["caring1", "caring2", "caring3"],
    "playful":     ["playful1", "playful2", "playful3"],
    "worried":     ["worried1", "worried2"],
    "embarrassed": ["embarrassed1"],
    "relieved":    ["relieved1", "relieved2"],
    "proud":       ["proud1"],
    "lonely":      ["lonely1"],
    "protective":  ["protective1"],
    "annoyed":     ["annoyed1", "annoyed2", "annoyed3", "annoyed4"],
    "disappointed":["disappointed1"],
    "frustrated":  ["frustrated1"],
    "sarcastic":   ["sarcastic1"],
    "cold":        ["cold1", "cold2", "cold3"],

    # --- Scene emotions (approximate matches) ---
    "content":     ["neutral1", "caring1"],           # Calm satisfaction
    "mischievous": ["playful2", "playful3"],          # Playful with edge
    "distant":     ["monotone1", "cold1", "cold2"],   # Emotional withdrawal
    "excited":     ["happy2", "happy3"],              # High-energy happy
}

_DEFAULT_TAG = "neutral1"


# =====================================================================
# 1. S-Curve Intensity Mapping
# =====================================================================
# Sigmoid function shifted right so most emotions stay low-mid and
# you need genuinely high Sakura emotion to reach the TTS engine's top variants.

S_CURVE_STEEPNESS = 10.0    # Higher = sharper transition zone
S_CURVE_MIDPOINT  = 0.7     # Shift right = harder to reach high variants


def _s_curve(x: float) -> float:
    """Apply sigmoid mapping to compress high intensity values.

    With default params (steepness=10, midpoint=0.7):
        Sakura 0.3 → TTS ~0.02   (variant 1)
        Sakura 0.5 → TTS ~0.12   (variant 1)
        Sakura 0.7 → TTS ~0.50   (variant 2)
        Sakura 0.9 → TTS ~0.88   (variant 3)
    """
    x = max(0.0, min(1.0, x))
    k = S_CURVE_STEEPNESS
    m = S_CURVE_MIDPOINT
    raw  = 1.0 / (1.0 + math.exp(-k * (x - m)))
    low  = 1.0 / (1.0 + math.exp(-k * (0.0 - m)))
    high = 1.0 / (1.0 + math.exp(-k * (1.0 - m)))
    return (raw - low) / (high - low)


# =====================================================================
# 2. Quadrant-Based Transition Lag
# =====================================================================
# Prevents jarring voice jumps like worried3 → happy3 by introducing
# a multiplier that ramps up over multiple conversation turns.

# Quadrants: High/Low Arousal × Positive/Negative valence (HAP, HAN, LAP, LAN)
QUADRANT_HAP = {"happy", "playful", "mischievous", "protective", "tsun"}
QUADRANT_HAN = {"angry", "fear", "jealous", "embarrassed", "worried",
                "annoyed", "frustrated"}
QUADRANT_LAP = {"caring", "content", "relieved", "proud", "shy"}
QUADRANT_LAN = {"sad", "disgust", "lonely", "disappointed", "cold",
                "distant", "sarcastic"}

_EMOTION_QUADRANT: Dict[str, str] = {}
for _emo in QUADRANT_HAP: _EMOTION_QUADRANT[_emo] = "HAP"
for _emo in QUADRANT_HAN: _EMOTION_QUADRANT[_emo] = "HAN"
for _emo in QUADRANT_LAP: _EMOTION_QUADRANT[_emo] = "LAP"
for _emo in QUADRANT_LAN: _EMOTION_QUADRANT[_emo] = "LAN"

# Diagonal pairs: opposite arousal AND opposite valence
_DIAGONAL_PAIRS = {
    frozenset({"HAP", "LAN"}),
    frozenset({"HAN", "LAP"}),
}

# Lag parameters
ADJACENT_INITIAL_MULT = 0.15    # Soft lag: starts here
ADJACENT_STEP         = 0.35    # +0.35 per turn → full in ~3 turns
DIAGONAL_INITIAL_MULT = 0.0     # Hard lag: starts at 0 (forced neutral)
DIAGONAL_STEP         = 0.25    # +0.25 per turn → full in ~4 turns

# Persistent state across calls
_last_tts_quadrant: str   = ""
_transition_multiplier: float = 1.0
_transition_step: float       = 0.0


def _is_diagonal(q1: str, q2: str) -> bool:
    """Check if two quadrants are diagonally opposite."""
    return frozenset({q1, q2}) in _DIAGONAL_PAIRS


def _apply_quadrant_lag(emotion: str, raw_intensity: float) -> Tuple[float, str]:
    """Apply quadrant-based transition lag to the intensity.

    Returns (effective_intensity, lag_description) where lag_description
    is a human-readable string for logging.
    """
    global _last_tts_quadrant, _transition_multiplier, _transition_step

    emotion_lower = emotion.lower().strip()
    new_quadrant = _EMOTION_QUADRANT.get(emotion_lower, "")

    # Neutral / surprise / unknown → no quadrant, no lag, reset state
    if not new_quadrant or emotion_lower == "neutral":
        _last_tts_quadrant = ""
        _transition_multiplier = 1.0
        _transition_step = 0.0
        return raw_intensity, "none"

    lag_desc = "none"

    if new_quadrant == _last_tts_quadrant:
        # Same quadrant: advance existing transition
        if _transition_multiplier < 1.0:
            _transition_multiplier = min(1.0, _transition_multiplier + _transition_step)
            lag_desc = f"ramping {_transition_multiplier:.2f}"
        else:
            lag_desc = "none"
    elif not _last_tts_quadrant:
        # Coming from neutral/unknown → no lag
        _transition_multiplier = 1.0
        _transition_step = 0.0
        lag_desc = "none"
    elif _is_diagonal(_last_tts_quadrant, new_quadrant):
        # Diagonal jump → hard lag (force neutral first)
        _transition_multiplier = DIAGONAL_INITIAL_MULT
        _transition_step = DIAGONAL_STEP
        lag_desc = f"DIAGONAL {_last_tts_quadrant}->{new_quadrant} mult=0.00"
    else:
        # Adjacent jump → soft lag (start at variant 1)
        _transition_multiplier = ADJACENT_INITIAL_MULT
        _transition_step = ADJACENT_STEP
        lag_desc = f"ADJACENT {_last_tts_quadrant}->{new_quadrant} mult=0.15"

    _last_tts_quadrant = new_quadrant

    effective = raw_intensity * _transition_multiplier
    return effective, lag_desc


# =====================================================================
# 3. Emotion State Progression
# =====================================================================
# Linear progression through discrete states. For N variants, there are
# 2*N+1 states evenly distributed across the 0-1 intensity range:
#
#   4 variants (angry1-4) → 9 states:
#     neutral → neutral+e1 → e1 → e1+e2 → e2 → e2+e3 → e3 → e3+e4 → e4
#
#   1 variant (proud1) → 3 states:
#     neutral → neutral+e1 → e1
#
# Transition states (split) use two neighboring tags.
# Pure states use a single tag.
# Maximum 2 tags per output. Never more.

MIN_SPLIT_LENGTH = 30     # Don't split text shorter than this

# Break patterns: (regex, priority_bonus)
# Sentence boundaries get a bonus so they're preferred over clause boundaries
_SENTENCE_BREAKS = re.compile(r'(?<=[.!?])\s+')
_CLAUSE_BREAKS   = re.compile(r'(?<=[,;])\s+|(?<=\s)--\s+')


def _find_split_point(text: str) -> Optional[int]:
    """Find the best split point in text, biased toward the center.

    Returns the character index to split at, or None if no good split found.
    The split point is AFTER the punctuation + space (start of second half).
    """
    if len(text) < MIN_SPLIT_LENGTH:
        return None

    center = len(text) / 2.0
    candidates: List[Tuple[float, int]] = []  # (score, position)

    # Find all sentence boundaries
    for m in _SENTENCE_BREAKS.finditer(text):
        pos = m.end()
        # Gaussian weight centered at 50% of text length
        dist = abs(pos - center) / len(text)
        score = math.exp(-(dist * 4.0) ** 2) * 2.0  # 2x bonus for sentence breaks
        candidates.append((score, pos))

    # Find all clause boundaries
    for m in _CLAUSE_BREAKS.finditer(text):
        pos = m.end()
        dist = abs(pos - center) / len(text)
        score = math.exp(-(dist * 4.0) ** 2) * 1.0  # 1x for clause breaks
        candidates.append((score, pos))

    if not candidates:
        return None

    # Pick the highest-scored candidate
    candidates.sort(key=lambda c: c[0], reverse=True)
    best_pos = candidates[0][1]

    # Ensure neither half is too short (at least 10 chars each)
    if best_pos < 10 or (len(text) - best_pos) < 10:
        return None

    return best_pos


def _get_emotion_state(variants: list, s_curved: float) -> Tuple[str, Optional[str]]:
    """Determine the emotion state from S-curved intensity.

    For N variants, there are 2*N+1 states:
        State 0:     neutral              (pure)
        State 1:     neutral + v[0]       (transition)
        State 2:     v[0]                 (pure)
        State 3:     v[0] + v[1]          (transition)
        ...
        State 2N:    v[N-1]               (pure)

    Returns (tag1, tag2) where tag2 is None for pure states.
    """
    n = len(variants)
    total_states = 2 * n + 1
    state_idx = int(s_curved * total_states)
    state_idx = min(state_idx, total_states - 1)

    if state_idx == 0:
        # Pure neutral
        return (_DEFAULT_TAG, None)
    elif state_idx % 2 == 1:
        # Transition state (split): lower + upper neighboring tags
        vi = (state_idx - 1) // 2   # index of the upper variant
        lower = _DEFAULT_TAG if vi == 0 else variants[vi - 1]
        upper = variants[vi]
        return (lower, upper)
    else:
        # Pure emotion state (single tag)
        vi = state_idx // 2 - 1
        return (variants[vi], None)


# =====================================================================
# Text Formatter (pre-processing before the TTS engine)
# =====================================================================
# All text is lowercased and word replacements are applied before
# being sent to the TTS engine. Emotion tags (【...】) are NOT affected.

_WORD_REPLACEMENTS: Dict[str, str] = {
    "Yumekami": "ゆめかみ",
    "yumekami": "ゆめかみ",
    "Sakura": "さくら",
    "sakura": "さくら",
    "Master": "ごしゅじんさま",
    "master": "ごしゅじんさま",
    # Family terms (applied before lowercasing, so include both cases)
    "Grandmother": "おばあちゃん",
    "grandmother": "おばあちゃん",
    "Grandfather": "おじいちゃん",
    "grandfather": "おじいちゃん",
    "Grandma": "おばあちゃん",
    "grandma": "おばあちゃん",
    "Grandpa": "おじいちゃん",
    "grandpa": "おじいちゃん",
    "Mother": "おかあさん",
    "mother": "おかあさん",
    "Father": "おとうさん",
    "father": "おとうさん",
    "Mom": "おかあさん",
    "mom": "おかあさん",
    "Dad": "おとうさん",
    "dad": "おとうさん",
    "Big sister": "おねえちゃん",
    "big sister": "おねえちゃん",
    "Big brother": "おにいちゃん",
    "big brother": "おにいちゃん",
    "Little sister": "いもうと",
    "little sister": "いもうと",
    "Little brother": "おとうと",
    "little brother": "おとうと",
    "Sister": "おねえちゃん",
    "sister": "おねえちゃん",
    "Brother": "おにいちゃん",
    "brother": "おにいちゃん",
    "Daughter": "むすめ",
    "daughter": "むすめ",
    "Mochi": "もち",
    "mochi": "もち",
    "Uncle": "おじさん",
    "uncle": "おじさん",
    "Aunt": "おばさん",
    "aunt": "おばさん",
    "Wife": "おくさん",
    "wife": "おくさん",
    "Husband": "だんなさま",
    "husband": "だんなさま",
    "Family": "かぞく",
    "family": "かぞく",
    # Common expressions → Japanese
    "Good morning": "おはようございます",
    "good morning": "おはようございます",
    "Good night": "おやすみなさい",
    "good night": "おやすみなさい",
    "Thank you": "ありがとうございます",
    "thank you": "ありがとうございます",
    "Sorry": "ごめんなさい",
    "sorry": "ごめんなさい",
    "Amazing": "すごい",
    "amazing": "すごい",
    "Pervert": "へんたい",
    "pervert": "へんたい",
    "Idiot": "ばか",
    "idiot": "ばか",
    "Cute": "かわいい",
    "cute": "かわいい",
    "Spirit": "たましい",
    "spirit": "たましい",
    "Hmph": "ふん",
    "hmph": "ふん",
}

# Japanese honorific suffixes → actual hiragana so the TTS engine pronounces them correctly.
# Applied after lowercasing, matched case-insensitively via the lowered text.
_HONORIFIC_REPLACEMENTS: List[Tuple[str, str]] = [
    ("-sama", "さま"),
    ("-san",  "さん"),
    ("-chan", "ちゃん"),
    ("-kun",  "くん"),
    ("-tan",  "たん"),
    ("-dono", "どの"),
    ("-senpai", "せんぱい"),
    ("-sensei", "せんせい"),
    ("-nee",  "ねえ"),
    ("-nii",  "にい"),
]


def _format_text_for_tts(text: str) -> str:
    """Lowercase all text, apply word replacements and honorific
    conversions for the TTS engine."""
    # Apply specific word replacements first (case-sensitive, before lowering)
    for old, new in _WORD_REPLACEMENTS.items():
        text = text.replace(old, new)

    # Lowercase everything
    text = text.lower()

    # Convert "haha" chains to 哈 chains for the TTS engine pronunciation
    # "haha" → "哈哈", "hahaha" → "哈哈哈", "hahahaha" → "哈哈哈哈", etc.
    # A lone "ha" that isn't part of "haha" is left untouched.
    text = re.sub(r'\bhaha(ha)*\b', lambda m: '哈' * (len(m.group(0)) // 2), text)

    # Replace Japanese honorific suffixes with hiragana
    for romaji, hiragana in _HONORIFIC_REPLACEMENTS:
        text = text.replace(romaji, hiragana)

    return text


# =====================================================================
# Public API
# =====================================================================

def format_tts_message(text: str, emotion: str, intensity: float) -> str:
    """Format a message for the TTS engine with the full pipeline:
    quadrant lag → S-curve → emotion state progression.

    State progression for N variants (2*N+1 discrete states):
        neutral → neutral+e1 → e1 → e1+e2 → e2 → ... → eN

    Returns formatted string like:
        Pure:       "【happy1】full text here"
        Transition: "【neutral1】first half. 【happy1】second half!"
    """
    emotion_lower = emotion.lower().strip()

    # --- Step 0: Text formatting for the TTS engine ---
    text = _format_text_for_tts(text)

    # --- Step 1: Quadrant lag ---
    effective_intensity, _ = _apply_quadrant_lag(emotion_lower, intensity)

    # --- Step 2: Forced neutral (multiplier = 0) ---
    if effective_intensity <= 0.0:
        return f"【{_DEFAULT_TAG}】{text}"

    # --- Step 3: Resolve variants ---
    variants = TTS_EMOTION_VARIANTS.get(emotion_lower)
    if not variants or emotion_lower == "neutral":
        return f"【{_DEFAULT_TAG}】{text}"

    # --- Step 4: S-curve the effective intensity ---
    s_curved = _s_curve(effective_intensity)

    # --- Step 5: Emotion state progression ---
    tag1, tag2 = _get_emotion_state(variants, s_curved)

    if tag2 is None:
        # Pure state: single tag
        return f"【{tag1}】{text}"

    # Transition state: try to split the text
    if len(text) < MIN_SPLIT_LENGTH:
        # Text too short to split → use the higher variant
        return f"【{tag2}】{text}"

    split_pos = _find_split_point(text)
    if split_pos is None:
        # No natural break found → use the higher variant
        return f"【{tag2}】{text}"

    part1 = text[:split_pos].rstrip()
    part2 = text[split_pos:].lstrip()
    return f"【{tag1}】{part1} 【{tag2}】{part2}"
