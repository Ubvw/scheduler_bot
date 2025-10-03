import json
import os
from pydantic import BaseModel, Field
from typing import Literal, Optional
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from tools.memory_tools import (
    get_create_manage_memory_tool,
    get_create_search_memory_tool,
    get_store,
)
from langgraph.prebuilt import create_react_agent

# --- Agent Definition ---
load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
llm = ChatOpenAI(
    model="x-ai/grok-4-fast",
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key,
    extra_body={
        "reasoning": {
            "enabled": True,
        }
    }
)

class HitlOutput(BaseModel):
    """Structured output for the HITL Agent's interpretation."""
    intent: Literal["CONFIRM", "REJECT_WITH_NEW_INFO", "AMBIGUOUS"] = Field(
        description=(
            "Primary intent. For single-slot 'yes'/'no': 'yes' => CONFIRM, 'no' => AMBIGUOUS. "
            "If participants are added, intent MUST be REJECT_WITH_NEW_INFO to trigger re-analysis."
        )
    )
    confirmed_option: Optional[int] = Field(
        description=(
            "The option number the user confirmed (1-indexed). For single-slot 'yes', set to 1."
        )
    )
    new_information: Optional[str] = Field(
        description=(
            "Any new constraints or modifications (e.g., 'afternoon only', '30 mins', 'next week')."
        )
    )
    participants_to_add: Optional[list[str]] = Field(
        description=(
            "Slack mentions/IDs or emails to add as participants. Presence of values requires re-analysis."
        )
    )

# --- Define the ReAct Agent's Prompt ---
HITL_SYSTEM_MESSAGE = f"""
You are the HITL (Human-in-the-Loop) Agent sitting between proposed meeting times and the user's reply. Your role is to interpret the user's message and either schedule the chosen option or signal what to do next.

Core objectives:
1) Classify intent as exactly one of: CONFIRM, REJECT_WITH_NEW_INFO, AMBIGUOUS.
2) Use tools appropriately:
   - Use the search memory tool to retrieve prior constraints/preferences only if helpful.
   - Use the manage memory tool to persist new constraints/preferences when the user provides them.
   - CRITICAL: Scheduling is handled by a deterministic graph node. Your job is to output a clean JSON with intent, confirmed_option, participants_to_add, and new_information.
3) Produce a single JSON object following the provided schema as the final output. No extra text.

Real‑world reply handling guidelines:
- Phrases like "first one", "option 1", "the earlier slot", "the second works", "go with 3" → intent = CONFIRM and set confirmed_option accordingly. Only schedule in this case.
- If the user asks to add people (e.g., "add <@U123>") or provides emails (e.g., "add a@x.com, b@y.com"), include them in participants_to_add and set intent = REJECT_WITH_NEW_INFO even if they also chose an option. The workflow MUST re-analyze availability with the new participants before scheduling.
- Summarize any additional constraints in new_information when applicable.
- Phrases like "none work", "can't do mornings", "after 3pm only", "next week instead", "prefer 30 minutes" → intent = REJECT_WITH_NEW_INFO and put the new constraints in new_information; do not schedule.
- Vague replies like "maybe", "either", "okay" without a clear option number, or conflicting statements → intent = AMBIGUOUS; do not schedule.
- If the user says "end" the outer workflow may handle cancellation; you should still classify based on content, but never schedule unless a clear confirmation is present.

Special case: single-slot yes/no confirmation
- When context indicates exactly one candidate slot and the user replies "yes" (case-insensitive), set intent = CONFIRM and confirmed_option = 1.
- When the user replies "no" (case-insensitive), set intent = AMBIGUOUS. Do not schedule; the workflow will ask for more context.

Tool usage policy:
- On REJECT_WITH_NEW_INFO, store constraints via the manage memory tool when they are concrete and useful (e.g., time windows, days, duration preferences, participant constraints). Do not schedule.
- On AMBIGUOUS, do not use tools unless storing genuinely useful clarified constraints; do not schedule.

Output contract:
- Your FINAL ANSWER must be a single JSON object that strictly matches this schema and nothing else.
JSON Schema:
{json.dumps(HitlOutput.model_json_schema(), indent=2)}
"""

# --- Create the Agent Executor ---
def create_hitl_agent_executor(namespace: str = "thread1"):
    """Create a stateless HITL ReAct agent with namespaced tools.

    Only long-term memory tools are provided; no checkpointer to prevent short-term spillover and duplication.
    """
    tools = get_create_manage_memory_tool(namespace=namespace) \
        + get_create_search_memory_tool(namespace=namespace)

    agent_executor = create_react_agent(
        model=llm,
        tools=tools,
        store=get_store(),
    )
    return agent_executor