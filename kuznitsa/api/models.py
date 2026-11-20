from typing import Literal
from pydantic import BaseModel, ConfigDict


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["impression","click","cart","order","exit","reformulate","suggest_show","suggest_click","correction_accept","correction_reject","chip","lead"]
    search_id: str | None = None
    session_id: str = ""
    client_id: str = "guest"
    card_id: str | None = None
    offer_id: str | None = None
    position: int | None = None
    qty: int | None = None
    value: float | None = None
    margin_value: float | None = None
    payload: dict = {}
