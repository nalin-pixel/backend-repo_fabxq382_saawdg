import os
import secrets
from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import stripe
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

from database import create_document, get_document, get_documents, update_document
from schemas import FlameCreate, Flame, FlameReply

STRIPE_SECRET = os.getenv("STRIPE_SECRET_KEY", "sk_test_123")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_test")
BASE_URL = os.getenv("BASE_URL", "http://localhost:3000")
ADMIN_KEY = os.getenv("ADMIN_KEY", "admin123")

stripe.api_key = STRIPE_SECRET

app = FastAPI(title="Eternal Flame API")

limiter = Limiter(key_func=get_remote_address, default_limits=["20/minute"])  # simple rate limit

app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Too many requests. Please slow down."})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def generate_slug(recipient: str, sender: Optional[str]) -> str:
    base = (recipient or "love").strip().lower().replace(" ", "-")
    if sender:
        base += f"-from-{sender.strip().lower().replace(' ', '-')}"
    rand = secrets.token_urlsafe(9)  # ~12+ unguessable chars
    return f"{base}-{rand}"


def validate_photos(photos):
    if not photos:
        return []
    safe = []
    for p in photos:
        url = str(p.get("url", ""))
        if url.startswith("https://") and any(url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"]):
            safe.append(p)
    return safe[:3]


@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}


@app.post("/flames", response_model=Flame)
@limiter.limit("5/minute")
async def create_flame(payload: FlameCreate):
    slug = generate_slug(payload.recipient_name, payload.sender_name)
    flame_id = secrets.token_urlsafe(12)
    watermark = payload.tier != "premium"
    doc = {
        "id": flame_id,
        "recipient_name": payload.recipient_name.strip(),
        "sender_name": (payload.sender_name or "Anonymous").strip(),
        "message": payload.message,
        "photos": validate_photos([p.dict() for p in (payload.photos or [])]),
        "flame_color": payload.flame_color,
        "tier": payload.tier,
        "scheduled_for": payload.schedule_date.isoformat() if payload.schedule_date else None,
        "payment_status": "pending",
        "slug": slug,
        "burn_start": datetime.utcnow().isoformat(),
        "watermark": watermark,
        "allow_public_gallery": payload.allow_public_gallery,
    }
    create_document("flame", doc)
    return Flame(**doc, created_at=datetime.utcnow())


class CheckoutRequest(BaseModel):
    flame_id: str
    tier: str


@app.post("/checkout")
async def create_checkout_session(req: CheckoutRequest):
    flame = get_document("flame", {"id": req.flame_id})
    if not flame:
        raise HTTPException(status_code=404, detail="Flame not found")
    price_map = {"basic": 499, "premium": 999}
    amount = price_map.get(req.tier)
    if not amount:
        raise HTTPException(status_code=400, detail="Invalid tier")

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        mode="payment",
        allow_promotion_codes=True,
        automatic_tax={"enabled": False},
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Eternal Flame – {req.tier.title()}"},
                "unit_amount": amount
            },
            "quantity": 1,
        }],
        success_url=f"{BASE_URL}/success?flame={flame['slug']}",
        cancel_url=f"{BASE_URL}/cancel?flame={flame['slug']}",
        metadata={"flame_id": flame["id"], "tier": req.tier}
    )
    return {"id": session.id, "url": session.url}


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        flame_id = session.get("metadata", {}).get("flame_id")
        tier = session.get("metadata", {}).get("tier", "basic")
        if flame_id:
            update_document("flame", {"id": flame_id}, {"payment_status": "paid", "tier": tier})
    return {"received": True}


@app.get("/flames/{slug}", response_model=Flame)
async def get_flame(slug: str):
    flame = get_document("flame", {"slug": slug})
    if not flame:
        raise HTTPException(status_code=404, detail="Not found")
    return Flame(**flame, created_at=datetime.utcnow())


@app.post("/flames/{flame_id}/reply")
async def reply_flame(flame_id: str, payload: FlameReply):
    flame = get_document("flame", {"id": flame_id})
    if not flame:
        raise HTTPException(status_code=404, detail="Flame not found")
    if flame.get("tier") != "premium":
        raise HTTPException(status_code=403, detail="Replies available for Premium flames")
    reply_doc = {
        "flame_id": flame_id,
        "message": payload.message,
        "sender_name": payload.sender_name,
        "created_at": datetime.utcnow().isoformat(),
    }
    create_document("reply", reply_doc)
    return {"status": "ok"}


@app.get("/gallery")
async def public_gallery():
    docs = get_documents("flame", {"allow_public_gallery": True, "payment_status": "paid"}, limit=100)
    for d in docs:
        d.pop("_id", None)
    return {"items": docs}


@app.get("/admin/flames")
async def admin_flames(x_admin_key: Optional[str] = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    docs = get_documents("flame", {"payment_status": "paid"}, limit=500)
    for d in docs:
        d.pop("_id", None)
    return {"items": docs}
