"""
Proof Verification Graph

A bounded LangGraph StateGraph that coordinates task proof verification.
The graph state is fully JSON-serializable. DB sessions are passed
out-of-band via RunnableConfig(configurable={"db": db}).

Image analysis uses Gemini when configured. Unconfigured, ambiguous, or
low-confidence proofs are held for supervisor review. High-confidence AI
approval remains opt-in through ENABLE_AUTOMATED_PROOF_APPROVAL.
"""

from typing import TypedDict, Optional

from langgraph.graph import StateGraph, END
from langchain_core.runnables import RunnableConfig


class ProofVerificationState(TypedDict):
    """Serializable graph state for proof verification sub-flow."""
    work_id: int
    proof_image_path: str
    proof_verified: bool
    verification_confidence: Optional[float]
    verification_rationale: str
    review_required: bool
    decision: str
    proof_id: Optional[int]


def inspect_proof_node(state: ProofVerificationState, config: RunnableConfig) -> dict:
    """Run image verification and persist the verification decision."""
    db = config["configurable"]["db"]
    from app.agents.task_verification_agent import verify_task_proof

    return verify_task_proof(
        work_id=state["work_id"],
        proof_image_path=state["proof_image_path"],
        db=db,
        workflow_id=config["configurable"].get("workflow_id"),
    )


def supervisor_gate_node(state: ProofVerificationState, config: RunnableConfig) -> dict:
    """Keep ambiguous/unconfigured proofs pending for supervisor review."""
    return {"proof_verified": False, "review_required": True}


def auto_approve_node(state: ProofVerificationState, config: RunnableConfig) -> dict:
    """Persist an enabled, high-confidence AI approval."""
    from app.agents.task_verification_agent import approve_task_proof

    approve_task_proof(state["proof_id"], config["configurable"]["db"])
    return {
        "proof_verified": True,
        "review_required": False,
    }


def auto_reject_node(state: ProofVerificationState, config: RunnableConfig) -> dict:
    """Persist a high-confidence rejection without completing the work item."""
    from app.agents.task_verification_agent import reject_task_proof

    reject_task_proof(
        state["proof_id"],
        state["verification_rationale"],
        config["configurable"]["db"],
    )
    return {"proof_verified": False, "review_required": False}


def route_verification_result(state: ProofVerificationState) -> str:
    """Route AI decisions to approval, rejection, or the human gate."""
    if state.get("review_required", True):
        return "supervisor_gate"
    if state.get("decision") == "VERIFIED":
        return "auto_approve"
    return "auto_reject"


def build_proof_verification_graph() -> StateGraph:
    """Build and compile the proof verification StateGraph.

    Compiled without a persistent checkpointer since the orchestrator's
    OrchestratorTrace, ApprovalRequest, AgentActionLog, and TaskProof
    tables remain the system authority for workflow state.
    """
    builder = StateGraph(ProofVerificationState)

    builder.add_node("inspect_proof", inspect_proof_node)
    builder.add_node("supervisor_gate", supervisor_gate_node)
    builder.add_node("auto_approve", auto_approve_node)
    builder.add_node("auto_reject", auto_reject_node)

    builder.set_entry_point("inspect_proof")
    builder.add_conditional_edges(
        "inspect_proof",
        route_verification_result,
        {
            "supervisor_gate": "supervisor_gate",
            "auto_approve": "auto_approve",
            "auto_reject": "auto_reject",
        },
    )
    builder.add_edge("supervisor_gate", END)
    builder.add_edge("auto_approve", END)
    builder.add_edge("auto_reject", END)

    return builder.compile()


# Module-level compiled graph instance
proof_verification_graph = build_proof_verification_graph()
