"""Month-end maintenance for the Muslim-Friendly Dining Directory.

The published workbook (data/muslim-friendly-establishments.xlsx) is the
source of truth for the website. The scheduled run only ever withdraws
certification claims whose recorded certificate has expired; it never adds
listings. New listings and certifications reach the website only through
apply.py, after an administrator has approved them.
"""

SGT_TZ = "Asia/Singapore"
