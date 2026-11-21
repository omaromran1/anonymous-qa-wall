import hashlib
import hmac
import ipaddress
import secrets

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings

signer = URLSafeTimedSerializer(settings.secret_key, salt="wall-csrf-v1")
admin_signer = URLSafeTimedSerializer(settings.secret_key, salt="wall-admin-v1")


def voter_hash(request: Request):
    ip = request.client.host if request.client else "unknown"
    if settings.trust_proxy:
        if settings.vercel:
            # Vercel's edge overwrites X-Forwarded-For and the identical
            # X-Vercel-Forwarded-For/X-Real-IP, so client-sent values are
            # discarded and these headers cannot be spoofed through Vercel.
            forwarded = (request.headers.get("x-vercel-forwarded-for", "")
                         or request.headers.get("x-real-ip", "")).strip()
        elif settings.render:
            # Render overwrites CF-Connecting-IP; leftmost XFF is spoofable.
            forwarded = request.headers.get("cf-connecting-ip", "").strip()
        else:
            forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            ip = forwarded
    try:
        ip = str(ipaddress.ip_address(ip))
    except ValueError:
        ip = "unknown"
    agent = request.headers.get("user-agent", "")
    # Raw address and agent are used transiently, never persisted or logged here.
    return hmac.new(settings.secret_key.encode(), (ip + agent).encode(), hashlib.sha256).hexdigest()


def cookie_options():
    return dict(httponly=True, samesite="lax", secure=settings.secure_cookies, path="/")


def new_csrf():
    return signer.dumps(secrets.token_urlsafe(32))


def valid_csrf(token):
    try:
        return isinstance(signer.loads(token, max_age=86400), str)
    except (BadSignature, TypeError):
        return False


async def require_csrf(request: Request):
    form = await request.form()
    request.state.form = form
    submitted = form.get("csrf_token", "")
    cookie = request.cookies.get("csrf", "")
    if not isinstance(submitted, str) or not cookie or not hmac.compare_digest(submitted.encode(), cookie.encode()) or not valid_csrf(cookie):
        raise HTTPException(403, "Form expired or invalid. Reload the page and try again.")


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def owns(request, question):
    raw = request.cookies.get(f"owner_{question.id}", "")
    return bool(raw) and hmac.compare_digest(token_hash(raw), question.edit_token_hash)


def is_admin(request):
    if not settings.admin_token:
        return False
    supplied = request.headers.get("x-admin-token", "")
    if supplied and hmac.compare_digest(supplied.encode(), settings.admin_token.encode()):
        return True
    try:
        digest = admin_signer.loads(request.cookies.get("admin", ""), max_age=3600)
        return hmac.compare_digest(digest, token_hash(settings.admin_token))
    except (BadSignature, TypeError):
        return False


def require_admin(request: Request):
    if not is_admin(request):
        raise HTTPException(403, "Admin sign-in required.")
