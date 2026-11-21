"""One-time controlled schema initialization for serverless deployments.

Vercel cold starts never touch the database, so run this once (and after
schema changes) from a machine you trust with the production variables set:

    cd anonymous-wall
    . .venv/bin/activate
    VERCEL=false DATABASE_URL='postgresql://...' SECRET_KEY='...' \
        ADMIN_TOKEN='...' python scripts/init_db.py

It only creates missing tables; it never prints or alters secrets.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import initialize_database

initialize_database()
print("Database schema initialized (existing tables left unchanged).")
