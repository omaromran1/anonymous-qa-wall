import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold().replace("ـ", "")
    return "".join(c for c in text if unicodedata.category(c) not in {"Mn", "Cf"})


WORDS = [normalize(line.strip()) for line in
         Path(__file__).with_name("profanity.txt").read_text(encoding="utf-8").splitlines()
         if line.strip() and not line.lstrip().startswith("#")]
PATTERN = re.compile(r"(?<!\w)(?:" + "|".join(re.escape(w) for w in WORDS) + r")(?!\w)") if WORDS else None


def clean_text(value):
    if not isinstance(value, str):
        raise ValueError("Enter text, not a file.")
    if "\x00" in value:
        raise ValueError("Text cannot contain null characters.")
    value = value.strip()
    if PATTERN and PATTERN.search(normalize(value)):
        raise ValueError("Please remove abusive words before posting.")
    return value


def relative_time(value):
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    seconds = max(0, int((datetime.now(timezone.utc) - value).total_seconds()))
    if seconds < 60:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        amount = seconds // size
        if amount:
            return f"{amount} {unit}{'s' if amount != 1 else ''} ago"
    return "just now"
