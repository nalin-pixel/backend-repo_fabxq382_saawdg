import os
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from database import db, create_document, get_documents
from schemas import FlameCreate, FlameReply

import stripe
from fastapi.responses import JSONResponse
import requests
from bson import ObjectId

# Environment
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
ADMIN_KEY = os.getenv("ADMIN_KEY", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "*")
HCAPTCHA_SECRET = os.getenv("HCAPTCHA_SECRET", "")

# Stripe init if key present
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

app = FastAPI(title="Eternal Flame API")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*" if FRONTEND_URL == "*" else FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


@app.get("/test")
async def test_database():
    response: Dict[str, Any] = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
                response["connection_status"] = "Connected"
                response["database_url"] = "✅ Set"
                response["database_name"] = db.name
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
        else:
            response["database"] = "⚠️ Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"

    return response


# Helper: create slug
def generate_slug(recipient: str, sender: str) -> str:
    base = f"{recipient.strip().lower()}-{sender.strip().lower()}".replace(" ", "-")
    token = secrets.token_urlsafe(9)  # ~12+ chars
    return f"{base}-{token}"


def verify_hcaptcha(token: Optional[str]) -> bool:
    """Verify hCaptcha token with remote service. If no secret configured, allow in development."""
    if not HCAPTCHA_SECRET:
        return True  # Dev mode
    if not token:
        return False
    try:
        r = requests.post("https://hcaptcha.com/siteverify", data={
            "secret": HCAPTCHA_SECRET,
            "response": token,
        }, timeout=5)
        data = r.json()
        return bool(data.get("success"))
    except Exception:
        return False


# Create draft flame
@app.post("/flames")
async def create_flame(payload: dict):
    try:
        captcha_token = payload.pop("captcha_token", None)
        if not verify_hcaptcha(captcha_token):
            raise HTTPException(status_code=400, detail="CAPTCHA failed")
        obj = FlameCreate(**payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    slug = generate_slug(obj.recipient_name, obj.sender_name)

    doc = obj.model_dump()
    doc.update({
        "slug": slug,
        "payment_status": "unpaid",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })

    inserted_id = create_document("flame", doc)

    return {"id": inserted_id, "slug": slug, "payment_status": "unpaid"}


# Stripe Checkout session
@app.post("/checkout")
async def checkout(payload: dict, request: Request):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=400, detail="Stripe not configured")

    flame_id: Optional[str] = payload.get("flame_id")
    tier: str = payload.get("tier", "basic")

    if not flame_id:
        raise HTTPException(status_code=422, detail="flame_id required")

    price = 499 if tier == "basic" else 999

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"Eternal Flame • {tier.title()}"},
                    "unit_amount": price,
                },
                "quantity": 1,
            }],
            success_url=f"{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/cancel",
            metadata={"flame_id": flame_id, "tier": tier},
            automatic_tax={"enabled": True},
            allow_promotion_codes=True,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"id": session.id, "url": session.url}


# Stripe webhook
@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=400, detail="Webhook not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {str(e)}")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        flame_id = session.get("metadata", {}).get("flame_id")
        if flame_id and db:
            try:
                db["flame"].update_one({"_id": ObjectId(flame_id)}, {"$set": {"payment_status": "paid", "updated_at": datetime.now(timezone.utc)}})
            except Exception:
                pass

    return {"received": True}


# Retrieve flame by slug
@app.get("/flames/{slug}")
async def get_flame(slug: str):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    doc = db["flame"].find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Flame not found")

    doc["id"] = str(doc.pop("_id"))
    return doc


# Premium reply
@app.post("/flames/{flame_id}/reply")
async def reply_flame(flame_id: str, payload: dict):
    try:
        _ = FlameReply(flame_id=flame_id, **payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())

    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")

    payload["flame_id"] = flame_id
    payload["created_at"] = datetime.now(timezone.utc)
    create_document("flamereply", payload)
    return {"ok": True}


# Gallery (public opt-in)
@app.get("/gallery")
async def gallery():
    docs = get_documents("flame", {"allow_public_gallery": True, "payment_status": "paid"}, limit=100)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}


# Admin view
@app.get("/admin/flames")
async def admin_flames(x_admin_key: Optional[str] = Header(None)):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    docs = get_documents("flame", {"payment_status": "paid"}, limit=200)
    for d in docs:
        d["id"] = str(d.pop("_id"))
    return {"items": docs}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
