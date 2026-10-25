"""
LangGraph Adapter

Thin bridge between the Python orchestrator's adapter layer and the
LangGraph proof verification sub-flow. Passes the SQLAlchemy DB session
out-of-band via RunnableConfig so graph state remains serializable.

Returns the decision, confidence, rationale, and review state to the capability
adapter. Database writes remain owned by the verification agent/domain services.
"""

from sqlalchemy.orm import Session


def _ensure_langgraph_debug_compatibility() -> None:
    """Bridge langchain-core 0.3's legacy debug lookup with newer installs."""
    import langchain

    if not hasattr(langchain, "debug"):
        from langchain_core.globals import set_debug

        set_debug(False)


def run_langgraph_proof_verification(
    db: Session,
    work_id: int,
    proof_image_path: str,
    workflow_id: str = None,
) -> dict:
    """Execute the proof verification graph as a stateless subroutine.

    The graph coordinates the proof inspection and routing decision.
    DB session is never stored in graph state.
    """
    from app.orchestrator.graphs.proof_verification_graph import proof_verification_graph

    _ensure_langgraph_debug_compatibility()
    initial_state = {
        "work_id": work_id,
        "proof_image_path": proof_image_path,
        "proof_verified": False,
        "verification_confidence": None,
        "verification_rationale": "",
        "review_required": True,
        "decision": "NEEDS_REVIEW",
        "proof_id": None,
    }

    config = {
        "configurable": {
            "db": db,
            "workflow_id": workflow_id,
        }
    }

    final_state = proof_verification_graph.invoke(initial_state, config=config)
    if final_state.get("review_required", True):
        decision = "NEEDS_REVIEW"
    elif final_state.get("proof_verified", False):
        decision = "APPROVED"
    elif final_state.get("decision") == "REJECTED":
        decision = "REJECTED"
    else:
        decision = "NEEDS_REVIEW"

    return {
        "proof_verified": final_state.get("proof_verified", False),
        "verification_confidence": final_state.get("verification_confidence"),
        "verification_rationale": final_state.get("verification_rationale", ""),
        "review_required": final_state.get("review_required", True),
        "decision": decision,
        "proof_id": final_state.get("proof_id"),
    }
