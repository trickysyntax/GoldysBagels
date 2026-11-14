"""
Goldy's Bagels — Stripe Checkout API
Creates Stripe Checkout Sessions for bagel preorders with optional tips.
"""
import os
import smtplib
import stripe
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional

# Stripe secret key from environment
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

app = FastAPI(title="Goldy's Bagels API")

# CORS — allow the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://goldysbagels.com", "http://goldysbagels.com", "http://localhost"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Pricing constants (in cents)
BAGEL_PRICE = 200       # $2.00
HALF_DOZEN_PRICE = 1000  # $10.00
DOZEN_PRICE = 1800       # $18.00

class OrderItem(BaseModel):
    name: str
    quantity: int

class CheckoutRequest(BaseModel):
    name: str
    phone: str
    notes: Optional[str] = ""
    items: List[OrderItem]
    total_bagels: int
    subtotal: int  # in dollars, calculated with bundle pricing
    tip_amount: int  # in dollars, 0 if no tip

def calculate_total(qty: int) -> int:
    """Calculate total in cents with bundle pricing."""
    if qty >= 12:
        dozens = qty // 12
        remainder = qty % 12
        price = dozens * DOZEN_PRICE
        if remainder >= 6:
            price += HALF_DOZEN_PRICE
            price += (remainder - 6) * BAGEL_PRICE
        else:
            price += remainder * BAGEL_PRICE
        return price
    elif qty >= 6:
        return HALF_DOZEN_PRICE + (qty - 6) * BAGEL_PRICE
    return qty * BAGEL_PRICE

@app.get("/api/health")
async def health():
    return {"status": "ok", "stripe_configured": bool(stripe.api_key)}

@app.post("/api/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe not configured")

    # Recalculate subtotal server-side to prevent tampering
    subtotal_cents = calculate_total(req.total_bagels)
    subtotal_dollars = subtotal_cents // 100

    # Build order description
    order_desc = ", ".join(f"{item.quantity}x {item.name}" for item in req.items if item.quantity > 0)

    # Build line items
    line_items = [{
        "price_data": {
            "currency": "usd",
            "product_data": {
                "name": f"Goldy's Bagels Preorder ({req.total_bagels} bagels)",
                "description": order_desc,
            },
            "unit_amount": subtotal_cents,
        },
        "quantity": 1,
    }]

    # Add tip if provided
    tip_cents = req.tip_amount * 100 if req.tip_amount > 0 else 0
    if tip_cents > 0:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": "Tip for Goldy's Bagels",
                },
                "unit_amount": tip_cents,
            },
            "quantity": 1,
        })

    # Build metadata
    metadata = {
        "customer_name": req.name,
        "customer_phone": req.phone,
        "order_details": order_desc,
        "total_bagels": str(req.total_bagels),
        "subtotal": str(subtotal_dollars),
        "tip": str(req.tip_amount),
    }
    if req.notes:
        metadata["notes"] = req.notes[:500]  # Stripe metadata value limit

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=line_items,
            metadata=metadata,
            customer_email=None,  # collected by Stripe
            success_url="https://goldysbagels.com/?status=success",
            cancel_url="https://goldysbagels.com/?status=cancelled",
            payment_intent_data={
                "metadata": metadata,
            },
            shipping_address_collection=None,
            billing_address_collection="auto",
            expires_at=None,  # no expiration for now
        )
        return {"url": session.url, "session_id": session.id}
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/webhook")
async def webhook(request: Request):
    """Handle Stripe webhooks for payment confirmation."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if webhook_secret:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
        except stripe.error.SignatureVerificationError:
            raise HTTPException(status_code=400, detail="Invalid signature")
    else:
        # No webhook secret configured — parse without verification (dev mode)
        import json
        event = json.loads(payload)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        # Log the order — in production, save to database
        print(f"Payment completed: {session.get('id')}")
        print(f"  Customer: {session.get('metadata', {}).get('customer_name')}")
        print(f"  Order: {session.get('metadata', {}).get('order_details')}")
        print(f"  Amount: ${session.get('amount_total', 0) / 100:.2f}")

    return JSONResponse({"received": True})


# ===== CONTACT FORM =====

CONTACT_SUBJECT_MAP = {
    "catering": "Catering Inquiry",
    "preorder": "Preorder Question",
    "feedback": "Feedback",
    "wholesale": "Wholesale",
    "other": "Other",
}

class ContactRequest(BaseModel):
    name: str
    email: str
    phone: Optional[str] = ""
    subject: str
    message: str

@app.post("/api/contact")
async def submit_contact(req: ContactRequest):
    smtp_host = os.environ.get("CONTACT_SMTP_HOST", "box.ovr.watch")
    smtp_port = int(os.environ.get("CONTACT_SMTP_PORT", "465"))
    smtp_user = os.environ.get("CONTACT_SMTP_USER", "info@goldysbagels.com")
    smtp_pass = os.environ.get("CONTACT_SMTP_PASS", "")
    to_email = os.environ.get("CONTACT_TO_EMAIL", "josh@ciderhouse.org")

    if not smtp_pass:
        raise HTTPException(status_code=500, detail="Contact form email not configured")

    subject_label = CONTACT_SUBJECT_MAP.get(req.subject, req.subject)

    # Build the email
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Goldy's Bagels] {subject_label}: {req.name}"
    msg["From"] = f"Goldy's Bagels Website <{smtp_user}>"
    msg["To"] = to_email
    msg["Reply-To"] = req.email

    # Plain text version
    text_body = f"""New message from the Goldy's Bagels contact form:

Name: {req.name}
Email: {req.email}
Phone: {req.phone or 'Not provided'}
Subject: {subject_label}

Message:
{req.message}
"""

    # HTML version
    html_body = f"""\
<html>
<body style="font-family: Inter, system-ui, sans-serif; color: #2C2823; line-height: 1.6;">
  <div style="max-width: 600px; margin: 0 auto; padding: 32px;">
    <h2 style="color: #1C1A18; font-family: 'Young Serif', serif; margin-bottom: 8px;">
      New Contact Form Message
    </h2>
    <p style="color: #6B655C; font-size: 14px; margin-bottom: 24px;">
      From the <strong>goldysbagels.com</strong> contact form
    </p>
    <table style="width: 100%; border-collapse: collapse; margin-bottom: 24px;">
      <tr>
        <td style="padding: 8px 0; font-weight: 600; color: #6B655C; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em; width: 100px;">Name</td>
        <td style="padding: 8px 0;">{req.name}</td>
      </tr>
      <tr>
        <td style="padding: 8px 0; font-weight: 600; color: #6B655C; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;">Email</td>
        <td style="padding: 8px 0;"><a href="mailto:{req.email}" style="color: #C9A24A;">{req.email}</a></td>
      </tr>
      <tr>
        <td style="padding: 8px 0; font-weight: 600; color: #6B655C; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;">Phone</td>
        <td style="padding: 8px 0;">{req.phone or 'Not provided'}</td>
      </tr>
      <tr>
        <td style="padding: 8px 0; font-weight: 600; color: #6B655C; font-size: 13px; text-transform: uppercase; letter-spacing: 0.05em;">Subject</td>
        <td style="padding: 8px 0;">{subject_label}</td>
      </tr>
    </table>
    <div style="background: #FAF7F0; border-radius: 8px; padding: 24px; border: 1px solid #E0DAD0;">
      <p style="white-space: pre-wrap; margin: 0;">{req.message}</p>
    </div>
  </div>
</body>
</html>
"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [to_email], msg.as_string())
    except Exception as e:
        print(f"Contact form email error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email. Please try again later.")

    return {"status": "sent"}
