"""Task-DAG + job models for divide-work orchestration."""
from __future__ import annotations

from pydantic import BaseModel, Field


class DivideTask(BaseModel):
    """One node in the work-division DAG."""

    id: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    status: str = "pending"  # pending|ready|running|done|failed|skipped
    result: str | None = None
    task_id: str | None = None  # TaskIQ task id once enqueued


class DivideJob(BaseModel):
    """A whole divide-work job: the request, its DAG, and the rollup."""

    job_id: str
    module: str
    request: str
    blackboard_task_id: str
    tasks: list[DivideTask] = Field(default_factory=list)
    status: str = "decomposing"  # decomposing|running|done|failed
    summary: str | None = None
