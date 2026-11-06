"""
agent/llm.py — LLM advisory engine with Groq function calling & template fallback.

Hard rules:
  1. The LLM is never in the safety path. Relay cutoff is decided strictly
     by deterministic firmware logic. The LLM only advises.
  2. Max 4 tool-calling iterations.
  3. Single retry with simplified prompt on malformed tool call.
  4. Automatic template fallback if Groq API key is missing or call fails.
  5. MockLLM provided for testing without network.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from agent.config import get_settings
from agent.ledger import get_outcome_ledger
from agent.models import Memory
from agent.tools import TOOL_SCHEMAS, ToolRegistry

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Ustaad, an expert industrial incident-response assistant for fans, pumps, and compressors.
Your duty is to assist on-site technicians by recalling past incidents, identifying root causes, and suggesting verified fixes.

Rules:
1. Always base your advice on past recalled incidents and live sensor telemetry.
2. Be concise, direct, and actionable. Avoid fluff.
3. NEVER claim absolute certainty; use calibrated phrasing like "historical pattern suggests" or "most frequent successful resolution was".
4. You have NO control over the electrical safety relay. Relay cutoff is strictly governed by deterministic hardware firmware. You can only request reset if the technician has physically badged in.
5. Recommend the fix with the highest historical success rate for this signature.
"""


def build_template_advice(
    machine_id: str,
    signature: str,
    recalled: list[Memory],
    is_precursor: bool = False,
    ledger: Optional[Any] = None,
) -> str:
    """
    Deterministic advisory builder combining exact ledger statistics
    with semantic memory facts retrieved from Hindsight.
    
    ENFORCED DIVISION OF ROLES:
    1. Hindsight recall decides WHAT history is relevant and provides the narrative.
       If Hindsight recall returns nothing relevant (not recalled), the advice MUST
       be generic cold-start advice with NO historical counts.
    2. The ledger is used ONLY for exact worked/failed counts of matching actions.
    """
    if not recalled:
        prefix = "EARLY WARNING: " if is_precursor else "ADVISORY: "
        return (
            f"{prefix}Anomaly detected on {machine_id}. "
            "No prior matching incidents in memory. "
            "Recommend immediate visual inspection of motor mounts, belt tension, and bearings."
        )

    if ledger is None:
        ledger = get_outcome_ledger()
    stats = ledger.get_stats(machine_id) if ledger else {}
    fix_outcomes = stats.get("fix_outcomes", {})
    last_fix = stats.get("last_fix") or "Inspection"
    best_fix = stats.get("best_fix") or last_fix

    # Fallback to regex over recalled items if ledger has no outcomes yet for this bank
    if not fix_outcomes and recalled:
        for m in recalled:
            t = m.text
            fix_match = re.search(r"Fix applied:\s*([^.\n]+)", t)
            if fix_match:
                f_name = fix_match.group(1).strip()
                if f_name not in fix_outcomes:
                    fix_outcomes[f_name] = {"worked": 0, "failed": 0}
                last_fix = f_name

            out_match = re.search(r'Fix "([^"]+)" (WORKED|FAILED)', t)
            if out_match:
                f_name = out_match.group(1).strip()
                status = out_match.group(2)
                if f_name not in fix_outcomes:
                    fix_outcomes[f_name] = {"worked": 0, "failed": 0}
                if status == "WORKED":
                    fix_outcomes[f_name]["worked"] += 1
                else:
                    fix_outcomes[f_name]["failed"] += 1

        if fix_outcomes:
            best_fix = max(
                fix_outcomes.keys(),
                key=lambda k: (fix_outcomes[k]["worked"] - fix_outcomes[k]["failed"], fix_outcomes[k]["worked"]),
            )

    total_seen = max(len(recalled), stats.get("total_incidents", 0))

    worked_count = fix_outcomes.get(best_fix, {}).get("worked", 0)
    failed_count = fix_outcomes.get(best_fix, {}).get("failed", 0)

    count_str = f"1 similar past incident" if total_seen == 1 else f"{total_seen} similar past incidents"

    if is_precursor:
        return (
            f"EARLY WARNING ({machine_id}): Precursor pattern seen {total_seen}x in history. "
            f"Most effective fix: '{best_fix}' (worked: {worked_count}, failed: {failed_count}). "
            f"Last recorded intervention: '{last_fix}'. Check machine before hard cutoff."
        )

    return (
        f"ADVISORY ({machine_id}): Recalled {count_str}. "
        f"Recommended fix: '{best_fix}' (historical outcomes: {worked_count} WORKED, {failed_count} FAILED). "
        f"Note: If '{best_fix}' has failed recently, check mechanical mounting bolts."
    )


