"""Normalisation helpers used for matching and de-duplication."""
import math
import re
import unicodedata
from difflib import SequenceMatcher

_LEGAL_SUFFIX = re.compile(
    r"\b(pte\.?\s*ltd\.?|private\s+limited|sdn\.?\s*bhd\.?|llp|ltd\.?|limited)\b"
)
_NOISE = re.compile(r"\b(halal|restaurant|restoran|cafe|café|the)\b")
_UNIT = re.compile(r"#?\s*(B?\d{1,3})\s*-\s*(\d{1,5}[A-Z]?)", re.I)


def norm_text(value):
    if value is None:
        return ""
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " and ").replace("@", " at ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_name(value):
    """Name key: lower-case, accents and legal suffixes removed."""
    s = norm_text(value)
    s = _LEGAL_SUFFIX.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def brand_key(value):
    """Looser key used only to recognise branches of the same brand."""
    s = norm_name(value)
    s = re.split(r"\b(at|outlet|branch)\b", s)[0]
    s = _NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_postal(value):
    if value is None:
        return ""
    digits = re.sub(r"\D", "", str(value).split(".")[0])
    if not digits:
        return ""
    digits = digits.zfill(6) if len(digits) <= 6 else digits
    return digits if len(digits) == 6 else ""


def unit_from(text):
    if not text:
        return ""
    m = _UNIT.search(str(text))
    if not m:
        return ""
    return f"{m.group(1).upper().zfill(2)}-{m.group(2).upper()}"


def similarity(a, b):
    a, b = norm_name(a), norm_name(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def metres_between(lat1, lon1, lat2, lon2):
    try:
        lat1, lon1, lat2, lon2 = map(float, (lat1, lon1, lat2, lon2))
    except (TypeError, ValueError):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
