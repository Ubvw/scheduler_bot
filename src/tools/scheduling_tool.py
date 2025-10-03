from typing import List
import datetime

# Import the actual function from your calendar tools
from .google_calendar_tools import schedule_meeting_on_account


def schedule_final_meeting(
    account_email: str,
    title: str,
    attendees: List[str],
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    description: str = ""
) -> str:
    """
    Schedules the final meeting event on a user's Google Calendar
    after they have confirmed a time slot.
    """
    result = schedule_meeting_on_account(
        account_email=account_email,
        title=title,
        attendees=attendees,
        start_dt=start_dt,
        end_dt=end_dt,
        description=description
    )
    if result:
        return f"Successfully scheduled meeting. Event link: {result.get('htmlLink')}"
    return "Failed to schedule the meeting."