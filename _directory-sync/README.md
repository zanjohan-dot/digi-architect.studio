# Directory maintenance (`_directory-sync`)

Month-end maintenance for `/muslim-friendly-directory`. The folder name starts
with `_`, so GitHub Pages (Jekyll) does not publish it on the website. The
repository is public, so these files are still readable on github.com.

## How the directory works

The page loads `data/muslim-friendly-establishments.xlsx` in the browser
(SheetJS) and reads the **first sheet** only. There is no database or server.
Six columns are live Excel formulas (ID, Postal Prefix, Demo Disclaimer, Data
Completeness, Map Ready, Record Validation); the site reads their **saved
results**, so the workbook must be recalculated before it is published.

## Schedule

`.github/workflows/directory-month-end.yml` runs at **23:00 SGT on the last
calendar day of every month** (cron on days 28–31 at 15:00 UTC; `sync.py` exits
unless it is month-end in Singapore). GitHub can start scheduled jobs a few
minutes late. A failed run fails the workflow, and GitHub emails the repository
owner. Run it on demand from **Actions → Directory month-end sync → Run
workflow → sync**.

The scheduled run **never edits the published workbook**. It:

| Step | Output |
|---|---|
| Checks every live listing for duplicates, incomplete data, and certified listings that are expired, expiring within 30 days, missing evidence or not re-verified in 31 days | `state/directory-issues.csv` |
| Refreshes candidates from permitted sources, matches them to listings, keeps branches separate, flags duplicates, and records new / changed / no-longer-found records (never deleted) | `state/candidates.csv` |
| Appends one line per run | `state/sync-log.csv` |
| Writes the monthly report | `reports/YYYY-MM.md` |

If a source fails, nothing changes. If a source returns under 70% of last
month's count, the run is **Partial**: previous data is kept and nothing is
marked missing.

## Reviewing and publishing candidates

1. Open `state/candidates.csv`. Rows needing a decision have
   `review_status = pending` and `match_status` of `new`, `new_branch` or
   `possible_duplicate`.
2. Set `review_status` to `approved` or `rejected` (note why in `review_note`).
3. Run **Actions → Directory month-end sync → Run workflow → promote**, or
   locally `python _directory-sync/promote.py` (preview), then `--apply`.

`promote.py` appends approved rows to the table and recalculates with
LibreOffice. Existing rows are left untouched. It refuses rows still flagged as
duplicates.

| Source | Listed as |
|---|---|
| OpenStreetMap | Community suggested — not verified; no certification claim |
| Permitted dataset with a certificate number | Halal certified; Certifying Body and Certificate Expiry as supplied |

IDs come from the row position (`est-NNN`). Deleting or re-sorting rows
renumbers them; matching therefore also uses name + postal code, not the ID alone.

## Sources

| Source | Status | Terms |
|---|---|---|
| OpenStreetMap (`diet:halal=yes/only`, `cuisine=halal`, Singapore) | Fetched automatically | ODbL 1.0 — attribute "© OpenStreetMap contributors". Tags are community-contributed and are **not** evidence of Muis certification. |
| Permitted dataset (`inbox/permitted/*.csv`) | Read only if `inbox/permitted/PROVENANCE.md` has a `Permission:` line | As licensed |
| Muis halal portal | **Not queried** | Muis Terms of Use require written permission to reproduce content |

### ODbL note

Records copied from OpenStreetMap form part of an ODbL database. Publishing a
database that incorporates them (including the public workbook once OSM rows are
promoted) carries attribution and share-alike obligations for that data. The
directory's own declarations are independent content. Take a view on this
before promoting OSM rows. The alternative is to treat OSM purely as a lead
list and list an establishment only after it submits its own declaration.

## Muis portal: field mapping for a future permitted feed

The public portal's search calls `POST https://halal.muis.gov.sg/api/halal/establishments`.
It has no public documentation and no full-list call. **No harvester is
implemented.** If Muis permits reuse (file or API), supply it as a CSV in
`inbox/permitted/` with a `PROVENANCE.md`.

| Portal field (as displayed) | CSV column | Directory column |
|---|---|---|
| Establishment name | `establishment_name` | Name |
| Scheme / type (Restaurant, Hawker, Snack Bar, …) | `establishment_type` | Establishment Type (mapped) |
| Certificate number (e.g. `EERT…`, `EEHK…`) | `certificate_number` | Basis of Listing; cross-reference key |
| Address incl. unit and building | `address` | Address (unit used for branch matching) |
| Postal code | `postal_code` | Postal Code → Area / Sector / District |
| Map position (OneMap) | `latitude`, `longitude` | Latitude, Longitude |
| Expiry (not shown on portal) | `certificate_expiry` | Certificate Expiry |

Any certified listing must show the source and the date it was last verified.
It must not use the Muis logo, and diners should be told to check the
certificate displayed at the premises.

## Tests

```
python -m unittest discover -s _directory-sync/tests -v
```

The 11 end-to-end tests cover:

- month-end guard
- initial import and idempotent re-run
- branches kept separate
- change detection
- missing records kept and flagged
- source down
- partial source
- permitted dataset provenance and cross-source de-duplication
- certificate expiry and evidence checks
- dry run
- promotion into the real workbook

The promotion and certificate tests need LibreOffice.
