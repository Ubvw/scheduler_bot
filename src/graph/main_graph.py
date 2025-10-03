# In graphs/main_graph.py
import json

from typing import TypedDict, List, Optional
from tools.slack_tools import get_chat_history
from agents.receptionist_agent import create_receptionist_agent_executor, RECEPTIONIST_SYSTEM_MESSAGE
from agents.analyze_agent import create_analyze_agent_executor, ANALYZER_SYSTEM_MESSAGE
from agents.hitl_agent import HITL_SYSTEM_MESSAGE
from agents.hitl_agent import create_hitl_agent_executor
from tools.datetime_tool import get_current_datetime_info
from tools.scheduling_tool import schedule_final_meeting
from tools.slack_tools import extract_user_ids_from_text, get_email_for_user_id, get_user_info_sync

from langgraph.types import interrupt, Command
from langgraph.graph import END, StateGraph

from app.slack_app import app as slack_app # For sending messages
from app.shared_session_manager import session_manager # Import the shared session manager
from tools.memory_tools import get_checkpointer


# --- 1. Define the Graph State ---
# This is the shared "memory" that all nodes in our graph will have access to.
class GraphState(TypedDict):
    """
    Represents the state of our graph.

    Attributes:
        initial_query: The initial user request.
        user_id: The ID of the user who initiated the request.
        channel_id: The ID of the channel where the request was made.
        mentioned_user_ids: List of user IDs mentioned in the query.
        chat_history: The recent chat history from the channel.
        receptionist_output: The structured output from the Receptionist Agent.
    """
    
    # Field populated from slack api
    initial_query: str
    user: list[dict]
    channel_id: str
    thread_ts: str # Reference
    involved_users: List[dict]
    chat_history: Optional[str]
    # Current datetime context
    current_time: Optional[str]
    current_date: Optional[str]
    current_day: Optional[str]

    # This will be populated by the Receptionist Agent
    receptionist_output: Optional[dict]

    # This will be populated by the Analyze Agent
    proposed_times: Optional[str]
    analyze_structured: Optional[dict]

    # HITL
    user_response: Optional[str]
    hitl_output: Optional[str]
    # Session-scoped, short-term constraints gathered during HITL (not persisted)
    recent_constraints: Optional[list[str]]




def preprocess_data_node(state: GraphState) -> GraphState:
    """
    This node gathers required data before the main agent runs.
    It fetches participant emails and recent chat history.
    """
    print("\n---NODE: Pre-process Data---\n")
    

    state["chat_history"] = ""
    datetime_info = get_current_datetime_info()
    state["current_time"] = datetime_info["time"]
    state["current_date"] = datetime_info["date"]
    state["current_day"] = datetime_info["day"]
    
    print(f"   History fetched: {len(state['chat_history'])} characters")
    print(f"   Current Time: {datetime_info['time']}")
    print(f"   Current Date: {datetime_info['date']}")
    print(f"   Current Day: {datetime_info['day']}")
    return state




def run_receptionist_agent_node(state: GraphState) -> GraphState:
    """Invokes the Receptionist Agent to parse the user's request."""
    print("---NODE: Receptionist Agent---")
    
    # 1. Create a channel-specific agent executor (for chat history tool scoping)
    agent_executor = create_receptionist_agent_executor(state["channel_id"])
    # Use a stable conversation namespace per Slack thread for the receptionist
    safe_thread = str(state['thread_ts']).replace('.', '-')
    conversation_namespace = f"{state['channel_id']}:{safe_thread}:receptionist"
    
    # 2. Prepare the messages for the agent
    messages = [
        ("system", RECEPTIONIST_SYSTEM_MESSAGE),
        ("human", f"User Request: \"{state['initial_query']}\"\n\nChat History:\n{state['chat_history']}"),
    ]
    
    # 3. Invoke the agent
    result = agent_executor.invoke({"messages": messages}, config = {"configurable": {"thread_id": conversation_namespace}})
    
    # 4. The final message from the agent should be our JSON object
    final_json_response = result['messages'][-1].content
    
    # 5. Parse and store the structured output
    try:
        structured_output = json.loads(final_json_response)
        state["receptionist_output"] = structured_output
        # If the agent retrieved chat history, populate state for downstream nodes
        state["chat_history"] = structured_output.get("chat_history_text", "") or ""
        # Merge chat_history_users into involved_users as full dicts {id, name, email}
        chat_uids = structured_output.get("chat_history_users") or []
        if chat_uids:
            existing = state.get("involved_users") or []
            existing_ids = {u.get("id") for u in existing if isinstance(u, dict)}
            for uid in chat_uids:
                if uid and uid not in existing_ids:
                    existing.append(get_user_info_sync(uid))
            state["involved_users"] = existing
        print("   Agent Output (Parsed JSON):")
        print(structured_output)
    except json.JSONDecodeError:
        print(f"   Error: Agent did not return valid JSON. Response was:\n{final_json_response}")
        state["receptionist_output"] = {"error": "Failed to parse agent output."}
        
    return state

