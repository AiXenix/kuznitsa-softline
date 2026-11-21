from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, PrivateAttr


Action = Literal["new","renewal","upgrade","crossgrade","addon","support"]
Metric = Literal["device","user","concurrent","server","core","cpu","vm","mailbox","company","site","storage","other"]
Audience = Literal["business","gov","edu","home","nonprofit","med"]
Delivery = Literal["esd","box","paper","media","service"]
Model = Literal["subscription","perpetual"]


class License(BaseModel):
    action: Action | None = None
    model: Model | None = None
    term_months: int | None = None
    metric: Metric | None = None
    qty_min: int | None = None
    qty_max: int | None = None
    pack: int | None = Field(default=None,ge=1)
    audience: Audience | None = None


class Offer(BaseModel):
    offer_id: str
    name: str
    sku: str | None = None
    vendor: str | None = None
    vendor_id: str | None = None
    family_id: str | None = None
    family_name: str | None = None
    edition: str | None = None
    version: str | None = None
    category_path: list[str] = []
    category_id: str | None = None
    description: str = ""
    attrs: dict[str,str] = {}
    kind: Literal["license","service","course","hardware","other"] = "license"
    lic: License = Field(default_factory=License)
    platforms: list[str] = []
    delivery: Delivery | None = None
    language: str | None = None
    registry: bool | None = None
    certs: list[str] = []
    price: float | None = None
    price_on_request: bool = False
    vat: int | None = None
    available: bool = True
    popularity: float = 0
    margin: float = 0
    sales_90d: int = 0
    views_90d: int = 0
    url: str | None = None
    image: str | None = None

    @property
    def card_id(self):
        return ":".join(filter(None, [self.family_id or self.offer_id, self.edition]))


class Client(BaseModel):
    client_id: str
    title: str
    segment: Literal["smb","mid","enterprise","gov","edu","individual"]
    industry: str = ""
    size_seats: int = 1
    fleet: dict = {}
    region: str = ""
    owned: list[dict] = []
    orders: list[dict] = []
    preferences: dict = {}
    demo: bool = False


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(max_length=300200)
    _authorized_eval: bool = PrivateAttr(default=False)

    @property
    def model_source(self):
        return "authorized_eval" if self.source=="eval" and self._authorized_eval else self.source

    @field_validator("q")
    @classmethod
    def bounded_lines(cls,q):
        lines=q.splitlines()
        if len(lines)>200 or any(len(line)>1500 for line in lines):
            raise ValueError("Допускается до 200 строк длиной до 1500 символов")
        return q
    profile_id: str = "guest"
    category: str | None = None
    session_id: str = ""
    ignore: list[str] = Field(default_factory=list)
    context: Literal["on","off"] = "on"
    verbatim: bool = False
    mode: Literal["smart","fast","naive"] = "smart"
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    filters: dict = {}
    exclude: dict = {}
    weights: dict[str,float] | None = None
    sort: str | None = None
    source: Literal["ui","gallery","compare","api","replay","eval","history"] = "api"
    explain: bool = True

    @classmethod
    def _constraints(cls, data):
        from math import isfinite
        single={"action","audience","model","delivery","deployment","version","origin","metric"}
        multi={"vendor","family","category","edition","certs","platform"}
        clean={}
        for k,v in data.items():
            if k in multi:
                items=v if isinstance(v,list) else [v]
                if not all(isinstance(x,str) for x in items):
                    raise ValueError(k)
                clean[k]=items
            elif k in single and isinstance(v,str) or k=="registry" and isinstance(v,bool):
                clean[k]=v
            elif k in ("price_min","price_max","term_months") and type(v) in (int,float) and isfinite(v) and v>=0:
                clean[k]=v
            else:
                raise ValueError(k)
        return clean


    @field_validator("filters","exclude")
    @classmethod
    def validate_constraints(cls,v):
        return cls._constraints(v)

    @field_validator("weights")
    @classmethod
    def validate_weights(cls,v):
        if v and any(k not in {"pop","pers","rel","margin"} or not 0<=x<=1 for k,x in v.items()):
            raise ValueError("weights")
        return v
