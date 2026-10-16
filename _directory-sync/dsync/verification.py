"""Certification evidence: validation rules and the listing fields they produce.

Administrators record each check in state/verifications.csv. A row only
changes the directory when its status is `approved` and it passes every rule
below. The row stays in the file afterwards as the audit trail.

The repository is public, so evidence itself (certificate scans, emails,
contact details) is never stored here. `evidence_ref` is a private label,
e.g. "Drive › Certificates › 2026-10 › Restoran X.pdf".
"""
import datetime as dt
import re

from .normalise import norm_postal

VERIFICATION_FIELDS = [
    "verification_id", "target", "establishment_name", "address", "postal_code",
    "certifying_body", "certificate_number", "certificate_expiry", "scheme",
    "evidence_type", "evidence_ref", "verified_on", "verified_by",
    "status", "applied_on", "applied_to", "notes",
]

EVIDENCE_TYPES = {
    "certificate supplied by establishment",
    "certificate sighted on premises",
    "certifying body record checked",
    "permitted dataset",
}
CERTIFYING_BODIES = {"Muis (Singapore)", "JAKIM (Malaysia)", "MUI (Indonesia)", "Other"}

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"(?<![\w-])(\+?65[\s-]?)?[689]\d{3}[\s-]?\d{4}\b")  # not inside IDs like com-94974045
_URL_WITH_QUERY = re.compile(r"https?://\S*\?\S+")


def parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %b %Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(str(value).strip(), fmt).date()
        except ValueError:
            continue
    return None


def personal_data_flags(text):
    """Return reasons a free-text field should not go into a public repository."""
    text = str(text or "")
    flags = []
    if _EMAIL.search(text):
        flags.append("contains an email address")
    if _PHONE.search(text):
        flags.append("contains a phone number")
    if _URL_WITH_QUERY.search(text):
        flags.append("contains a link with access parameters")
    return flags


def validate(row, today, reverify_days=31):
    """Return a list of problems; empty means the row can be applied."""
    problems = []
    for f in ("establishment_name", "address", "postal_code", "certifying_body",
              "certificate_number", "certificate_expiry", "evidence_type", "evidence_ref",
              "verified_on", "verified_by"):
        if not str(row.get(f) or "").strip():
            problems.append(f"{f} is required")
    if row.get("postal_code") and not norm_postal(row["postal_code"]):
        problems.append("postal_code must be a 6-digit Singapore postal code")
    if row.get("certifying_body") and row["certifying_body"] not in CERTIFYING_BODIES:
        problems.append(f"certifying_body must be one of: {', '.join(sorted(CERTIFYING_BODIES))}")
    if row.get("evidence_type") and row["evidence_type"].strip().lower() not in EVIDENCE_TYPES:
        problems.append(f"evidence_type must be one of: {', '.join(sorted(EVIDENCE_TYPES))}")
    expiry = parse_date(row.get("certificate_expiry"))
    if row.get("certificate_expiry") and not expiry:
        problems.append("certificate_expiry is not a valid date (use YYYY-MM-DD)")
    elif expiry and expiry < today:
        problems.append(f"certificate expired on {expiry.isoformat()}")
    checked = parse_date(row.get("verified_on"))
    if row.get("verified_on") and not checked:
        problems.append("verified_on is not a valid date (use YYYY-MM-DD)")
    elif checked and checked > today:
        problems.append("verified_on is in the future")
    elif checked and (today - checked).days > reverify_days:
        problems.append(f"verification is older than {reverify_days} days; check again before publishing")
    for f in ("evidence_ref", "verified_by", "notes"):
        for flag in personal_data_flags(row.get(f)):
            problems.append(f"{f} {flag} - this file is public; keep evidence details private")
    if len(str(row.get("verified_by") or "")) > 30:
        problems.append("verified_by should be a role or initials, not a full name")
    return problems


def certified_fields(row):
    """Workbook fields for a listing whose certificate has been verified."""
    body = row["certifying_body"]
    short = body.split(" (")[0]
    checked = parse_date(row["verified_on"]).isoformat()
    expiry = parse_date(row["certificate_expiry"]).isoformat()
    return {
        "Listing Status": "Halal certified",
        "Halal Certified": "TRUE",
        "Certification Status": f"Halal-certified ({short})",
        "Certifying Body": body,
        "Certificate Expiry": expiry,
        "Basis of Listing": (f"Halal certificate {row['certificate_number']} ({short}), valid to {expiry}. "
                             f"Evidence: {row['evidence_type'].strip().lower()}; verified {checked}."),
        "Last Updated": checked,
    }


def suspended_fields(listing, today):
    """Fields that withdraw a certification claim once its expiry has passed."""
    return {
        "Listing Status": "Pending verification",
        "Halal Certified": "",
        "Certification Status": "Certificate expired — re-verification pending",
        "Basis of Listing": (f"Certificate recorded as expiring {listing.get('Certificate Expiry')}. "
                             f"Certified status withdrawn {today.isoformat()} pending evidence of renewal."),
        "Last Updated": today.isoformat(),
    }