# Analyze Agent node
def run_analyze_agent_node(state: GraphState) -> GraphState:
    """Invokes the Analyze Agent to find suitable meeting times."""
    print("---NODE: Analyze Agent---")

    receptionist_output = state["receptionist_output"]
    # Sanitize namespace: some stores disallow '.' in labels
    safe_thread = str(state['thread_ts']).replace('.', '-')
    conversation_namespace = f"{state['channel_id']}:{safe_thread}:analyze"

    # Include short-term, session-scoped constraints from prior HITL turns
    recent_constraints = state.get("recent_constraints") or []

    agent_input = f"""
    Current time context is: {state['current_day']}, {state['current_date']}, {state['current_time']} (UTC+8).
    Here are the meeting details:
    - Title: {receptionist_output.get('meeting_title')}
    - Duration: {receptionist_output.get('duration_hours')} hours
    - Timeframe Query: "{receptionist_output.get('timeframe_query')}"
    - Known Constraints: {receptionist_output.get('constraints')}
    - Session-scoped updates from user: {recent_constraints}
    - Requesting user information: {state['user']}
    - Participants to consider for scheduling: {state['involved_users']}
    """
    messages = [
        ("system", ANALYZER_SYSTEM_MESSAGE),
        ("human", agent_input),
    ]
    result = create_analyze_agent_executor("thread1").invoke(
        {"messages": messages},
        config={"configurable": {"thread_id": conversation_namespace}}
    )

    proposed_times = result['messages'][-1].content
    state["proposed_times"] = proposed_times
    try:
        state["analyze_structured"] = json.loads(proposed_times)
    except Exception:
        state["analyze_structured"] = None
    
    print("Proposed Times:")
    print(proposed_times)

    return state

#################################################################################################

def present_options_node(state: GraphState):
    """Posts the proposed times to Slack. Does NOT interrupt."""
    print("---NODE: Present Options---")
    import asyncio
    import json as _json
    
    # Prepare adaptive, human-readable message
    raw = state.get("proposed_times") or ""
    human_lines: list[str] = []
    header = ""
    footer = ""
    try:
        data = _json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = None

    if isinstance(data, dict):
        slots = data.get("time_slots") or []
        if not slots:
            header = "I couldn't find any suitable time slots."
        elif len(slots) == 1:
            header = "I found a suitable time slot:"
            human_lines.append(f"1) {slots[0]}")
        else:
            header = "Here are a few options I found:"
            for idx, s in enumerate(slots, start=1):
                human_lines.append(f"{idx}) {s}")
        if not slots:
            footer = "Feel free to adjust your timeframe or constraints."
        elif len(slots) == 1:
            footer = (
                "Please reply with just 'yes' to confirm or 'no' to decline. "
                "You can also add participants (e.g., 'add @user') or constraints (e.g., 'afternoon only')."
            )
        else:
            footer = (
                " "
                "Please reply in this thread to confirm (e.g., '@scheduler Option 1 is good') "
                "or suggest changes (e.g., 'afternoon only', '30 mins', 'add @user to the meeting')."
            )
    else:
        # Fallback: raw text
        header = "Here are the proposed time details:"
        human_lines.append(str(raw))
        footer = (
            "Please reply in this thread to confirm or suggest changes."
        )

    text = "\n".join([header, "", *human_lines, "", footer]).strip()

    async def send_message():
        await slack_app.client.chat_postMessage(
            channel=state["channel_id"],
            thread_ts=state["thread_ts"],
            text=text
        )
    
    asyncio.run(send_message())
    return state

def wait_for_input_node(state: GraphState):
    """
    This is a dedicated node that calls interrupt() to pause the graph.
    Its only purpose is to wait for human input.
    """
    print("---NODE: Waiting for Human Input (Pausing)---")
    
    # Mark the session as waiting for a reply
    thread_id = f"{state['channel_id']}:{state['thread_ts']}"
    session_manager.update_session_status(thread_id, "awaiting_hitl")
    
    # The graph will pause here. When resumed, the value passed to
    # Command(resume=...) will be returned by the interrupt() call.
    user_response = interrupt("waiting_for_user_input") 
    
    # The user's reply is now in the state
    return {"user_response": user_response}

def force_end_node(state: GraphState) -> GraphState:
    """Confirms to the user that the scheduling process is being cancelled."""
    print("---NODE: Force End---")
    import asyncio
    
    end_message = "Okay, I'm cancelling this scheduling request. Feel free to start a new one anytime."
    
    async def send_message():
        await slack_app.client.chat_postMessage(
            channel=state["channel_id"],
            thread_ts=state["thread_ts"],
            text=end_message
        )
    
    asyncio.run(send_message())
    return state

