from pydantic import BaseModel, Field, HttpUrl, field_validator
from typing import List, Optional, Literal
from datetime import datetime

# Eternal Flame Schemas

Tier = Literal['basic', 'premium']

class FlameCreate(BaseModel):
    recipient_name: str = Field(..., min_length=1, max_length=80)
    sender_name: str = Field(..., min_length=1, max_length=80)
    message: str = Field(..., min_length=10, max_length=4000)
    photos: Optional[List[HttpUrl]] = Field(default=None, description="Up to 3 image URLs")
    flame_color: Optional[str] = Field(default="#FF4D4D", description="Hex color for flame accent")
    tier: Tier = Field(default='basic')
    schedule_date: Optional[datetime] = Field(default=None, description="If set, intended reveal date/time (UTC)")
    allow_public_gallery: bool = Field(default=False)

    @field_validator('photos')
    @classmethod
    def validate_photos(cls, v):
        if v is None:
            return v
        if len(v) > 3:
            raise ValueError('Maximum 3 photos allowed')
        allowed = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
        for url in v:
            if not any(str(url).lower().endswith(ext) for ext in allowed):
                raise ValueError('Photo URLs must end with image extensions')
        return v

class Flame(BaseModel):
    id: str
    slug: str
    recipient_name: str
    sender_name: str
    message: str
    photos: Optional[List[HttpUrl]] = None
    flame_color: Optional[str] = None
    tier: Tier
    schedule_date: Optional[datetime] = None
    allow_public_gallery: bool = False
    payment_status: Literal['unpaid','paid','refunded','failed'] = 'unpaid'
    is_revealed: bool = True
    revealed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

class FlameReply(BaseModel):
    flame_id: str
    message: str = Field(..., min_length=3, max_length=2000)
