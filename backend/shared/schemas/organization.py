"""Client-safe organization response contracts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PersonalOrganizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    role: Literal["owner"]
    created_at: datetime
