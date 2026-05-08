from __future__ import annotations

from pydantic import BaseModel


class StoreShortMemoryRequest(BaseModel):
    memory_scope: str = "global"
    user_text: str = ""
    assistant_text: str = ""


class RetrieveMemoryRequest(BaseModel):
    query: str
    memory_scope: str = "global"
    limit: int = 5

