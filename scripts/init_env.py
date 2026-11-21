"""Create a local .env with fresh secrets. Never overwrite an existing .env."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
content = (root / ".env.example").read_text(encoding="utf-8")
content = content.replace("SECRET_KEY=", "SECRET_KEY=" + secrets.token_urlsafe(48))
content = content.replace("ADMIN_TOKEN=", "ADMIN_TOKEN=" + secrets.token_urlsafe(48))
path = root / ".env"
try:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; left unchanged.")
with os.fdopen(fd, "w", encoding="utf-8") as stream:
    stream.write(content)
print("Created .env with fresh local secrets. Keep it private; never commit it.")
