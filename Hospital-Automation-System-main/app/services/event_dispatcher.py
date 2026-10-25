"""
Event Dispatcher -- Background Infrastructure

Provides a single reusable function for dispatching hospital events
to the Event Agent in a background task.  This is infrastructure,
not business logic.

Used by:
    - Event Gateway route   (POST /events)
    - Supervisor route      (POST /supervisor-task-requests)
    - Any future route that needs to fire an event
"""

from app.models.enums import HospitalEventEnum


def dispatch_event(event_type: HospitalEventEnum, payload: dict):
    """
    Execute event processing in a background-safe context.

    Creates its own DB session (not request-scoped) and forwards
    the event to the Event Agent for validation + orchestration.
    """
    from app.database.connection import SessionLocal
    from app.agents.event_agent import publish_event

    db = SessionLocal()
    try:
        publish_event(event_type, payload, db)
    except Exception as exc:
        print(f"[EVENT_DISPATCHER] Background processing failed: {exc}")
    finally:
        db.close()
