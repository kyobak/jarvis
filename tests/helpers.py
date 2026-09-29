from datetime import datetime

from jarvis.brain.context import Context
from jarvis.core.timeutil import KST


def ctx(hour=21, minute=47, status=None, next_event=None, focus=None) -> Context:
    return Context(
        now=datetime(2026, 9, 29, hour, minute, tzinfo=KST),
        user_name="재원",
        status=status or {},
        next_event=next_event,
        focus_session=focus,
    )
