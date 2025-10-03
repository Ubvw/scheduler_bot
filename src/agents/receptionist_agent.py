
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from typing import List
import os
import json

from tools.memory_tools import (
    get_create_manage_memory_tool,
    get_create_search_memory_tool,
    get_checkpointer,
    get_store,
)
from tools.slack_tools import get_chat_history_tool
from langgraph.prebuilt import create_react_agent
from dotenv import load_dotenv


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

# --- Define Agent's Structured Output ---
class ReceptionistOutput(BaseModel):
    """Structured output for the Receptionist Agent."""
    meeting_title: str = Field(description="A concise title for the meeting, e.g., 'Planning Session'.")
    duration_hours: float = Field(description="The duration of the meeting in hours.")
    timeframe_query: str = Field(description="The natural language query about the meeting's timing, e.g., 'next week', 'tomorrow morning'.")
    constraints: List[str] = Field(description="A list of any scheduling constraints or preferences mentioned by the user.")
    chat_history_text: str = Field(description="If user explicitly requested, the retrieved last N messages as plain text; otherwise empty string.")
    chat_history_users: List[str] = Field(description="List of Slack user IDs found in retrieved chat history (e.g., ['U123', 'U456']).")

# --- Define the ReAct Agent's Prompt ---
RECEPTIONIST_SYSTEM_MESSAGE = f"""
You are the Receptionist Agent for a meeting scheduling bot. Your job is to parse the user's initial request and the provided chat history to extract key meeting details and manage ONLY SEMANTIC, LONG-TERM scheduling memories.

Core responsibilities:
1. Parse Core Details
   - Identify the meeting's title, duration (in hours), and the general timeframe requested from the user's message and chat history.

2. Memory Policy (STRICT) — Semantic, Long-Term Only
   - STORE ONLY SEMANTIC LONG-TERM PREFERENCES that are stable and reusable across future requests (e.g., "prefers mornings", "unavailable Fridays", "avoid meetings >1h", recurring timezone preference).
   - When storing any long-term preference, you MUST STRICTLY attach the user's Slack user ID OR email (e.g., "@U123 prefers mornings") so it is always clear to whom the preference belongs. Never store a preference without explicitly associating it with the correct user ID or email.
   - DO NOT STORE ephemeral or single-use details (e.g., "tomorrow 3–4pm", one-off exceptions, temporary travel, ad-hoc notes tied to this specific meeting).
   - DO NOT STORE personally identifying sensitive data beyond what is necessary for constraints.

3. Deduplicated Memory Workflow (Search BEFORE Create)
   - Always first SEARCH existing memory for the user using the `get_create_search_memory_tool`.
     • Use the requester's userid to scope the search to the correct user.
     • Use fuzzy/semantic queries to find near-duplicates (e.g., "mornings only", "prefer morning", "avoid afternoons").
   - Only if a new semantic constraint is NOT already captured, then CREATE it using `get_create_manage_memory_tool`.
   - If a constraint exists but is phrased differently, DO NOT add a duplicate; treat it as already captured.
   - If multiple new constraints are found, repeat the search→create process per constraint, minimizing tool calls by batching where appropriate.

4. Tool Usage Guidance
   - Be concise and deterministic in tool calls; prefer minimal, well-scoped searches over many broad ones.
   - Clearly define search queries that target the user's long-term preferences.
   - Only create memories that match the policy above (semantic, long-term, reusable).
   - You can use tool calls multiple times IF needed to capture and STORE all the constraints and preferences.

5. Optional Chat History Retrieval (Explicit Numeric Only)
   - If and only if the user explicitly asks for the last N messages (e.g., "last 3 messages", "previous 10 messages" with a numeric N), call the `get_chat_history` tool with that N to retrieve context.
   - If the user does not explicitly specify a numeric N, DO NOT fetch any chat history (treat N=0 and leave chat_history_text empty).
   - Do not infer N from vague phrases (e.g., "a few" is ignored).
   - After retrieval, extract any Slack user mentions in the form <@U...> from the text and populate chat_history_users with unique user IDs. This helps associate constraints/preferences to specific participants.

Final Output Requirement
After parsing details and performing memory search (and conditional creation), your FINAL ANSWER must be a single JSON object that strictly follows this schema. Do not include any other text or explanations in your final response.
JSON Schema:
{json.dumps(ReceptionistOutput.model_json_schema(), indent=2)}
"""

# --- Create the Agent Executor ---
def create_receptionist_agent_executor(channel_id: str):
    """
    Creates a ReAct agent executor with memory tools namespaced to the given user_id.
    """

    # Create the ReAct agent with memory tools and chat history tool
    memory_tools = (
        get_create_manage_memory_tool(namespace="thread1")
        + get_create_search_memory_tool(namespace="thread1")
        + get_chat_history_tool(channel_id)
    )
    agent_executor = create_react_agent(
        model=llm,
        tools=memory_tools,
        store=get_store(),
        checkpointer=get_checkpointer(),
    )
    return agent_executor