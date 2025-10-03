from __future__ import print_function
import datetime
import os
import re
from typing import List, Dict, Any, Tuple, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDENTIALS_FILE = "credentials.json"  # update if different


def sanitize_email_alias(email_addr: str) -> str:
    local = email_addr.split("@", 1)[0]
    safe = re.sub(r"[^0-9A-Za-z]", "", local)
    if not safe:
        safe = re.sub(r"[^0-9A-Za-z]", "", email_addr)
    return safe


def get_calendar_service_for_email(email_addr: str):
    alias = sanitize_email_alias(email_addr)
    token_path = f"token_{alias}.json"
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def list_all_calendars(service) -> List[Dict[str, Any]]:
    calendars = []
    page_token = None
    while True:
        resp = service.calendarList().list(pageToken=page_token).execute()
        items = resp.get("items", [])
        calendars.extend(items)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return calendars


def query_freebusy_for_calendar_ids(service, calendar_ids: List[str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> Dict[str, Any]:
    """
    Query freebusy for the given calendar IDs using the provided service object.
    Returns the 'calendars' map from the freebusy response.
    """
    time_min = start_dt.isoformat()
    time_max = end_dt.isoformat()

    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": "Asia/Manila",
        "items": [{"id": cid} for cid in calendar_ids],
    }

    resp = service.freebusy().query(body=body).execute()
    return resp.get("calendars", {})


def merge_freebusy_maps(per_account_results: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    per_account_results: list of dicts each with:
      - 'account': account email
      - 'calendar_list': list of (id, summary)
      - 'freebusy': dict mapping calendarId -> { 'busy': [ {start,end}, ... ], ... }
    Returns aggregated map:
      calendarId -> {
        'summary': str|None,
        'accounts': [account_emails],
        'busy': [ { 'start': str, 'end': str }, ... ]  # deduped & sorted
      }
    """
    agg: Dict[str, Dict[str, Any]] = {}

    for res in per_account_results:
        acct = res.get("account")
        cal_list = res.get("calendar_list", [])
        fb = res.get("freebusy", {})

        # store summary info from calendar_list
        for cid, summary in cal_list:
            if cid not in agg:
                agg[cid] = {"summary": summary, "accounts": [], "busy": []}
            else:
                # prefer a non-empty summary if not set
                if not agg[cid].get("summary") and summary:
                    agg[cid]["summary"] = summary

        # merge busy slots
        for cid, caldata in fb.items():
            if cid not in agg:
                agg[cid] = {"summary": None, "accounts": [], "busy": []}
            if acct and acct not in agg[cid]["accounts"]:
                agg[cid]["accounts"].append(acct)

            busy_slots = caldata.get("busy", [])
            for slot in busy_slots:
                # represent slot as tuple for deduping
                start = slot.get("start")
                end = slot.get("end")
                if start is None or end is None:
                    continue
                agg[cid]["busy"].append((start, end))

    # Deduplicate and sort busy slots per calendar, convert back to dicts
    for cid, entry in agg.items():
        seen = set()
        uniq: List[Tuple[str, str]] = []
        for s, e in entry["busy"]:
            key = (s, e)
            if key not in seen:
                seen.add(key)
                uniq.append(key)
        # sort by start time (lexicographic on RFC3339 works)
        uniq.sort(key=lambda x: x[0])
        entry["busy"] = [{"start": s, "end": e} for s, e in uniq]

    return agg


def get_aggregated_freebusy_for_accounts(emails: List[str], start_dt: datetime.datetime, end_dt: datetime.datetime) -> Dict[str, Any]:
    """
    For each account:
      - build service
      - get list of all calendars
      - query freebusy for those calendars
    Then merge results into a single aggregated map and return it.
    """
    per_account_results = []

    for addr in emails:
        print(f"\nProcessing account: {addr}")
        try:
            service = get_calendar_service_for_email(addr)
        except Exception as exc:
            print(f"  Failed to build service for {addr}: {exc}")
            continue

        try:
            calendars = list_all_calendars(service)
            calendar_ids = [c["id"] for c in calendars]
            if not calendar_ids:
                print(f"  No calendars found for {addr}")
                per_account_results.append({
                    "account": addr,
                    "calendar_list": [],
                    "freebusy": {}
                })
                continue

            fb_map = query_freebusy_for_calendar_ids(service, calendar_ids, start_dt, end_dt)

            per_account_results.append({
                "account": addr,
                "calendar_list": [(c.get("id"), c.get("summary")) for c in calendars],
                "freebusy": fb_map
            })

            print(f"  Queried {len(calendar_ids)} calendar(s) for free/busy")
        except HttpError as he:
            print(f"  HttpError for {addr}: {he}")
            per_account_results.append({
                "account": addr,
                "calendar_list": [(c.get("id"), c.get("summary")) for c in (calendars if 'calendars' in locals() else [])],
                "freebusy": {},
                "error": str(he)
            })
        except Exception as e:
            print(f"  Unexpected error for {addr}: {e}")
            per_account_results.append({
                "account": addr,
                "calendar_list": [(c.get("id"), c.get("summary")) for c in (calendars if 'calendars' in locals() else [])],
                "freebusy": {},
                "error": str(e)
            })

    aggregated = merge_freebusy_maps(per_account_results)
    return {
        "queried_accounts": [r.get("account") for r in per_account_results],
        "per_account_results": per_account_results,
        "aggregated": aggregated
    }



def _iso_for_api(dt: datetime.datetime) -> str:
    """
    Return an RFC3339-compatible string for the API.
    - If dt is timezone-aware, use isoformat() (which includes offset).
    - If dt is naive, assume UTC and append 'Z'.
    """
    if dt.tzinfo is None:
        # naive -> treat as UTC (this matches earlier functions which append 'Z')
        return dt.isoformat() + "Z"
    # timezone-aware: use isoformat (e.g. '2025-10-01T12:00:00+00:00')
    return dt.isoformat()

def schedule_meeting_on_account(
    account_email: str,
    title: str,
    attendees: List[str],
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    description: str = "",
    timezone: str = "Asia/Manila",
    calendar_id: str = "primary",
    send_updates: str = "all",   # "all", "externalOnly", or "none"
) -> Optional[dict]:
    """
    Create an event on account_email's calendar.

    Returns: created event dict on success, None on failure.
    """
    # sanity checks
    if start_dt >= end_dt:
        print("start_dt must be before end_dt")
        return None

    # build service for the account (reuses your existing token naming & flow)
    try:
        service = get_calendar_service_for_email(account_email)
    except Exception as exc:
        print(f"Failed to build calendar service for {account_email}: {exc}")
        return None

    event_body = {
        "summary": title,
        "description": description,
        "start": {
            "dateTime": _iso_for_api(start_dt),
            "timeZone": timezone,
        },
        "end": {
            "dateTime": _iso_for_api(end_dt),
            "timeZone": timezone,
        },
        # attendees as dicts
        "attendees": [{"email": a} for a in attendees],
        # default reminders (can be overridden by client)
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "email", "minutes": 24 * 60},
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    try:
        created_event = (
            service.events()
            .insert(calendarId=calendar_id, body=event_body, sendUpdates=send_updates)
            .execute()
        )
        print(f"Event created for {account_email}: {created_event.get('htmlLink')}")
        return created_event
    except HttpError as he:
        print(f"HttpError while creating event for {account_email}: {he}")
        return None
    except Exception as e:
        print(f"Unexpected error while creating event for {account_email}: {e}")
        return None