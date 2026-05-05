"""Pydantic schemas for the commitment plan import API.

All models use extra="forbid" to reject unknown fields before any DB writes.
Position is server-assigned; exercise order is preserved from the payload array.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

_VALID_METRICS = {"reps", "minutes", "kg"}
_VALID_PROGRESSION_METRICS = {"reps", "minutes", "kg"}


class ImportExerciseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    target: int = Field(gt=0)
    metric: str = Field(default="reps")
    progression_metric: str = Field(default="reps")

    @field_validator("metric")
    @classmethod
    def validate_metric(cls, v: str) -> str:
        if v not in _VALID_METRICS:
            raise ValueError(f"metric must be one of {sorted(_VALID_METRICS)}")
        return v

    @field_validator("progression_metric")
    @classmethod
    def validate_progression_metric(cls, v: str) -> str:
        if v not in _VALID_PROGRESSION_METRICS:
            raise ValueError(f"progression_metric must be one of {sorted(_VALID_PROGRESSION_METRICS)}")
        return v


class ImportScheduleDay(BaseModel):
    model_config = ConfigDict(extra="forbid")

    day: date
    rest: bool = False
    exercises: list[ImportExerciseSpec] = Field(default_factory=list)

    @field_validator("exercises")
    @classmethod
    def validate_exercises(cls, v: list, info) -> list:
        if not info.data.get("rest", False) and len(v) == 0:
            raise ValueError("workout days must have at least 1 exercise")
        if len(v) > 5:
            raise ValueError("maximum 5 exercises per workout day")
        return v


class CommitmentImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    schedule: list[ImportScheduleDay] = Field(min_length=1, max_length=200)

    @field_validator("end_date")
    @classmethod
    def validate_end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v < start:
            raise ValueError("end_date must be on or after start_date")
        return v


class CommitmentImportResult(BaseModel):
    dry_run: bool
    commitment_id: str | None = None
    already_exists: bool = False
    workout_days: int
    rest_days: int
    exercise_count: int
