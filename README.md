### Google Calendar Slack Scheduler

An AI-powered Slack assistant that helps propose and schedule meetings by integrating Slack, LangGraph agents, and Google Calendar.

It listens for Slack mentions, extracts meeting intent and constraints, proposes candidate time slots, loops with the user for clarification, and schedules the final meeting on Google Calendar.

---

## Features
- Parse natural-language scheduling requests from Slack mentions
- Persist reusable, long‑term preferences (e.g., mornings-only) via semantic memory
- Propose candidate meeting times and support human-in-the-loop feedback
- Resolve Slack mentions to emails and schedule events on Google Calendar
- Robust workflow built with LangGraph (interrupts and resume)

---

## Project Structure

```
src/
  app/
    main.py                 # Slack event entrypoint (Socket Mode)
    slack_app.py            # Initializes AsyncApp and tokens
    session_manager.py      # In-memory session tracking
    shared_session_manager.py
  agents/
    receptionist_agent.py   # Extracts meeting details + memory policy
    analyze_agent.py        # Finds candidate time slots
    hitl_agent.py           # Interprets user replies (confirm/adjust)
  graph/
    main_graph.py           # LangGraph workflow wiring nodes together
  tools/
    google_calendar_tools.py# Google Calendar auth, free/busy, create event
    scheduling_tool.py      # Final scheduling helper used by graph
    slack_tools.py          # Slack utilities (IDs, emails, chat history)
    datetime_tool.py        # Current date/time context
    memory_tools.py         # Vector store + checkpointer helpers
```

Key flow: `src/app/main.py` handles `app_mention` and initializes a per-thread workflow state → `src/graph/main_graph.py` orchestrates nodes: preprocess → receptionist → analyze → present options → wait (interrupt) → hitl → route → schedule/clarify/end.

---

## Prerequisites
- Python 3.12+
- Slack App with Socket Mode enabled
  - Bot Token and App-Level Token
- Google Cloud project + OAuth2 credentials for Calendar API
  - Enable "Google Calendar API"
  - Download `credentials.json` (OAuth client ID)
- An LLM provider key for OpenRouter (used by agents)

---

## Setup

1) Clone and open the project

```bash
git clone <your-repo-url>
cd google_calendar
```

2) Create and populate `.env`

create .env

Add the following variables (no quotes):

```bash
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
OPENROUTER_API_KEY=sk-or-...
```

3) Place Google credentials

- Save your OAuth client file as `credentials.json` in the project root (same folder as `pyproject.toml`).
- First run will open a browser to authorize and will create a user token file like `token_<alias>.json` per email account.

4) Sync with .venv

Using uv:

```bash
uv sync
```

---

## Running the Slack Bot

Ensure your Slack app is in a workspace and has the necessary scopes (chat:write, users:read, app_mentions:read, im:history if needed) and Socket Mode enabled.

Start the app:

```bash
python -m src.app.main
```

You should see "Starting Scheduler Bot...". Mention the bot in any channel/thread to start a session, e.g., "@scheduler set a 1h sync with @alice next Tue morning".

---

## How It Works (Architecture)

- Slack entrypoint (`src/app/main.py`)
  - Handles `app_mention`, normalizes text, resolves participants, and starts or resumes a per-thread LangGraph run.
  - Uses `SessionManager` to avoid duplicate processing and to pause/resume for human input.

- LangGraph workflow (`src/graph/main_graph.py`)
  - Nodes:
    - preprocess_data: adds current date/time, prepares chat history
    - receptionist: parses title/duration/timeframe and manages long‑term preferences via memory tools
    - analyze: proposes candidate slots from constraints and participants
    - present_options: posts options to Slack
    - wait_for_input: interrupts until user replies in thread
    - hitl_agent: interprets reply (confirm/new info/ambiguous)
    - route_response: decides next node (schedule, re‑analyze, clarify, end)
    - schedule_meeting: resolves attendees’ emails and creates the Google Calendar event

- Google Calendar (`src/tools/google_calendar_tools.py`)
  - OAuth via `credentials.json` → stored per-account token files `token_<alias>.json`
  - Free/busy queries across calendars; event creation with attendees and reminders

---

## Environment Variables
- `SLACK_BOT_TOKEN`: Bot token (xoxb-...)
- `SLACK_APP_TOKEN`: App-level token (xapp-...) for Socket Mode
- `OPENROUTER_API_KEY`: LLM API key

Optional/implicit:
- `credentials.json` file is required in project root

---

## Development Notes
- Code targets Python 3.12 and uses `pyproject.toml` for dependencies
- Agents use `langchain-openai` via OpenRouter; models can be adjusted in `agents/*`
- Keep long‑term preference storage minimal and user-scoped per prompts

Run linters/tests as desired within your environment. If you modify any file paths for credentials or tokens, reflect changes in `tools/google_calendar_tools.py`.

---

## Troubleshooting
- Browser auth doesn’t open: ensure `credentials.json` is valid and machine can open a local server; otherwise switch to installed app flow alternatives.
- Slack mentions not triggering: verify the bot is invited to the channel, has `app_mentions:read`, and Socket Mode is connected.
- Event not created: confirm requester or added participants have valid emails and Calendar API is enabled for the account.

---

