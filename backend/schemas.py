from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
from datetime import datetime

class Photo(BaseModel):
    url: HttpUrl
    width: Optional[int] = None
    height: Optional[int] = None

class FlameCreate(BaseModel):
    recipient_name: str = Field(..., max_length=100)
    sender_name: Optional[str] = Field(None, max_length=100)
    message: str = Field(..., max_length=5000)
    photos: Optional[List[Photo]] = None
    flame_color: str = Field("red", regex=r"^(red|pink|gold|purple)$")
    tier: str = Field(..., regex=r"^(basic|premium)$")
    schedule_date: Optional[datetime] = None
    allow_public_gallery: bool = False

class Flame(BaseModel):
    id: str
    recipient_name: str
    sender_name: Optional[str]
    message: str
    photos: Optional[List[Photo]]
    flame_color: str
    tier: str
    created_at: datetime
    scheduled_for: Optional[datetime]
    payment_status: str
    slug: str
    burn_start: datetime
    watermark: bool = True

class FlameReply(BaseModel):
    flame_id: str
    message: str = Field(..., max_length=2000)
    sender_name: Optional[str] = Field(None, max_length=100)

class StripeSessionCreate(BaseModel):
    tier: str = Field(..., regex=r"^(basic|premium)$")
    metadata: dict

class StripeWebhook(BaseModel):
    payload: str
    sig_header: str
