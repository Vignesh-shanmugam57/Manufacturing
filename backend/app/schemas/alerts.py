from typing import Literal

from pydantic import BaseModel, Field


class AlertStatusIn(BaseModel):
    """Human workflow step. VERIFIED is never set by hand: it comes from the telemetry check."""
    status: Literal["ACKNOWLEDGED", "RESOLVED", "OPEN"]
    note: str = Field(default="", max_length=1000)


class AlertAssignIn(BaseModel):
    """Give an alert to a team or a person. Every change is recorded with who made it."""
    assignee: str = Field(min_length=2, max_length=40)


class AlertCreate(BaseModel):
    """A person (or another system) raises an advisory alert by hand."""
    utility_type: str = Field(min_length=1, max_length=30)
    title: str = Field(min_length=3, max_length=200)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    recommendation: str = Field(default="", max_length=2000)
    details: str = Field(default="", max_length=4000)
    plant_id: str | None = None
    zone: str | None = None
    assigned_to: str = Field(default="maintenance", max_length=40)
