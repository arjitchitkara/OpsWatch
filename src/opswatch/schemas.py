from datetime import datetime

from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MonitorBase(BaseModel):
    """Shared fields for monitor API requests and responses."""

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)
    method: str = Field(default="GET", pattern="^(GET|HEAD)$")
    expected_status: int = Field(default=200, ge=100, le=599)
    expected_body: str | None = None
    interval_seconds: int = Field(default=60, ge=5, le=86400)
    timeout_seconds: int = Field(default=5, ge=1, le=120)
    failure_threshold: int = Field(default=3, ge=1, le=20)
    recovery_threshold: int = Field(default=2, ge=1, le=20)
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        """Require a complete HTTP or HTTPS URL."""

        parsed_url = urlsplit(value)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("Enter a complete HTTP or HTTPS URL")
        return value


class MonitorCreate(MonitorBase):
    """Data required to create a monitor."""

    pass


class MonitorUpdate(BaseModel):
    """Fields that can be changed on an existing monitor."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=1, max_length=2048)
    method: str | None = Field(default=None, pattern="^(GET|HEAD)$")
    expected_status: int | None = Field(default=None, ge=100, le=599)
    expected_body: str | None = None
    interval_seconds: int | None = Field(default=None, ge=5, le=86400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    failure_threshold: int | None = Field(default=None, ge=1, le=20)
    recovery_threshold: int | None = Field(default=None, ge=1, le=20)
    enabled: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str | None) -> str | None:
        """Require a complete HTTP or HTTPS URL when one is provided."""

        if value is None:
            return value
        parsed_url = urlsplit(value)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
            raise ValueError("Enter a complete HTTP or HTTPS URL")
        return value


class MonitorRead(MonitorBase):
    """Monitor data returned by the API."""

    id: int
    status: str
    last_checked_at: datetime | None
    last_status_code: int | None
    last_response_time_ms: int | None
    last_error_type: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MonitorCheckRead(BaseModel):
    """Monitor check data returned by the API."""

    id: int
    monitor_id: int
    checked_at: datetime
    success: bool
    status_code: int | None
    response_time_ms: int | None
    error_type: str | None
    error_message: str | None

    model_config = ConfigDict(from_attributes=True)


class IncidentUpdate(BaseModel):
    """Fields that can be changed on an existing incident."""

    status: str | None = Field(default=None, pattern="^(open|acknowledged|resolved)$")
    severity: str | None = Field(default=None, pattern="^(info|warning|critical)$")
    notes: str | None = None


class IncidentRead(BaseModel):
    """Incident data returned by the API."""

    id: int
    monitor_id: int
    title: str
    severity: str
    status: str
    started_at: datetime
    acknowledged_at: datetime | None
    resolved_at: datetime | None
    failure_reason: str | None
    notes: str | None

    model_config = ConfigDict(from_attributes=True)
