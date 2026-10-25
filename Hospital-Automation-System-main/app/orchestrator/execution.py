"""
Orchestrator Execution Utilities

Provides the ExecutionStep schema, the AgentExecutionError custom exception,
and the record_step helper used across all workflows and agents.
"""

from typing import TypedDict, List


class ExecutionStep(TypedDict, total=False):
    """Schema for a single agent execution trace entry."""
    agent: str
    status: str
    capability: str
    message: str


class AgentExecutionError(Exception):
    """
    Raised when an agent fails during workflow execution.

    Attributes:
        agent:           Name of the agent that failed (use constants.py).
        message:         Human-readable failure description.
        completed_steps: Execution steps that succeeded before this failure.
        metadata:        Workflow-specific context (work_id, request_id, status, etc.).
    """

    def __init__(
        self,
        agent: str,
        message: str,
        completed_steps: List[ExecutionStep] = None,
        metadata: dict = None,
    ):
        self.agent = agent
        self.message = message
        self.completed_steps = completed_steps or []
        self.metadata = metadata or {}
        super().__init__(f"{agent} failed: {message}")


class GracefulWorkflowAbort(Exception):
    """Raised when a capability handler decides to abort the workflow gracefully.

    This is not a failure. The executor will stop running subsequent steps,
    merge the metadata into context.produced, set context.status, and
    return without recording a failed trace entry.

    Attributes:
        status:   Custom status string for the response envelope
                  (e.g. "ALREADY_PROCESSED").
        message:  Human-readable reason for the abort.
        metadata: Key-value pairs merged into context.produced so they
                  appear in the final response (e.g. request_id).
    """

    def __init__(self, status: str, message: str, metadata: dict = None):
        self.status = status
        self.message = message
        self.metadata = metadata or {}
        super().__init__(message)


class WorkflowPausedException(Exception):
    """Raised when execution is suspended awaiting supervisor action.

    The executor raises this instead of silently breaking when it detects
    a GracefulWorkflowAbort with a pause-compatible status. The orchestrator
    catches it to persist the remaining plan steps and context state.

    Attributes:
        status:          Status string (e.g. "PENDING_HUMAN_APPROVAL").
        message:         Human-readable reason for the pause.
        remaining_steps: List of PlanStep objects not yet executed.
        metadata:        Key-value pairs from the abort that triggered the pause.
    """

    def __init__(
        self,
        status: str,
        message: str,
        remaining_steps: list,
        metadata: dict = None,
    ):
        self.status = status
        self.message = message
        self.remaining_steps = remaining_steps
        self.metadata = metadata or {}
        super().__init__(message)


def record_step(workflow: List[ExecutionStep], agent: str, status: str, capability: str = None):
    """Append an execution step to the workflow trace."""
    step = {
        "agent": agent,
        "status": status,
    }
    if capability:
        step["capability"] = capability
    workflow.append(step)
