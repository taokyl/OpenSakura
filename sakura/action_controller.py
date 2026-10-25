# action_controller.py - body-action control (ported from the Discord-era backend)
#
# Decides which named body animations the avatar plays for a reply
# (action chain + a delayed follow-up chain). The LLM call goes through
# llm.py so the "action" role can be OpenRouter or Ollama.
import json
import asyncio
from typing import Dict, Optional, Any

import llm
from settings import settings

# Request configuration
REQUEST_TIMEOUT = 30
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = 1.0


class ActionController:
    """Action control system"""

    def __init__(self):
        self.action_library = self._load_action_library()
        self.enabled = bool(settings.get("actions.enabled", True))
        self.followup_timer = None  # Timer for the second query
        self.current_action_chain = None  # Current action chain
        self.followup_callback = None  # Callback function for the second query
        print(f"[ACTION] Action control system initialized - Enabled: {self.enabled}")
        print(f"[ACTION] LLM provider: {llm.provider_for('action')}")
        print(f"[ACTION] Model: {llm.model_for('action')}")
        print(f"[ACTION] Action library: {len(self.action_library)} actions")

    def set_followup_callback(self, callback):
        """Set the callback function for the second query"""
        self.followup_callback = callback

    def _load_action_library(self) -> Dict[str, str]:
        """Load preset action library (names must match web/assets/clips.json).

        Looping actions repeat for whatever duration is chosen; one-shot actions
        (marked) always play to the end, so give them at least their length."""
        return {
            # Neutral / conversation
            "Waiting": "Stands relaxed, breathing; neutral resting pose, a good way to end",
            "Talk": "Talks with small hand gestures; explaining, chatting, answering",
            "Think": "Fist under her chin, other arm across her waist; thinking it over, pondering, unsure",
            "Idea": "Raises a finger beside her face; 'I've got an idea!', 'oh, I know!'",
            "LookAround": "Looks left and right; curious, searching, bored (about 5 s)",
            "Stretch": "Stretches her arms overhead; tired, relaxed, bored, waking up (one-shot, 5 s)",

            # Greetings
            "Wave": "Big friendly wave overhead; hello, goodbye, 'over here!'",
            "WaveSmall": "Small wave beside her face; a cute hi or bye-bye",
            "Bow": "Polite bow with hands together; greeting, thanks, apology (one-shot, 2.5 s)",

            # Happy / excited
            "Yay": "Throws both arms up and cheers; celebrating, very happy, 'yay!'",
            "Hop": "Hops in place with arms up; jumping for joy, can't contain excitement",
            "Dance": "Grooves side to side and pumps a fist; dancing, playful, celebrating, in a great mood",
            "Laugh": "Giggles behind her hand; laughing, amused, teasing giggle",
            "Yes": "Nods and pumps a fist; 'yes!', agreeing, determined, 'got it'",

            # Shy / sad
            "Shy": "Pokes her index fingers together, head down and turned away; shy, embarrassed, flustered",
            "Sad": "Head down, hands clasped low; sad, lonely, disappointed",
            "Cry": "Covers her eyes and sobs; crying, heartbroken, very sad",

            # Surprise / negative
            "Surprised": "Jolts back with hands up; surprised, startled, 'eh?!' (one-shot, 2.5 s)",
            "ShakeHead": "Shakes her head; no, disagreeing, refusing, 'no way'",
            "Angry": "Clenched fists in front of her, fuming; angry, frustrated, 'grr!'",
            "Pout": "Arms folded, looks away with a huff; tsundere, sulking, 'hmph!'",
            "FoldArms": "Arms folded; unimpressed, skeptical, waiting impatiently",

            # Attitude / interaction
            "HandsOnHips": "Hands on hips; confident, proud, scolding, 'listen here'",
            "LeanIn": "Leans toward you, head tilted, hands behind her back; teasing, curious, playful",
            "OpenArms": "Reaches her open arms toward you, palms up; 'come here', offering a hug, welcoming",
            "Point": "Points right at you, other hand on her hip; 'you!', 'hey, you!', calling you out",
        }

    def calculate_action_duration(self, reply_text: str, intensity: float) -> float:
        """Calculate action duration based on reply content"""
        # Base duration: based on text length
        base_duration = len(reply_text) * 0.15  # 0.15 seconds per character

        # Emotion adjustment: higher intensity emotions result in longer actions
        emotion_multiplier = 1.0 + (intensity * 0.5)
        base_duration *= emotion_multiplier

        # Special case adjustments
        if "..." in reply_text or "～" in reply_text:
            base_duration *= 1.3  # Tone words extend the action

        # Clamp to a reasonable range
        return min(max(base_duration, 2.0), 8.0)  # Clamp to 2-8 seconds

    def decide_action_count(self, reply_length: int, emotion_intensity: float) -> int:
        """Decide the number of actions"""
        if reply_length < 10:  # Short reply
            return 1
        elif reply_length < 30:  # Medium reply
            return 2 if emotion_intensity > 0.5 else 1
        else:  # Long reply
            return min(3, reply_length // 15)  # One action per 15 characters, max 3

    def need_followup_action(self, last_action: str) -> bool:
        """Determine whether a second query is needed (based on realistic girl behavior patterns)"""
        # If the last action is already a good ending action, skip
        good_ending_actions = ["Waiting", "Talk"]
        if last_action in good_ending_actions:
            return False

        # All other cases need a follow-up action (let LLM decide what to do based on emotion)
        # A real girl wouldn't stand still just because emotions are low; she'd do something that fits her current mood
        return True

    def cancel_followup_timer(self):
        """Cancel the timer for the second query"""
        if self.followup_timer:
            self.followup_timer.cancel()
            self.followup_timer = None
            print("[ACTION] Idle action countdown cancelled (new conversation started)")

    async def get_action_recommendation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get action recommendation (first query - action chain)"""
        if not self.enabled:
            return self._get_default_action_chain()

        # Cancel previous idle countdown (new conversation started)
        self.cancel_followup_timer()

        try:
            # Calculate action chain parameters
            reply_text = context.get("ai_reply", "")
            intensity = context.get("intensity", 0.5)

            action_count = self.decide_action_count(len(reply_text), intensity)
            total_duration = self.calculate_action_duration(reply_text, intensity)

            # Build action chain prompt
            prompt = self._build_action_chain_prompt(context, action_count, total_duration)

            # Call action control LLM
            response = await self._call_action_llm(prompt)

            # Parse action chain response
            action_chain = self._parse_action_chain_response(response, total_duration)

            # Save current action chain
            self.current_action_chain = action_chain

            print(f"[ACTION] Action chain: {len(action_chain.get('actions', []))} actions, total duration: {action_chain.get('total_duration', 0):.1f}s")

            # Start the timer for the second query
            self._schedule_followup_action(action_chain, context)

            return action_chain

        except Exception as e:
            print(f"[ACTION] Action chain recommendation failed: {e}")
            return self._get_default_action_chain()

    def _build_action_chain_prompt(self, context: Dict[str, Any], action_count: int, total_duration: float) -> str:
        """Build action chain control prompt"""
        user_text = context.get("user_text", "")
        ai_reply = context.get("ai_reply", "")
        emotion = context.get("emotion", "neutral")
        intensity = context.get("intensity", 0.5)
        relationship = context.get("relationship", "unknown")
        action_history = context.get("action_history", [])

        # Action history text
        action_history_text = ""
        if action_history:
            recent_actions = list(action_history)[-5:]  # Last 5 actions
            action_history_text = f"Recent actions (chronological order, oldest→newest): {', '.join(recent_actions)}"

        # Available actions list
        actions_list = "\n".join([f"- {action}: {desc}" for action, desc in self.action_library.items()])

        prompt = f"""You are a professional action direction AI responsible for recommending appropriate action sequences for a virtual character.

=== Current Situation ===
User said: "{user_text}"
AI reply: "{ai_reply}"
Current emotion: {emotion} (intensity: {intensity})
Relationship type: {relationship}
{action_history_text}

=== Action Chain Requirements ===
Generate {action_count} action(s), with a total duration of approximately {total_duration:.1f} seconds
Actions should match the AI's reply content and emotional state

=== Available Action Library ===
{actions_list}

=== Action Selection Principles ===
1. Actions must highly match the AI reply's content and emotion
2. Avoid repeating recently performed actions
3. Consider action continuity and naturalness
4. Action intensity should match emotional intensity
5. Adjust action intimacy based on relationship type
6. If the user asks her to do something an action shows (dance, wave, bow, ...) and her reply goes along with it, include that action
7. When the reply's tone (playful, apologetic, teasing) differs from the listed emotion, follow the reply

=== Output Format ===
Please strictly output in the following JSON format:
{{
  "actions": [
    {{
      "name": "action name",
      "duration": duration in seconds,
      "description": "action description"
    }}
  ],
  "total_duration": total duration,
  "reasoning": "selection reasoning"
}}

Notes:
- Action names must exactly match those in the action library
- The sum of all action durations should be close to {total_duration:.1f} seconds
- Output only JSON, no other explanations"""

        return prompt

    def _parse_action_chain_response(self, response: str, expected_duration: float) -> Dict[str, Any]:
        """Parse action chain response"""
        try:
            # Remove possible code block markers
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

            data = json.loads(response)

            # Validate format
            if "actions" not in data:
                raise ValueError("Missing 'actions' field in response")

            actions = data["actions"]
            if not isinstance(actions, list) or len(actions) == 0:
                raise ValueError("'actions' must be a non-empty array")

            # Validate each action
            total_duration = 0
            for action in actions:
                if "name" not in action or "duration" not in action:
                    raise ValueError("Action missing 'name' or 'duration' field")

                if action["name"] not in self.action_library:
                    print(f"[ACTION] Warning: Unknown action {action['name']}, replacing with Waiting")
                    action["name"] = "Waiting"

                total_duration += float(action["duration"])

            # Update total duration
            data["total_duration"] = total_duration

            return data

        except Exception as e:
            print(f"[ACTION] Action chain parsing failed: {e}, response: {response[:200]}")
            return self._get_default_action_chain()

    def _get_default_action_chain(self) -> Dict[str, Any]:
        """Get default action chain"""
        return {
            "actions": [
                {
                    "name": "Waiting",
                    "duration": 3.0,
                    "description": "Default idle action"
                }
            ],
            "total_duration": 3.0,
            "reasoning": "Using default action chain"
        }

    def _schedule_followup_action(self, action_chain: Dict[str, Any], context: Dict[str, Any]):
        """Schedule the second query (optimized: start query immediately, delay push)"""
        total_duration = action_chain.get("total_duration", 3.0)
        last_action = action_chain.get("actions", [{}])[-1].get("name", "Waiting")

        # Determine whether a second query is needed
        if not self.need_followup_action(last_action):
            print("[ACTION] No second query needed")
            return

        print(f"[ACTION] Starting second query immediately, will push results in {total_duration:.1f} seconds")

        # Start the second query immediately, but delay pushing results
        self.followup_timer = asyncio.create_task(self._parallel_followup_processing(total_duration, context))

    async def _parallel_followup_processing(self, delay: float, context: Dict[str, Any]):
        """Process second query in parallel (start query immediately, delay pushing results)"""
        try:
            # Start second query immediately
            print("[ACTION] Starting second query immediately (parallel processing)")
            followup_start_time = asyncio.get_event_loop().time()

            # Build context for the second query
            followup_context = context.copy()
            followup_context["is_followup"] = True
            followup_context["previous_actions"] = self.current_action_chain

            # Get follow-up action recommendation (start immediately)
            followup_action = await self._get_followup_action(followup_context)

            followup_duration = asyncio.get_event_loop().time() - followup_start_time
            names = [a.get("name") for a in followup_action.get("actions", [])]
            print(f"[ACTION] Second query completed ({followup_duration:.2f}s): {names}")

            # Calculate remaining wait time
            elapsed_time = asyncio.get_event_loop().time() - followup_start_time
            remaining_delay = max(0, delay - elapsed_time)

            if remaining_delay > 0:
                print(f"[ACTION] Waiting {remaining_delay:.1f}s before pushing second action")
                await asyncio.sleep(remaining_delay)
            else:
                print("[ACTION] First action chain already finished, pushing second action immediately")

            # Push follow-up action
            if self.followup_callback:
                await self.followup_callback(followup_action)
            else:
                print(f"[ACTION] Follow-up action: {followup_action} (no callback function)")

        except asyncio.CancelledError:
            print("[ACTION] Parallel second query cancelled")
        except Exception as e:
            print(f"[ACTION] Parallel second query failed: {e}")
        finally:
            self.followup_timer = None

    async def _get_followup_action(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get follow-up action chain (second query)"""
        try:
            prompt = self._build_followup_prompt(context)
            response = await self._call_action_llm(prompt)
            action_chain = self._parse_action_chain_response(response, expected_duration=4.0)

            action_names = [a.get("name", "idle") for a in action_chain.get("actions", [])]
            print(f"[ACTION] Follow-up action chain recommendation: {action_names}")
            return action_chain

        except Exception as e:
            print(f"[ACTION] Follow-up action chain recommendation failed: {e}")
            return self._get_default_followup_action_chain()

    def _get_default_followup_action_chain(self) -> Dict[str, Any]:
        """Get default follow-up action chain"""
        return {
            "actions": [
                {
                    "name": "Waiting",
                    "duration": 4.0,
                    "description": "Default idle action"
                }
            ],
            "total_duration": 4.0,
            "reasoning": "Using default follow-up action chain"
        }

    def _build_followup_prompt(self, context: Dict[str, Any]) -> str:
        """Build the second query prompt (based on realistic girl behavior patterns)"""
        previous_actions = context.get("previous_actions", {})
        emotion = context.get("emotion", "neutral")
        intensity = context.get("intensity", 0.5)
        user_text = context.get("user_text", "")
        ai_reply = context.get("ai_reply", "")

        actions_list = "\n".join([f"- {action}: {desc}" for action, desc in self.action_library.items()])

        # Generate guidance based on emotion intensity
        if intensity > 0.6:
            emotion_guidance = """High emotion state - Continue expressing and reacting:
- Continue expressing emotions: Yay, Hop, Dance, Laugh, Angry, Cry, Pout, etc.
- Shift to more focused poses: LeanIn, HandsOnHips, OpenArms, Shy, etc.
- Maintain an active state, showing emotional continuity
- Can perform more excited or serious actions"""
        elif intensity > 0.3:
            emotion_guidance = """Medium emotion state - Natural transition:
- Naturally transition from conversation pose to daily state
- Minor adjustments: WaveSmall, Yes, Think, Idea, HandsOnHips, FoldArms, etc.
- Can perform some relaxed personalized actions
- Maintain moderate activity level"""
        else:
            emotion_guidance = """Low emotion state - Return to personal activities:
- Return to personal daily activities: LookAround, Stretch, Think, FoldArms, etc.
- Show personality: perform small actions that fit the character's personality
- Natural relaxed state: Waiting is also a good choice
- Do things one would do when bored"""

        prompt = f"""The conversation has ended. Now select a follow-up action sequence.

=== Current State ===
User said: "{user_text}"
AI reply: "{ai_reply}"
Just completed action chain: {previous_actions.get('actions', [])}
Current emotion: {emotion} (intensity: {intensity})

=== Realistic Girl Behavior Guidance ===
{emotion_guidance}

=== Available Action Library ===
{actions_list}

=== Follow-up Action Chain Requirements ===
Generate 1-2 follow-up actions, total duration 3-6 seconds
Actions should reflect the character's personal state and subsequent behavior

=== Core Principles ===
1. A real girl wouldn't stand still just because emotions are low
2. She would perform natural behaviors that match her current emotional state
3. Continue expressing when emotions are high; do daily activities when emotions are low
4. Consider the character's personality traits and habits
5. Actions should be natural and fluid, fitting realistic interaction scenarios
6. Can be a single long action or a combination of multiple short actions
7. Stay in the mood of her reply above; don't switch to a different emotion

=== Output Format ===
Please strictly output in the following JSON format:
{{
  "actions": [
    {{
      "name": "action name",
      "duration": duration in seconds,
      "description": "action description"
    }}
  ],
  "total_duration": total duration,
  "reasoning": "selection reasoning (explain why these actions fit realistic girl behavior)"
}}

Notes:
- Action names must exactly match those in the action library
- Usually 1-2 actions are sufficient
- Total duration should be between 3-6 seconds
- Output only JSON, no other explanations"""

        return prompt

    async def _call_action_llm(self, prompt: str) -> str:
        """Call the action-control LLM via the shared llm door (role="action")."""
        messages = [
            {"role": "system", "content": "You are a professional action control AI. You must output in strict JSON format."},
            {"role": "user", "content": prompt},
        ]
        last_exc: Optional[Exception] = None
        for i in range(MAX_RETRIES + 1):
            try:
                return await llm.chat("action", messages, temperature=0.7, json_mode=True, timeout=REQUEST_TIMEOUT)
            except llm.LLMRejected:
                raise
            except Exception as e:  # noqa: BLE001 — retry transient provider errors
                last_exc = e
                if i < MAX_RETRIES:
                    print(f"[ACTION] LLM retry {i+1}/{MAX_RETRIES}: {e}")
                    await asyncio.sleep(RETRY_BACKOFF_SEC * (i + 1))
        raise last_exc  # type: ignore[misc]
