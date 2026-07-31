from typing import Literal

from pydantic import BaseModel


class ServiceHealth(BaseModel):
    service: str
    status: Literal["ok", "degraded"] = "ok"
    version: str
