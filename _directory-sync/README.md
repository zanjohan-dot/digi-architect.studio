# Directory maintenance (`_directory-sync`)

This is month-end maintenance for `/muslim-friendly-directory`. GitHub Pages
does not publish this folder because its name starts with `_`. **The
repository is public, though, so everything committed here can be read on
github.com.** The [privacy rules](#privacy-public-repository) section says
what must stay out.

## How the directory works

The page loads `data/muslim-friendly-establishments.xlsx` in the browser using
SheetJS, and reads only the first sheet. There is no database.

Six columns are live Excel formulas:

- ID
- Postal Prefix
- Demo Disclaimer
- Data Completeness
- Map Ready
- Record Validation

The site reads their **saved results**. Every automated write therefore
recalculates the workbook with LibreOffice and checks it before replacing the
live file. `dsync/workbook.py` is the only code that touches Excel, so a later
move to a database such as Supabase replaces that one module.

## Listing types

| Listing Status | Certification Status | Comes from |
|---|---|---|
| Halal certified | Halal-certified (Muis) | A verification with certificate evidence (below) |
| Self-declared Muslim-friendly | Not halal-certified | The establishment's own declaration (entered by hand) |
| Community suggested — not verified | Certification status not stated | An approved OpenStreetMap candidate (only when OSM publishing is on) |
| Pending verification | Certificate expired — re-verification pending | Set automatically when a recorded certificate expires |

OpenStreetMap halal tags are **never** treated as certification.

## Month-end run (automatic)

`.github/workflows/directory-month-end.yml` runs at **23:00 SGT on the last
calendar day of each month**. GitHub cron cannot say "last day", so the job is
scheduled for days 28–31 at 15:00 UTC, and `sync.py` exits unless it is
month-end in Singapore.

Scheduled runs start only from `main`, and GitHub may start them a few minutes
late. To run now, use **Actions → Directory month-end sync → Run workflow →
sync**.

Each run:

1. **Checks every listing.** It looks for duplicates and incomplete data. For
   certified listings it flags certificates that have expired, expire within 30
   days, lack evidence, or have not been re-verified in 31 days. Results go to
   `state/directory-issues.csv`.
2. **Withdraws certified status** from any listing whose recorded certificate
   has expired. The listing becomes "Pending verification". This is the only
   change the scheduled run makes to the website.
3. **Refreshes candidates** from OpenStreetMap and any licensed dataset. It
   matches them to listings, keeps branches separate, and flags duplicates. It
   records new, changed and no-longer-found records and never deletes them.
   Results go to `state/candidates.csv`.
4. **Scans free-text fields** for email addresses, phone numbers and access
   links (see [privacy rules](#privacy-public-repository)).
5. **Writes the audit trail and report.** One line per run goes to
   `state/sync-log.csv`, and the monthly report goes to `reports/YYYY-MM.md`.

**Failure handling:**

- **Source down.** Nothing changes, and the run is logged as Failed. The
  scheduled job retries once after 20 minutes, across four Overpass servers.
  If it still fails, GitHub marks the workflow failed and emails the owner.
- **Late start.** GitHub sometimes starts scheduled jobs late. A month-end job
  that starts after midnight still runs for the month just ended, unless that
  month already has a successful run logged. A job for an earlier day that
  starts after midnight on the last day does not run early.
- **Small extract.** If a source returns under 70% of last month's count, the
  run is Partial. Previous data is kept, and nothing is marked missing.
- **Workbook not verified.** If any workbook write cannot be verified, the
  live file is left exactly as it was.
- **Website read check fails.** Nothing is committed unless a SheetJS read of
  the workbook (the same read the website does) succeeds.

## Verifying a certificate

Each check is one row in `state/verifications.csv`:

| Column | What to enter |
|---|---|
| `verification_id` | Your own reference, e.g. `V-2026-014` |
| `target` | The listing ID (e.g. `est-004`) to certify an existing listing; a candidate `source_id` (e.g. `osm:node/123`) to list a candidate; or blank for a new listing |
| `establishment_name`, `address`, `postal_code` | As printed on the certificate |
| `certifying_body` | `Muis (Singapore)`, `JAKIM (Malaysia)`, `MUI (Indonesia)` or `Other` |
| `certificate_number`, `certificate_expiry` | From the certificate (`YYYY-MM-DD`) |
| `scheme` | Optional: Restaurant, Hawker, Snack Bar, Bakery, Food Court, Caterer |
| `evidence_type` | `Certificate supplied by establishment`, `Certificate sighted on premises`, `Certifying body record checked` or `Permitted dataset` |
| `evidence_ref` | **Private label only**, e.g. `Drive > Certificates > 2026-10 > Restoran X`. Never a file, an email address or a shared link. |
| `verified_on` | Date you checked (within the last 31 days) |
| `verified_by` | Role or initials |
| `status` | `draft` while working; `approved` when ready |

Then run **Actions → Run workflow → apply**, or locally
`python _directory-sync/apply.py` (preview) followed by `--apply`.

A verification is **refused**, and the reason written to `notes`, if any of
these is true:

- a field is missing
- the certificate has expired
- the evidence type is not on the list
- the check is older than 31 days
- the listing already exists without a `target`
- a free-text field contains contact details

Applied rows stay in the file as the evidence trail: source, date,
certificate and private evidence reference. Renewals work the same way, with
a new row targeting the listing ID.

Coordinates for new certified listings are looked up from the postal code
through OneMap. This is best effort; set the `ONEMAP_TOKEN` secret if OneMap
requires one. If the lookup fails, the listing is added and flagged
"Missing coordinates".

## Candidates (community suggestions)

In `state/candidates.csv`, set `review_status` to `approved` or `rejected`.
Approved rows are listed as "Community suggested — not verified" by the
`apply` action.

OpenStreetMap rows are refused while `settings.json` has
`"osm_publishing_accepted": false`, which is the default.

## Settings (`settings.json`)

| Setting | Default | Meaning |
|---|---|---|
| `osm_publishing_accepted` | `false` | Allow OSM-derived community listings on the website (see ODbL below) |
| `suspend_expired_certificates` | `true` | Month-end run withdraws certified status after a recorded expiry |
| `geocode_with_onemap` | `true` | Look up coordinates for verified listings |
| `reverify_days` / `expiry_warning_days` | `31` / `30` | Re-verification and expiry-warning windows |

## Sources

| Source | Status | Terms |
|---|---|---|
| OpenStreetMap (`diet:halal=yes/only`, `cuisine=halal`, Singapore) | Fetched monthly | ODbL 1.0, attribution "© OpenStreetMap contributors" |
| Licensed dataset (`inbox/permitted/`, or the `PERMITTED_DATASET_URL` + `PERMITTED_PROVENANCE` secrets) | Read only with a provenance record | As licensed; see `inbox/permitted/README.md` |
| Muis halal portal | **Not queried** | Muis Terms of Use require written permission to reproduce content |

### ODbL (OpenStreetMap)

`state/candidates.csv` is a public extract of OSM data. It is attributed and
offered under ODbL.

If you turn on `osm_publishing_accepted`, two things follow:

- **Attribution.** The directory page automatically shows the OSM attribution
  whenever a listing contains OSM-derived data.
- **Share-alike.** The public workbook then contains OSM-derived rows, so that
  data must be made available under ODbL.

The alternative is to keep OSM as a lead list: invite each establishment to
declare or certify, and list it from its own information.

## Privacy (public repository)

| Stays out of this repository | Why |
|---|---|
| Certificate scans, photos, PDFs, emails | Evidence lives in private storage; `evidence_ref` only names where |
| Establishment owner/contact details, private submissions | Personal data |
| Licensed datasets and their provenance | Licence may forbid publication. These files are git-ignored, and records from licences that forbid publication go to the git-ignored `state/private/` |
| Credentials, API tokens, private links | Use repository secrets |

`.gitignore` blocks the common file types. The month-end run flags email
addresses, phone numbers and access links in `review_note`, `evidence_ref`,
`verified_by` and `notes`. Error messages from the licensed-feed download
never include its URL.

## Muis portal: field mapping for a future licensed feed

The public portal's search calls `POST https://halal.muis.gov.sg/api/halal/establishments`.
It has no public documentation and no full-list call. **No harvester is
implemented.** A licensed file or feed only needs to be supplied as CSV with
the columns below; no code changes are required.

| Portal field (as displayed) | CSV column | Directory column |
|---|---|---|
| Establishment name | `establishment_name` | Name |
| Scheme / type (Restaurant, Hawker, Snack Bar, …) | `establishment_type` | Establishment Type (mapped) |
| Certificate number (e.g. `EERT…`, `EEHK…`) | `certificate_number` | Basis of Listing; cross-reference key |
| Address incl. unit and building | `address` | Address (unit used for branch matching) |
| Postal code | `postal_code` | Postal Code → Area / Sector / District |
| Map position | `latitude`, `longitude` | Latitude, Longitude |
| Expiry (not shown on portal) | `certificate_expiry` | Certificate Expiry |

## Other tools

- `python _directory-sync/remove_demo.py [--apply]` removes listings marked
  `Is Demo = TRUE`. It backs up the workbook to `backups/` first.
- `node _directory-sync/tools/site_read_check.mjs data/muslim-friendly-establishments.xlsx`
  reads the workbook exactly as the website does. It needs
  `npm install https://cdn.sheetjs.com/xlsx-0.20.3/xlsx-0.20.3.tgz` in `tools/`.

## Tests

```
python -m unittest discover -s _directory-sync/tests -v
```

There are 28 end-to-end tests. They run automatically on every pull request
(`.github/workflows/directory-tests.yml`), followed by a live dry run against
OpenStreetMap.
