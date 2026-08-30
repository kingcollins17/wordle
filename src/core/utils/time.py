from datetime import datetime
from zoneinfo import ZoneInfo

LAGOS_TZ = ZoneInfo("Africa/Lagos")


def get_current_time() -> datetime:
    """Returns the current datetime in Africa/Lagos timezone with tzinfo removed."""
    return datetime.now(LAGOS_TZ).replace(tzinfo=None)
