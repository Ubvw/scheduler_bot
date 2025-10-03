import datetime
import pytz

# Always operate in UTC+8 (e.g., Singapore/Manila time)
TIMEZONE = pytz.timezone('Asia/Manila')

def get_current_datetime_info() -> dict:
    """
    Returns the current TIME, DATE, and DAY in Asia/Manila timezone (UTC+8).
    """
    reference_date = datetime.datetime.now(TIMEZONE)

    return {
        "time": reference_date.strftime("%H:%M:%S"),   # e.g., "23:46:05"
        "date": reference_date.strftime("%Y-%m-%d"),   # e.g., "2025-10-01"
        "day": reference_date.strftime("%A")           # e.g., "Wednesday"
    }

# Example usage
print(get_current_datetime_info())