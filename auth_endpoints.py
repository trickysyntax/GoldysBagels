# --------------------------------------------------------------------------- #
# User authentication (Sign in with Apple)                                    #
# --------------------------------------------------------------------------- #

import base64 as _b64


async def _verify_apple_id_token(identity_token: str) -> dict:
    """Decode an Apple ID identity token JWT and extract user info."""
    parts = identity_token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid JWT format")
    payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
    payload_bytes = _b64.urlsafe_b64decode(payload_b64)
    payload = json.loads(payload_bytes)
    apple_user_id = payload.get("sub", "")
    email = payload.get("email", "")
    email_verified = payload.get("email_verified", "false")
    if not apple_user_id:
        raise ValueError("No user identifier in token")
    return {
        "apple_user_id": apple_user_id,
        "email": email if (email_verified == "true" or email) else "",
    }


class AppleAuthRequest(BaseModel):
    identity_token: str
    name: str = ""
    phone: str = ""


@app.post("/api/auth/apple")
async def apple_auth(req: AppleAuthRequest):
    """Verify Apple ID token and create or retrieve the user account."""
    try:
        token_info = await _verify_apple_id_token(req.identity_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid token: " + str(e))
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
    """Return all orders for a user by internal user id."""
    user = db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    rows = db.get_orders_by_user_id(user_id)
    return {"orders": [_serialize_order(r) for r in rows]}