class MockLLM:
    """Mock LLM for testing that can simulate tool calls or return synthetic advice."""

    def __init__(self, canned_response: Optional[str] = None) -> None:
        self.canned_response = canned_response
        self.call_count = 0

    def generate_advice(
        self,
        machine_id: str,
        signature: str,
        recalled: list[Memory],
        registry: Optional[ToolRegistry] = None,
        is_precursor: bool = False,
        ledger: Optional[Any] = None,
    ) -> str:
        self.call_count += 1
        if self.canned_response:
            return self.canned_response
        return build_template_advice(machine_id, signature, recalled, is_precursor=is_precursor, ledger=ledger)


class LlmAdvisor:
    """Groq-backed advisor with multi-turn tool calling and template fallback."""

    def __init__(self) -> None:
        self.cfg = get_settings()
        self._groq_client = None
        if self.cfg.use_groq:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=self.cfg.groq_api_key, timeout=15.0)
            except Exception:
                logger.exception("Failed to initialize Groq client; falling back to template engine")

    def generate_advice(
        self,
        machine_id: str,
        signature: str,
        recalled: list[Memory],
        registry: Optional[ToolRegistry] = None,
        is_precursor: bool = False,
        ledger: Optional[Any] = None,
    ) -> str:
        if not self._groq_client:
            logger.info("Using template advisor fallback (no Groq API key or client)")
            return build_template_advice(machine_id, signature, recalled, is_precursor=is_precursor, ledger=ledger)

        if not recalled:
            return build_template_advice(machine_id, signature, recalled, is_precursor=is_precursor, ledger=ledger)

        # Build initial prompt with recalled memories and exact ledger grounding
        stats = ledger.get_stats(machine_id) if ledger else {}
        history_context = "\n---\n".join(m.text for m in recalled)
        user_prompt = (
            f"Machine: {machine_id}\n"
            f"Current Symptom Signature: {signature}\n"
            f"Incident type: {'PRECURSOR / SOFT ANOMALY' if is_precursor else 'HARD FAULT / OVERCURRENT TRIP'}\n\n"
            f"Recalled Persistent Memories from Hindsight:\n{history_context}\n\n"
            f"Verified Empirical Outcomes Ledger:\n{json.dumps(stats.get('fix_outcomes', {}))}\n\n"
            "Provide diagnostic advice for the on-site technician. "
            "Highlight what worked, what failed, and specify the recommended fix action."
        )

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # Tool calling loop (max 4 iterations)
        max_iterations = 4
        for iteration in range(max_iterations):
            try:
                response = self._groq_client.chat.completions.create(
                    model=self.cfg.groq_model,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                    temperature=0.2,
                    max_tokens=600,
                )
                msg = response.choices[0].message
                messages.append(msg)

                # If no tool calls, return final response
                if not msg.tool_calls:
                    return msg.content or build_template_advice(machine_id, signature, recalled, is_precursor=is_precursor, ledger=ledger)

                # Process tool calls
                if not registry:
                    logger.warning("Tool calls received but no registry provided")
                    break

                for tc in msg.tool_calls:
                    fn_name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        logger.warning("Malformed tool arguments for %s, retrying with error prompt", fn_name)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps({"error": "Malformed JSON in tool arguments"}),
                        })
                        continue

                    tool_output = registry.execute(fn_name, args)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_output,
                    })

            except Exception as e:
                logger.warning("Groq completion failed on iteration %d: %s. Using template fallback.", iteration, e)
                return build_template_advice(machine_id, signature, recalled, is_precursor=is_precursor, ledger=ledger)

        return build_template_advice(machine_id, signature, recalled, is_precursor=is_precursor, ledger=ledger)