def clarification_node(state: GraphState) -> GraphState:
    """Asks the user for a more specific response."""
    print("---NODE: Clarify---")
    import asyncio

    clarification_message = (
        "I'm sorry, I didn't quite understand your response. "
        "Could you please confirm one of the options, provide a new constraint (e.g., 'I need an afternoon slot'), or reply with 'END' to cancel?"
    )
    
    async def send_message():
        await slack_app.client.chat_postMessage(
            channel=state["channel_id"],
            thread_ts=state["thread_ts"],
            text=clarification_message
        )
    
    asyncio.run(send_message())
    return state

def route_response(state: GraphState) -> str:
    """Checks the user's response and decides the next step."""
    print("---NODE: Route Response---")
    
    user_response = state.get("user_response", "").lower()

    # Add a high-priority check for the user's 'END' command
    if "end" in user_response:
        print("   User requested to end the process.")
        return "force_end"

    intent = state["hitl_output"].get("intent")
    # If new participants are added, force re-analysis regardless of confirmation
    newly_added = state["hitl_output"].get("participants_to_add") or []
    if newly_added:
        return "re-analyze"
    print(f"   User intent detected: {intent}")

    if intent == "CONFIRM":
        return "schedule_meeting"
    elif intent == "REJECT_WITH_NEW_INFO":
        return "re-analyze"
    else: # AMBIGUOUS
        return "clarify"

def run_hitl_agent_node(state: GraphState) -> GraphState:
    """
    Invokes the HITL Agent to interpret the user's response and take action.
    """
    print("---NODE: HITL Agent---")

    safe_thread = str(state['thread_ts']).replace('.', '-')
    conversation_namespace = f"{state['channel_id']}:{safe_thread}:hitl"

    # Friendlier summary of proposed times for the agent
    proposed_raw = state.get("proposed_times") or ""
    try:
        _data = json.loads(proposed_raw) if isinstance(proposed_raw, str) else proposed_raw
    except Exception:
        _data = None
    if isinstance(_data, dict):
        _slots = _data.get("time_slots") or []
        if not _slots:
            summary = "No candidate slots."
        elif len(_slots) == 1:
            summary = f"Single candidate: {_slots[0]}"
        else:
            summary = "Candidates:\n" + "\n".join([f"{i+1}) {_slots[i]}" for i in range(len(_slots))])
    else:
        summary = str(proposed_raw)

    agent_input = {
        "messages": [
            ("system", HITL_SYSTEM_MESSAGE),
            ("human", f"Here are the proposed times (summarized):\n{summary}\n\nHere is my reply: \"{state['user_response']}\""),
        ]
    }
    
    result = create_hitl_agent_executor("thread1").invoke(
        agent_input,
        config = {"configurable": {"thread_id": conversation_namespace}}
    )
    final_json_response = result['messages'][-1].content
    
    try:
        structured_output = json.loads(final_json_response)
        state["hitl_output"] = structured_output
        # Capture short-term constraints within this session only
        if structured_output.get("intent") == "REJECT_WITH_NEW_INFO" and structured_output.get("new_information"):
            existing = state.get("recent_constraints") or []
            existing.append(structured_output["new_information"]) 
            state["recent_constraints"] = existing
        print("   Agent Interpretation:")
        print(structured_output)
    except json.JSONDecodeError:
        print(f"   Error: HITL Agent did not return valid JSON. Response was:\n{final_json_response}")
        state["hitl_output"] = {"intent": "AMBIGUOUS", "new_information": "Agent failed to produce valid JSON."}
        
    return state


