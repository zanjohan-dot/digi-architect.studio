"""Month-end maintenance for the Muslim-Friendly Dining Directory.

The published workbook (data/muslim-friendly-establishments.xlsx) is the
source of truth for the website. This package never edits it during the
scheduled run. It checks the workbook, refreshes candidate records from
sources that may lawfully be reused, and writes an audit trail and report.
Records reach the website only through promote.py, after an administrator
has marked them approved.
"""

SGT_TZ = "Asia/Singapore"
