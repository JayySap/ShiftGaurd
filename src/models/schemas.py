"""Pydantic schemas for data validation and serialization.

This module defines the data models used throughout ShiftGuard for
type-safe data handling and API request/response validation.
"""

from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ShiftStatus(str, Enum):
    """Enumeration of possible shift states."""

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    AWAITING_RESPONSE = "AWAITING_RESPONSE"


class FeedbackAction(str, Enum):
    """Enumeration of employee feedback actions."""

    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REQUEST_SWAP = "REQUEST_SWAP"


class ReasonCategory(str, Enum):
    """Enumeration of decline reason categories."""

    SICK = "SICK"
    DISTANCE = "DISTANCE"
    BURNOUT = "BURNOUT"
    OTHER = "OTHER"


class EmployeeBase(BaseModel):
    """Base schema for employee data.

    Attributes:
        full_name: Employee's full legal name.
        email: Employee's email address (unique identifier).
        phone_number: Optional contact phone number.
        role: Job role/title (e.g., 'Barista', 'Shift Lead').
        max_weekly_hours: Maximum hours this employee can work per week.
        waived_notice_period: Whether employee waived 96h notice right (Ontario).
    """

    full_name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    phone_number: Optional[str] = Field(default=None, max_length=20)
    role: str = Field(default="Staff", max_length=100)
    max_weekly_hours: int = Field(default=40, ge=1, le=168)
    waived_notice_period: bool = Field(default=False)


class EmployeeCreate(EmployeeBase):
    """Schema for creating a new employee."""

    pass


class Employee(EmployeeBase):
    """Full employee schema with database fields.

    Attributes:
        id: Unique identifier (UUID).
        created_at: Timestamp of record creation.
        is_active: Whether the employee is currently active.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    is_active: bool = True


class AvailabilityBase(BaseModel):
    """Base schema for availability data.

    Attributes:
        shift_date: The date this availability applies to.
        can_open: Available for opening shifts (e.g., 5 AM - 1 PM).
        can_close: Available for closing shifts (e.g., 1 PM - 10 PM).
        note: Optional constraints or notes.
    """

    shift_date: date
    can_open: bool = Field(default=False)
    can_close: bool = Field(default=False)
    note: Optional[str] = Field(default=None, max_length=500)


class AvailabilityCreate(AvailabilityBase):
    """Schema for creating/updating availability."""

    employee_email: EmailStr


class Availability(AvailabilityBase):
    """Full availability schema with database fields.

    Attributes:
        id: Unique identifier (serial).
        employee_id: Reference to the employee.
        submitted_at: Timestamp of submission.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: UUID
    submitted_at: datetime


class ShiftBase(BaseModel):
    """Base schema for shift data.

    Attributes:
        start_time: Shift start timestamp with timezone.
        end_time: Shift end timestamp with timezone.
        status: Current state of the shift.
    """

    start_time: datetime
    end_time: datetime
    status: ShiftStatus = Field(default=ShiftStatus.DRAFT)


class ShiftCreate(ShiftBase):
    """Schema for creating a new shift.

    Attributes:
        employee_id: UUID of the assigned employee.
        is_clopen_violation: Whether this shift creates a clopening violation.
        violation_reason: Explanation if violation exists.
        manager_override_reason: Justification for approving a violation.
    """

    employee_id: UUID
    is_clopen_violation: bool = Field(default=False)
    violation_reason: Optional[str] = Field(default=None, max_length=500)
    manager_override_reason: Optional[str] = Field(default=None, max_length=500)


class Shift(ShiftCreate):
    """Full shift schema with database fields.

    Attributes:
        id: Unique identifier (UUID).
        created_at: Timestamp of record creation.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class ShiftWithEmployee(Shift):
    """Shift schema including employee details.

    Attributes:
        employee: The assigned employee's details.
    """

    employee: Optional[Employee] = None


class ShiftFeedbackCreate(BaseModel):
    """Schema for creating shift feedback.

    Attributes:
        shift_id: UUID of the shift being responded to.
        employee_id: UUID of the responding employee.
        action: The action taken (accept/decline/swap).
        reason_category: Category of reason if declining.
        reason_text: Detailed explanation for AI training.
    """

    shift_id: UUID
    employee_id: UUID
    action: FeedbackAction
    reason_category: Optional[ReasonCategory] = None
    reason_text: Optional[str] = Field(default=None, max_length=1000)


class ShiftFeedback(ShiftFeedbackCreate):
    """Full feedback schema with database fields.

    Attributes:
        id: Unique identifier (UUID).
        created_at: Timestamp of feedback submission.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class GoogleFormPayload(BaseModel):
    """Schema for incoming Google Forms webhook payload.

    Attributes:
        email: Respondent's email address.
        dates: List of dates with availability.
        can_open_dates: Dates available for opening shifts.
        can_close_dates: Dates available for closing shifts.
        notes: Optional notes per date (date -> note mapping).
    """

    email: EmailStr
    dates: list[date]
    can_open_dates: list[date] = Field(default_factory=list)
    can_close_dates: list[date] = Field(default_factory=list)
    notes: dict[str, str] = Field(default_factory=dict)


class ScheduleGenerationResult(BaseModel):
    """Result of schedule generation.

    Attributes:
        shifts_created: Number of shifts created.
        violations_flagged: Number of compliance violations detected.
        unassigned_slots: Number of slots that couldn't be filled.
        shifts: List of created shift objects.
    """

    shifts_created: int
    violations_flagged: int
    unassigned_slots: int
    shifts: list[Shift]


class CalendarPublishResult(BaseModel):
    """Result of calendar publishing operation.

    Attributes:
        sent: Number of calendar invites successfully sent.
        failed: Number of failed invite attempts.
        errors: List of error messages for failed invites.
    """

    sent: int
    failed: int
    errors: list[str] = Field(default_factory=list)
