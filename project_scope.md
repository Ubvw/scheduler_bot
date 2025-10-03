# Project overview: Multi-user meeting scheduling agent

## Goal
Develop a prototype that schedules meetings for multiple users by interpreting natural-language availability and constraints from Slack messages.

Examples:
- User A: "I am available every morning from 9–11 AM, except on Wednesdays."
- User B: "I am free on Tuesdays, but if possible, I prefer an early morning slot."
- User C: "I already have a meeting booked on Friday from 2–4 PM."

Example Slack input:
@schedule_bot Schedule a 2-hour planning session next week with @user1 and @user2. I'm free Tuesday and Thursday mornings.


## Tech Stack
- **Messaging Platform**: Slack  
- **AI Framework**: Python with CrewAI + Qdrant(docker localhost) to store semantic memory
- **Slack Integration**: Bolt‑Python (to build the agentic bot and handle Slack events)
   SCOPES:
   Bot Scopes
   app_mentions:read  - View messages that directly mention @scheduler in conversations that the app is in
   chat:write         - Send messages as @scheduler
   User Scopes
   channels:history   - View messages and other content in a user's public channels
   groups:history     - View messages and other content in a user's private channels
   users:read         - View people in a workspace
   users:read.email   - View email addresses of people in a workspace
- **Calendar Integration**: Google Calendar API  
  - `credentials.json` (OAuth client secrets) is already present in the project directory.  
  - OAuth tokens (`token_<alias>.json`) are already generated and stored locally.  
  - Authentication is fully set up — the system can directly call the Calendar API for availability and event creation.  

## Agents
- Triage Agent:
  - Classifies intent (create vs update).
  - Stores/manages semantic memories of user constraints.

- Analyze Agent:
  - Synthesizes constraints, calendar data, and chat history.
  - Proposes 2–3 optimal timeslots.
  - Hands options to HITL Agent for confirmation.
  - May schedule overlapping events only if users explicitly agree.

- HITL Agent (Human-in-the-loop):
  - Confirms or rejects proposed timeslots via Slack.
  - If rejected, requests more context and loops back to Analyze Agent.
  - On confirmation, triggers event scheduling.

## Nodes and tools
- manage_memory_tool: LangMem tool for read/update/delete of semantic memories.
- create_memory_tool: LangMem tool for storing semantic memories.
- get_datetime: Python utility to normalize date/time windows.
- check_history_and_users_email: Bolt-Python utility to resolve mentions, emails, and chat history.
- get_users_availability: Google Calendar API integration (free/busy).
- schedule_meeting: Google Calendar API integration (create/update events).
- hitl-tool: uses slack api to talk back to user.

## Workflow
node 1. Input will come from slack:
   @schedule_bot Schedule a 2-hour planning session next week with @user1 and @user2. I'm free Tuesday and Thursday mornings. Refer to last n messages for context.

2. Triage Agent:
   - Classify request (create/update).
   - Store constraints in memory (create_memory_tool, manage_memory_tool).

3. Pipeline:
   - check_history_and_users_email → resolve participants and context.
   - get_users_availability → fetch free/busy for all relevant calendars.

4. Analyze Agent:
   - Combine constraints + availability + history.
   - Propose 2–3 candidate timeslots.
   - Pass to HITL Agent for confirmation.
   - Respect explicit consent for overlaps.
   - use memory tool to get preferences.

5. HITL Agent (uses slack API):
   - Present options in Slack and capture preference.
   - If confirmed → schedule_meeting.
   - If rejected → gather more context from users, when context is filled → return to Analyze Agent with past_attempts metadata.

## Key design principles
- Natural-language first: constraints expressed directly in Slack.
- Agentic orchestration: specialized roles for triage, reasoning, and human confirmation.
- Human-in-the-loop: users confirm final scheduling decisions.
- Memory-aware: semantic memories persist and inform future scheduling.
- Flexible constraints: supports hard rules (e.g., “not Wednesdays”) and soft preferences (e.g., “prefer mornings”).

## Assumptions
- All participants maintain up-to-date schedules in Google Calendar.  
- The system has OAuth-verified access to each participant’s corporate Google account (email + calendar).  
- Scheduling interactions take place within a Slack group chat environment.  


Refined Milestone Structure
Based on your answers, here's the optimized breakdown:
Milestone 1: Foundation & Slack Integration
Goal: Basic Slack bot that can receive mentions and reply in channel
Deliverables:

