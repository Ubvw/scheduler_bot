from slack_sdk.web.client import WebClient
from slack_sdk.errors import SlackApiError
import os
import re
from typing import Optional, List, Callable
from dotenv import load_dotenv
try:
    from langchain.tools import Tool
except Exception:
    Tool = None

load_dotenv()


USER_TOKEN = os.environ["SLACK_USER_TOKEN"]
user_client = WebClient(token=USER_TOKEN)


def get_chat_history(channel_id: str, message_count: int = 5) -> dict:
    """
    Retrieves slack's recent channel messages.
    Returns a dictionary with 'emails' and 'history_text'.
    """
    
    history_text = ""
    entries: List[dict] = []
    try:
        response = user_client.conversations_history(channel=channel_id, limit=message_count+1)
        # Skip the triggering message at index 0; take next N
        raw_messages = response['messages'][1:message_count+1]
        # Build entries with author and text
        for m in raw_messages:
            user_id = m.get('user') or m.get('username') or ''
            text = m.get('text', '')
            entries.append({"user": user_id, "text": text})
        # Oldest-first text with author mention prefix for clear attribution
        lines = []
        for e in reversed(entries):
            author = f"<@{e['user']}>" if e.get('user') else "<@unknown>"
            lines.append(f"{author}: {e.get('text', '')}")
        history_text = "\n".join(lines)
    except SlackApiError as e:
        print(f"Error fetching history for channel {channel_id}: {e}")

    return {
        "history_text": history_text,
        "entries": entries
    }


def get_email_for_user_id(user_id: str) -> Optional[str]:
    """Resolve a Slack user ID to their profile email, if available."""
    try:
        resp = user_client.users_info(user=user_id)
        profile = resp.get("user", {}).get("profile", {})
        return profile.get("email")
    except SlackApiError as e:
        print(f"Error fetching user info for {user_id}: {e}")
        return None


def get_user_info_sync(user_id: str) -> dict:
    """
    Sync helper to fetch Slack user info and return a dict {id, name, email}.
    Falls back to minimal fields if data is unavailable.
    """
    try:
        resp = user_client.users_info(user=user_id)
        user = resp.get("user", {})
        profile = user.get("profile", {})
        name = profile.get("display_name") or profile.get("real_name") or user_id
        email = profile.get("email", "")
        return {"id": user_id, "name": name, "email": email}
    except SlackApiError as e:
        print(f"Error fetching user info for {user_id}: {e}")
        return {"id": user_id, "name": user_id, "email": ""}


MENTION_RE = re.compile(r"<@([A-Z0-9]+)>")


def extract_user_ids_from_text(text: str) -> List[str]:
    """Extract Slack user IDs from a message text containing mentions like <@U123>."""
    return MENTION_RE.findall(text or "")


def get_chat_history_tool(channel_id: str) -> List[object]:
    """
    Returns a tool that retrieves the last N messages for the given channel.
    If N <= 0, returns an empty string.
    """
    def _run(n: int) -> str:
        try:
            n = int(n)
        except Exception:
            return ""
        if n <= 0:
            return ""
        res = get_chat_history(channel_id=channel_id, message_count=n)
        return res.get("history_text", "")

    # If LangChain Tool is available, wrap it; otherwise return a simple callable
    if Tool is not None:
        tool = Tool(
            name="get_chat_history",
            description=(
                "Fetch the last N messages from the current Slack channel. "
                "Use ONLY when the user explicitly specifies a numeric N (e.g., 'last 3 messages')."
            ),
            func=_run,
        )
        return [tool]
    else:
        return [
            {
                "name": "get_chat_history",
                "description": (
                    "Fetch the last N messages from the current Slack channel. Use ONLY when the user explicitly specifies a numeric N."
                ),
                "func": _run,
            }
        ]