def schedule_meeting_node(state: GraphState) -> GraphState:
    print("---NODE: Schedule Meeting---")
    import asyncio
    from datetime import datetime
    import re as _re
    from zoneinfo import ZoneInfo

    # Extract structured data
    analyze_struct = state.get("analyze_structured") or {}
    hitl = state.get("hitl_output") or {}

    # Helpers
    def _get_requester_email() -> Optional[str]:
        try:
            u = (state.get("user") or {})
            if isinstance(u, list):
                u = (u[0] if u else {})
            return u.get("profile", {}).get("email") or u.get("email") or (
                get_email_for_user_id(u.get("id")) if u.get("id") else None
            )
        except Exception:
            return None

    def _collect_initial_attendees() -> list[str]:
        attendees: list[str] = []
        requester = _get_requester_email()
        if requester:
            attendees.append(requester)
        for mu in state.get("involved_users", []) or []:
            email = mu.get("profile", {}).get("email") or mu.get("email")
            if email and email not in attendees:
                attendees.append(email)
        return attendees

    def _resolve_added_participants(existing: list[str]) -> tuple[list[str], list[str]]:
        participants_to_add = hitl.get("participants_to_add") or []
        unresolved_ids: list[str] = []
        for token in participants_to_add:
            token = (token or "").strip()
            if not token:
                continue
            # direct email string
            if "@" in token and "<" not in token and ">" not in token:
                if token not in existing:
                    existing.append(token)
                continue
            # Slack mentions / user IDs
            user_ids = extract_user_ids_from_text(token)
            if not user_ids and token.startswith("U"):
                user_ids = [token]
            if not user_ids:
                continue
            found_any = False
            for uid in user_ids:
                email = get_email_for_user_id(uid)
                if email:
                    found_any = True
                    if email not in existing:
                        existing.append(email)
            if not found_any:
                unresolved_ids.extend(user_ids)
        return existing, unresolved_ids

    def _parse_confirmed_slot() -> tuple[Optional[datetime], Optional[datetime]]:
        confirmed_index = (hitl.get("confirmed_option") or 1) - 1
        slots = (analyze_struct.get("time_slots") or []) if analyze_struct else []
        if not slots or not (0 <= confirmed_index < len(slots)):
            return None, None
        m = _re.search(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})-(\d{2}:\d{2})", slots[confirmed_index])
        if not m:
            return None, None
        day, start_str, end_str = m.group(1), m.group(2), m.group(3)
        tz = ZoneInfo("Asia/Manila")
        try:
            start_dt = datetime.fromisoformat(f"{day}T{start_str}:00").replace(tzinfo=tz)
            end_dt = datetime.fromisoformat(f"{day}T{end_str}:00").replace(tzinfo=tz)
            return start_dt, end_dt
        except Exception:
            return None, None

    # Build attendees
    attendees = _collect_initial_attendees()
    attendees, unresolved = _resolve_added_participants(attendees)

    if unresolved:
        async def ask_for_emails():
            ids = ", ".join(f"<@{u}>" for u in unresolved)
            await slack_app.client.chat_postMessage(
                channel=state["channel_id"],
                thread_ts=state["thread_ts"],
                text=(
                    f"I need emails for {ids} to add them to the invite. "
                    "Please reply with their emails (comma-separated), or say 'skip' to proceed without them."
                ),
            )
        asyncio.run(ask_for_emails())
        return state

    # Parse slot and schedule
    start_dt, end_dt = _parse_confirmed_slot()
    if start_dt is None or end_dt is None:
        print("   Unable to parse confirmed slot; skipping scheduling.")
        return state

    requester_email = _get_requester_email()
    account_email = requester_email or (attendees[0] if attendees else None)
    if not account_email:
        print("   No requester email found; cannot schedule.")
        return state

    title = state.get("receptionist_output", {}).get("meeting_title") or "Meeting"
    description = "Scheduled via Slack assistant"

    result_msg = schedule_final_meeting(
        account_email=account_email,
        title=title,
        attendees=attendees,
        start_dt=start_dt,
        end_dt=end_dt,
        description=description,
    )

    async def send_confirmation():
        await slack_app.client.chat_postMessage(
            channel=state["channel_id"],
            thread_ts=state["thread_ts"],
            text=result_msg,
        )
    asyncio.run(send_confirmation())
    return state




# --- 3. Assemble the Graph ---
def build_graph():
    """Builds the main LangGraph workflow."""
    workflow = StateGraph(GraphState)

    # Add the nodes
    workflow.add_node("preprocess_data", preprocess_data_node)
    workflow.add_node("receptionist", run_receptionist_agent_node)
    workflow.add_node("analyze", run_analyze_agent_node)
    workflow.add_node("present_options", present_options_node)
    workflow.add_node("wait_for_input", wait_for_input_node) # Interrupt node
    workflow.add_node("hitl_agent", run_hitl_agent_node)
    workflow.add_node("clarify", clarification_node)
    workflow.add_node("schedule_meeting", schedule_meeting_node)
    workflow.add_node("force_end", force_end_node)


    # Define the workflow
    workflow.set_entry_point("preprocess_data")
    workflow.add_edge("preprocess_data", "receptionist")
    workflow.add_edge("receptionist", "analyze")
    workflow.add_edge("analyze", "present_options")
    workflow.add_edge("present_options", "wait_for_input")
    workflow.add_edge("wait_for_input", "hitl_agent")
    workflow.add_edge("clarify", "wait_for_input")


    workflow.add_conditional_edges(
        "hitl_agent",
        route_response,
        {
            "force_end": "force_end",
            "end_conversation": END,
            "schedule_meeting": "schedule_meeting",
            "re-analyze": "analyze",
            "clarify": "clarify"
        }
    )
    workflow.add_edge("force_end", END)

    return workflow.compile(checkpointer=get_checkpointer())

main_graph = build_graph()