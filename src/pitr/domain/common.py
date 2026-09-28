from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import uuid

from pydantic import BaseModel, ConfigDict, Field


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True, json_schema_serialization_defaults_required=True)


class Command(Contract):
    operation_id: str = Field(min_length=1, max_length=200)


class Conflict(ValueError):
    """The caller's expected version or operation identity is stale."""


class Forbidden(ValueError):
    """The current execution cannot access this operation or dependency."""


class BudgetExhausted(ValueError):
    pass


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('时间必须包含时区')
    return result.astimezone(timezone.utc)


def canonical(value) -> str:
    def encode(item):
        if isinstance(item, BaseModel):
            return item.model_dump(mode='json')
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError(type(item).__name__)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, default=encode)


def digest(value) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def uid(prefix: str) -> str:
    return prefix + '_' + uuid.uuid4().hex[:24]
