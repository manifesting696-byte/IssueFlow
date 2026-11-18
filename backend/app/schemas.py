from enum import StrEnum
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class Category(StrEnum):
    system_fault = 'system_fault'
    permission_request = 'permission_request'
    feature_suggestion = 'feature_suggestion'
    usage_consultation = 'usage_consultation'
    uncertain = 'uncertain'


class Status(StrEnum):
    pending = 'pending'
    in_progress = 'in_progress'
    completed = 'completed'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Content(Input):
    content: StrictStr

    @field_validator('content')
    @classmethod
    def check_content(cls, value):
        if not value.strip():
            raise ValueError('INVALID_CONTENT')
        if len(value) > 5000:
            raise ValueError('CONTENT_TOO_LONG')
        return value


class TicketCreate(Content):
    request_id: Annotated[StrictStr, Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')]


class Version(Input):
    expected_version: Annotated[int, Field(ge=1)]


class ContentUpdate(Content, Version):
    pass


class StatusUpdate(Version):
    status: Status = Field(strict=False)


class CategoryUpdate(Version):
    category: Category = Field(strict=False)
    reason: Annotated[StrictStr, Field(max_length=1000)]

    @field_validator('reason')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('原因不能为空')
        return value


class Clarification(Version):
    message: Annotated[StrictStr, Field(max_length=1000)]

    @field_validator('message')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('补充要求不能为空')
        return value


class Login(Input):
    username: Annotated[StrictStr, Field(min_length=1, max_length=50)]
    password: Annotated[StrictStr, Field(min_length=1, max_length=200)]


class LLMOutput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    category: Category
    evidence: Annotated[StrictStr, Field(max_length=5000)]
    reason: Annotated[StrictStr, Field(min_length=1, max_length=500)]
