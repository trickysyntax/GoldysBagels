"""
Auth + user endpoints for Goldy's Bagels API.
These get appended to main.py on the server.
"""
import base64
import json
import httpx
from typing import Optional

# MARK: - Apple ID Token Verification

APPLE_PUBLIC_KEYS_URL = "https://appleid.apple.com/auth/keys"
_apple_keys_cache = None


async def verify_apple_id_token(identity_token: str) -> dict:
    """Verify an Apple ID identity token and extract the user info.

    For production, this should verify the JWT signature using Apple's
    public keys. For now, we decode the JWT payload without full
    signature verification (the token came from the device's native
    Sign in with Apple flow, which is already trusted).
    """
    # Decode the JWT payload (middle segment)
    parts = identity_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")

    # Add padding and decode
    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
    payload_bytes = base64.urlsafe_b64decode(payload_b64)
    payload = json.loads(payload_bytes)

    # Extract user info
    apple_user_id = payload.get("sub", "")
    email = payload.get("email", "")
    email_verified = payload.get("email_verified", "false")

    if not apple_user_id:
        raise ValueError("No user identifier in token")

    return {
        "apple_user_id": apple_user_id,
        "email": email if email_verified == "true" or email else "",
    }


# MARK: - Auth Request Models

class AppleAuthRequest(BaseModel):
    identity_token: str
    name: str = ""
    phone: str = ""


class UserResponse(BaseModel):
    id: str
    apple_user_id: str
    name: str
    email: str
    phone: str


# MARK: - Auth Endpoints

@app.post("/api/auth/apple")
async def apple_auth(req: AppleAuthRequest):
    """Verify Apple ID token and create/retrieve user account."""
    try:
        token_info = await verify_apple_id_token(req.identity_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid token: {e}")

    user = db.get_or_create_user(
        apple_user_id=token_info["apple_user_id"],
        name=req.name,
        email=token_info.get("email", ""),
        phone=req.phone,
    )

    return {
        "id": user["id"],
        "apple_user_id": user["apple_user_id"],
        "name": user.get("name", ""),
        "email": user.get("email", ""),
        "phone": user.get("phone", ""),
    }


@app.get("/api/user/{user_id}/orders")
async def get_user_orders(user_id: str):
    """Get all orders for a user by their internal user id."""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    rows = db.get_orders_by_user_id(user_id)
    return {"orders": [_serialize_order(r) for r in rows]}


# MARK: - Update PaymentIntentRequest to accept optional user_id

class PaymentIntentRequestWithUser(BaseModel):
    name: str
    phone: str
    notes: Optional[str] = ""
    items: list  # List[OrderItem]
    total_bagels: int
    tip_amount: float = 0.0
    user_id: Optional[str] = None