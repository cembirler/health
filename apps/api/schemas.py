"""Pydantic response models. Only what `/api/meta/health` returns now —
agent endpoints build responses inline in routers/agent.py."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class SingleResponse(BaseModel, Generic[T]):
    data: T


class HealthStatus(BaseModel):
    status: str
    db: str
    as_of: str