Project structure (CrewAI + Bolt-Python + Qdrant setup)
Slack bot receives @schedule_bot mentions in channel
Bot can parse message text and extract mentioned users
Bot replies in the same channel (not DM)
Basic logging setup

Testing:

Send @schedule_bot hello → bot responds in channel
Send @schedule_bot test with @user1 @user2 → bot identifies mentioned users


Milestone 2: Core Utilities & Google Calendar Integration
Goal: Standalone tools working independently
Deliverables:

get_datetime(query, reference_date) → normalizes "next week", "Tuesday", "2 days from now" to datetime ranges (UTC+8)
check_history_and_users_email(user_mentions, channel_id, message_count) → resolves Slack user IDs to emails + retrieves recent messages
get_users_availability(emails, start_time, end_time) → Google Calendar free/busy query
schedule_meeting(title, attendees, start, end, description) → creates Google Calendar event

Testing:

Test each tool in isolation with mock/real data
Verify OAuth token refresh works
Test free/busy with overlapping/non-overlapping calendars

Note: Share your initial Slack + Google Calendar code here so I can integrate it properly.

Milestone 3: Qdrant Memory + Triage Agent
Goal: Memory storage + intent classification
Deliverables:

Qdrant schema for storing user constraints (preferences, hard rules, timestamps)
create_memory_tool(user_id, constraint_text, timestamp) → stores in Qdrant
manage_memory_tool(user_id, action='read'/'update'/'delete') → CRUD operations
Triage Agent:

Classifies: "create new meeting" vs. "update existing meeting"
Extracts constraints from natural language (e.g., "I prefer mornings", "not on Wednesdays")
Stores constraints in memory with timestamps



Testing:

Store sample constraints: "User A prefers mornings" → retrieve later
Test classification: "Schedule a meeting" (create) vs. "Move my 2pm meeting" (update)
Verify timestamp-based memory retrieval


Milestone 4: Analyze Agent + Timeslot Proposal
Goal: Synthesize data and propose meeting times
Deliverables:

Analyze Agent:

Reads memories for all participants (preferences/constraints)
Calls get_users_availability for relevant time window
Applies constraint logic (hard rules = must respect, soft preferences = nice-to-have)
Proposes 2–3 optimal timeslots ranked by preference match
Formats proposals as clear text options



Constraint Resolution Logic:

Hard constraints: "not Wednesdays", "only mornings" → filter out conflicting slots
Soft preferences: "prefer early morning" → rank slots accordingly
Overlaps: flag if any slot conflicts with existing calendar events

Testing:

Scenario 1: All users free → propose best slots
Scenario 2: Conflicting hard constraints → fallback logic
Scenario 3: No perfect match → propose best compromises with explanations


Milestone 5: HITL Agent + Analyze↔HITL Loop
Goal: Human confirmation with iterative refinement
Deliverables:

HITL Agent:

Receives proposals from Analyze Agent
Posts options to Slack channel (text-based, numbered list)
Captures user response (e.g., "Option 2" or "None work, I need afternoon slots")
If confirmed: triggers schedule_meeting and confirms in channel
If rejected: extracts new context/constraints → passes back to Analyze Agent with past_attempts metadata


Analyze↔HITL Loop:

Analyze Agent receives rejection context → refines proposals
Maximum 3 iterations before escalating to "Unable to find suitable time"
Each iteration stores updated constraints in memory



Testing:

Happy path: User confirms option → meeting scheduled
Rejection path: User rejects → provides more context → new proposals
Max retry: After 3 attempts → graceful failure message


Milestone 6: End-to-End Integration
Goal: Complete workflow from Slack mention to scheduled meeting
Deliverables:

Wire all agents into CrewAI sequential crew
Full flow: Slack mention → Triage → Analyze → HITL → Schedule
Error handling (API failures, invalid constraints, no availability)
Logging/observability (track agent decisions, tool calls, timing)
Edge case handling:

Not enough participants mentioned
Meeting duration not specified
Date range unclear



Testing:

Simple: "Schedule 1hr meeting tomorrow with @user1"
Complex: "Schedule 2hr session next week with @user1 @user2. I prefer mornings, not Wednesdays. Check last 10 messages."
Error cases: Invalid users, no availability found


Milestone 7: Polish & Production Prep (Optional for now)

Rate limiting for Slack/Google APIs
Graceful degradation (if Qdrant down, fallback to stateless mode)
User feedback collection ("Was this time good?")
Admin commands (clear memories, debug mode)