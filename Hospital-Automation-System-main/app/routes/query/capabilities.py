from fastapi import APIRouter
from typing import List

from app.orchestrator.intelligence.registry import default_registry
from app.schemas.capability import CapabilityResponse

router = APIRouter(prefix="/capabilities", tags=["Query - Capabilities"])


@router.get("/", response_model=List[CapabilityResponse])
def list_all_capabilities():
    caps = default_registry.list_capabilities()
    return [
        CapabilityResponse(
            name=c.name,
            agent_name=c.agent_name,
            handles_events=list(c.handles_events),
            requires=list(c.requires),
            produces=list(c.produces),
            priority=c.priority,
            continue_on_failure=c.continue_on_failure,
            description=c.description,
        )
        for c in caps
    ]


@router.get("/agent/{agent_name}", response_model=List[CapabilityResponse])
def get_capabilities_for_agent(agent_name: str):
    caps = [
        c for c in default_registry.list_capabilities()
        if c.agent_name == agent_name.upper()
    ]
    return [
        CapabilityResponse(
            name=c.name,
            agent_name=c.agent_name,
            handles_events=list(c.handles_events),
            requires=list(c.requires),
            produces=list(c.produces),
            priority=c.priority,
            continue_on_failure=c.continue_on_failure,
            description=c.description,
        )
        for c in caps
    ]


@router.get("/events")
def list_supported_events():
    all_caps = default_registry.list_capabilities()
    event_map = {}
    for c in all_caps:
        for event in c.handles_events:
            event_map.setdefault(event, []).append(c.agent_name)
    return event_map
