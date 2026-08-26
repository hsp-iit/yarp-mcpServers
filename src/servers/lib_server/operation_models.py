"""Typed state shared by asynchronous YARP operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


OperationStatus = Literal["working", "completed", "failed", "cancelled"]


class OperationSnapshot(BaseModel):
    """Authoritative snapshot exposed through an MCP resource."""

    operation_id: str
    operation_type: str
    status: OperationStatus
    status_message: str | None = None
    progress: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime
    updated_at: datetime
    poll_interval_ms: int = Field(default=1000, gt=0)
    status_uri: str
    details: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    revision: int = Field(default=0, ge=0)


class StartOperationResult(BaseModel):
    """Structured result returned when a server accepts background work."""

    success: bool = True
    operation_id: str
    operation_type: str
    status: OperationStatus = "working"
    status_uri: str
    poll_interval_ms: int
    message: str


class OperationErrorResult(BaseModel):
    """Structured domain-level rejection returned before work is accepted."""

    success: Literal[False] = False
    error: str


class OperationListResult(BaseModel):
    """Structured list result for operation-management tools."""

    operations: list[OperationSnapshot]
    total: int
    active: int
