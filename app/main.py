from contextlib import asynccontextmanager
from pathlib import Path
import logging

logging.getLogger("uvicorn.access").disabled = True

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from app.config import settings
from app.database import initialize_database
from app.ratelimit import RateLimitExceeded
from app.routers import admin, answers, questions, votes
from app.security import new_csrf, valid_csrf, cookie_options
from app.web import render


@asynccontextmanager
async def lifespan(app):
    # Vercel cold starts many short-lived instances; touching Neon in the
    # startup path would slow or break cold /health probes. There the schema
    # is initialized once, out of band, with scripts/init_db.py. Local and
    # Render keep startup initialization behind the same flag.
    if settings.db_init_on_startup and not settings.vercel:
        initialize_database()
    yield


app = FastAPI(title="Anonymous Q&A Wall", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    cookie = request.cookies.get("csrf", "")
    request.state.csrf = cookie if valid_csrf(cookie) else new_csrf()
    response = await call_next(request)
    # A health probe needs no database, token, or cookie.
    if request.url.path != "/health" and request.state.csrf != cookie:
        response.set_cookie("csrf", request.state.csrf, max_age=86400, **cookie_options())
    response.headers.update({
        "Content-Security-Policy": "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    })
    if settings.secure_cookies:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


def error_response(request, message, status):
    name = "error_fragment.html" if request.headers.get("hx-request") == "true" else "error.html"
    response = render(request, name, message=message)
    response.status_code = status
    return response


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc):
    return error_response(request, str(exc.detail), exc.status_code)


@app.exception_handler(ValidationError)
async def validation_error(request: Request, exc):
    # Do not echo user content or internal exception details.
    messages = [f"{e['loc'][-1]}: {e['msg']}" for e in exc.errors()]
    return error_response(request, "; ".join(messages), 422)


@app.exception_handler(RequestValidationError)
async def request_error(request: Request, exc):
    return error_response(request, "Invalid address, page number, or form input.", 422)


@app.exception_handler(RateLimitExceeded)
async def rate_error(request: Request, exc):
    response = error_response(request, "Too many requests. Please try again later.", 429)
    response.headers["Retry-After"] = str(exc.retry_after)
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


for router in (questions.router, answers.router, votes.router, admin.router):
    app.include_router(router)
