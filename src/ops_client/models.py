"""Pydantic models; fields follow the mock API schema. Money is cents, time is minutes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    created_at: str
    updated_at: str
    version: int


class User(_Row):
    name: str
    email: str
    title: str
    department: str
    active: bool
    cost_rate_cents: int
    bill_rate_cents: int


class Project(_Row):
    code: str
    name: str
    client: str
    status: str
    budget_cents: int
    start_date: str
    end_date: str | None = None


class Task(_Row):
    project_id: int
    name: str
    budget_minutes: int


class TimeEntry(_Row):
    user_id: int
    project_id: int
    task_id: int
    date_performed: str
    minutes: int
    billable: bool
    cost_rate_cents: int
    notes: str


class Approval(_Row):
    user_id: int
    week_start: str
    status: str
    approver_id: int | None = None
    submitted_at: str
    decided_at: str | None = None


MODELS: dict[str, type[_Row]] = {
    "users": User,
    "projects": Project,
    "tasks": Task,
    "time_entries": TimeEntry,
    "approvals": Approval,
}
