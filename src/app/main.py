import os
import re
import sys
from pathlib import Path

# Ensure project `src` directory is on sys.path for imports like `graph.*`
src_dir = str(Path(__file__).resolve().parents[1])
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)
from dotenv import load_dotenv
from slack_sdk.errors import SlackApiError
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_app import app, SLACK_APP_TOKEN
from app.shared_session_manager import session_manager
from graph.main_graph import main_graph, GraphState # Import our new graph and state
from langgraph.types import Command

# Session manager is imported from shared_session_manager


async def get_user_info(user_id: str) -> dict:
    """Fetch Slack user info and return {id, name, email}."""
    try:
        resp = await app.client.users_info(user=user_id)
        profile = resp["user"]["profile"]
        return {
            "id": user_id,
            "name": profile.get("display_name") or profile.get("real_name") or user_id,
            "email": profile.get("email", "")
        }
    except SlackApiError as e:
        print(f"Error fetching user info for {user_id}: {e}")
        return {"id": user_id, "name": user_id, "email": ""}




async def extract_mentioned_users(text: str, bot_user_id: str) -> list[dict]:
    """
    Extracts all mentioned user IDs from text (excluding the bot itself),
    and resolves them to {id, name, email}.
    """
    mentioned_ids = [uid for uid in re.findall(r"<@([A-Z0-9]+)>", text) if uid != bot_user_id]
    mentioned_ids = mentioned_ids[1:]
    results = []
    for uid in mentioned_ids:
        results.append(await get_user_info(uid))
    return results

def strip_bot_mention(text: str) -> str:
    """Removes the initial bot mention from the message text for cleaner processing."""
    return re.sub(r'^<@U[A-Z0-9]+>\s*', '', text).strip()


@app.event("app_mention")
async def handle_app_mention(event, say, ack):
    """Main event handler for all app mentions, handling both new and resumed conversations."""
    await ack()

    channel_id = event["channel"]
    user_id = event["user"]
    thread_ts = event.get("thread_ts", event.get("ts"))
    bot_user_id = event.get("authorizations", [{}])[0].get("user_id", "")

    thread_id = f"{channel_id}:{thread_ts}"
    config = {"configurable": {"thread_id": thread_id}}
    user_text = strip_bot_mention(event["text"])

    # Check for any existing session first to prevent duplicates
    existing_session = session_manager.get_any_session(channel_id, thread_ts)
    active_session = session_manager.get_active_session(channel_id, thread_ts)

    if active_session:
        # --- RESUME WORKFLOW ---
        print(f"Resuming workflow for thread {thread_id} with input: '{user_text}'")
        session_manager.update_session_status(thread_id, "running")
        # Run the graph in the background to avoid blocking the Slack event handler
        asyncio.create_task(main_graph.ainvoke(Command(resume=user_text), config=config))
    elif existing_session:
        # --- DUPLICATE EVENT DETECTED ---
        print(f"Duplicate event detected for thread {thread_id}. Session already exists with status: {existing_session.get('status')}")
        await say(text="I'm already processing your request. Please wait for my response.", thread_ts=thread_ts)
    else:
        # --- START NEW WORKFLOW ---
        print(f"Starting new workflow for thread {thread_id}")
        await say(text=f"Got it, <@{user_id}>! Let me look into that...", thread_ts=thread_ts)

        session_manager.create_session(channel_id, thread_ts)
        
        triggering_user = await get_user_info(user_id)
        mentioned_users = await extract_mentioned_users(event["text"], bot_user_id)

        # Ensure the initial state is complete with all required fields
        initial_state: GraphState = {
            "initial_query": user_text,
            "user": triggering_user,
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "involved_users": mentioned_users,
            "chat_history": None,
            "receptionist_output": None,
            "current_time": None,
            "current_date": None,
            "current_day": None,
            "proposed_times": None,
            "user_response": None,
            "hitl_output": None
        }
        
        # Run the graph in the background
        asyncio.create_task(main_graph.ainvoke(initial_state, config=config))

async def main():
    """Starts the bot."""
    print("🚀 Starting Scheduler Bot...")
    handler = AsyncSocketModeHandler(app, SLACK_APP_TOKEN)
    await handler.start_async()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())