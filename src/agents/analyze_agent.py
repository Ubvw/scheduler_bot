import os
import json
from typing import List
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Import the tools this agent will use
from tools.google_calendar_tools import get_aggregated_freebusy_for_accounts
from tools.memory_tools import (
    get_create_search_memory_tool,
    get_store,
)

from langgraph.prebuilt import create_react_agent

# --- Load API Keys and Initialize LLM ---
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

def _build_tools(namespace: str):
    """Build tools with a per-conversation namespace for memory isolation."""
    return [get_aggregated_freebusy_for_accounts] + get_create_search_memory_tool(namespace=namespace)


# --- Define Structured Output ---
class AnalyzeOutput(BaseModel):
    """Structured output for the Analyze Agent."""
    time_slots: List[str] = Field(
        description=(
            "1-3 proposed meeting time slots as human-readable ranges. "
            "Return exactly one slot when there is a single clear, conflict-free option. "
            "Example: '2025-10-01 09:00-10:00 Asia/Manila'."
        )
    )
    start_iso: str = Field(description="Resolved timeframe start in ISO 8601, e.g., '2025-10-01T01:00:00Z'.")
    end_iso: str = Field(description="Resolved timeframe end in ISO 8601, e.g., '2025-10-08T01:00:00Z'.")
    duration_minutes: int = Field(description="Required meeting duration in minutes.")
    considered_constraints: List[str] = Field(
        default_factory=list,
        description="Any constraints/preferences considered when proposing time slots.",
    )

# --- Define the ReAct Agent's Prompt ---
ANALYZER_SYSTEM_MESSAGE = f"""
You are an expert scheduling Analyze Agent. Your objective is to propose the best possible meeting time slots by using ALL provided runtime context and tools precisely.

Context you will receive (from the user message):
- Current runtime: current DAY, DATE, and TIME (timezone is Asia/Manila, UTC+8)
- Meeting details: title, duration in hours, timeframe_query (natural language), and known constraints
- Participant information: participant emails (if provided)

Core principles to follow:
- Clarity: Keep internal steps simple and focused; avoid unnecessary detours.
- Context: Use the provided current DAY/DATE/TIME and timeframe_query to anchor all reasoning about when to schedule.
- Specificity: Resolve an exact time window and duration; do not return vague ranges.
- Iterative refinement (internally): Think step-by-step, verify assumptions, then act with tools. Do not include your chain-of-thought in the final answer.
- Constraint adherence (STRICT): Treat constraints from both known_constraints (user input) and tool/memory outputs as HARD BLOCKERS, not soft preferences. Never propose slots that violate them. If the requested timeframe conflicts with constraints, prefer the constraints and adjust the timeframe/slots accordingly.

Strict step-by-step process:
1) Determine Time Range
   - Interpret timeframe_query USING the provided current DAY, DATE, and TIME as the reference point.
   - Resolve precise ISO 8601 datetimes for a start and end window that align with the intent (e.g., "next week", "tomorrow afternoon").
   - Ensure the window is sufficiently wide to contain multiple candidate slots of the requested duration.

2) Retrieve Preferences
   - Use the search memory tool to find relevant preferences/constraints.
   - IMPORTANT: Always query memory using the user id, not the name or email.
   - Merge constraints from known_constraints and from tool/memory retrieval. Constraints take precedence over vague or conflicting user phrasing.

3) Get Availability
   - Use get_aggregated_freebusy_for_accounts with participant emails and the resolved [start, end] window.
   - If participant emails are missing in the user message, proceed with those that are available. If none are available, skip tool use and continue with best-effort assumptions explicitly listed in considered_constraints.

4) Synthesize and Propose
   - If there is a single clear, conflict-free slot that fits the timeframe and constraints, return EXACTLY ONE slot in time_slots.
   - Otherwise, propose 2-3 conflict-free candidate slots that best satisfy constraints.
   - Prefer business hours in Asia/Manila unless constraints specify otherwise. Respect no-meeting days or time windows if found in memory.
   - Prioritize earlier feasible times within the intended timeframe. Briefly summarize applied constraints/assumptions in considered_constraints.
   - NEVER propose any slot that violates constraints. Example: if constraints indicate "not available on Wednesday", do NOT propose any Wednesday times even if the user asks for Wednesday; instead, suggest the nearest feasible alternatives that respect constraints.

Tool usage policy:
- Use search_memory for each participant (including the requesting user and all participants to consider for scheduling) to capture any preferences or constraints that could impact scheduling.
- Use get_aggregated_freebusy_for_accounts exactly once per evaluation window, unless you must refine the window after synthesis. Get the availability of the requester.

Output requirements:
- Your FINAL ANSWER must be a single JSON object and MUST strictly match this JSON Schema (no extra commentary, no markdown):
JSON Schema:
{json.dumps(AnalyzeOutput.model_json_schema(), indent=2)}

Quality checklist before answering:
- Did you resolve a precise start_iso and end_iso that reflect timeframe_query with the provided current DAY/DATE/TIME?
- Do the proposed time_slots match the requested duration and known constraints? avoid known busy periods?
- Are key assumptions and applied constraints captured in considered_constraints?
 - Zero-tolerance constraint check: Do any proposed time_slots violate constraints from known_constraints or tool/memory? If yes, revise to fully comply.
"""

# --- Create the Global Agent Executor ---
def create_analyze_agent_executor(namespace: str = "thread1"):
    """Create a stateless Analyze agent executor with namespaced memory tools.

    The executor is created without a checkpointer to avoid message duplication on reruns.
    """
    tools = _build_tools(namespace)
    analyze_agent_executor = create_react_agent(llm, tools, store=get_store())
    return analyze_agent_executor