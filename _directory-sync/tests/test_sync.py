"""End-to-end tests. Run: python -m unittest discover -s _directory-sync/tests -v

Each test copies the tool, the real workbook and the directory page into a
temporary repo and runs the scripts exactly as the scheduled job does, using
offline fixtures. Tests that write the workbook need LibreOffice; website-read
checks need Node with SheetJS installed in _directory-sync/tools.
"""
import calendar
import csv
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl

TOOL = Path(__file__).resolve().parents[1]
REPO = TOOL.parent
WORKBOOK = REPO / "data" / "muslim-friendly-establishments.xlsx"
PAGE = REPO / "muslim-friendly-directory.html"
HAS_SOFFICE = bool(shutil.which("soffice"))
HAS_SHEETJS = bool(shutil.which("node")) and (TOOL / "tools" / "node_modules" / "xlsx").exists()
sys.path.insert(0, str(TOOL))

from dsync.verification import VERIFICATION_FIELDS  # noqa: E402


def node(i, name, postcode=None, lat=1.30, lon=103.85, timestamp="2025-06-01T00:00:00Z", **tags):
    t = {"name": name, "amenity": "restaurant", "diet:halal": "yes"}
    if postcode:
        t["addr:postcode"] = postcode
    t.update(tags)
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "timestamp": timestamp, "tags": t}


BASE = [
    node(1, "Nasi Lemak House", "730123", **{"addr:street": "Woodlands Avenue 1", "addr:housenumber": "12"}),
    node(2, "Prata Corner", "560456", 1.37, 103.84),
    node(3, "Burger Barn @ Tampines", "529510", 1.354, 103.944, cuisine="burger"),
    node(4, "Burger Barn @ Jurong", "609601", 1.333, 103.742, cuisine="burger"),
    node(5, "Teh Tarik Stall", None, 1.29, 103.86, amenity="food_court"),
]


def verification(**kw):
    row = {f: "" for f in VERIFICATION_FIELDS}
    row.update({
        "verification_id": "V-001", "establishment_name": "Restoran Contoh", "address": "1 Bedok North Road #01-10",
        "postal_code": "460001", "certifying_body": "Muis (Singapore)", "certificate_number": "EERT00001234",
        "certificate_expiry": "2027-06-30", "scheme": "Restaurant",
        "evidence_type": "Certificate supplied by establishment",
        "evidence_ref": "Drive > Certificates > 2026-10 > Restoran Contoh", "verified_on": "2026-10-20",
        "verified_by": "ZJ", "status": "approved",
    })
    row.update(kw)
    return row


def file_hash(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


class Harness:
    def __init__(self, settings=None):
        self.dir = Path(tempfile.mkdtemp())
        shutil.copytree(TOOL, self.dir / "_directory-sync",
                        ignore=shutil.ignore_patterns("state", "reports", "backups", "__pycache__", "tests",
                                                      "node_modules"))
        self.tool = self.dir / "_directory-sync"
        (self.tool / "inbox" / "permitted").mkdir(parents=True, exist_ok=True)
        for f in (self.tool / "inbox" / "permitted").glob("*.csv"):
            f.unlink()
        (self.dir / "data").mkdir()
        shutil.copy(WORKBOOK, self.wb)
        if (REPO / "data" / "community-listings.xlsx").exists():
            shutil.copy(REPO / "data" / "community-listings.xlsx", self.dir / "data" / "community-listings.xlsx")
        shutil.copy(PAGE, self.dir / PAGE.name)
        s = json.loads((TOOL / "settings.json").read_text())
        s.update({"geocode_with_onemap": False}, **(settings or {}))
        (self.tool / "settings.json").write_text(json.dumps(s))

    @property
    def wb(self):
        return self.dir / "data" / WORKBOOK.name

    def run(self, script, *args, env=None):
        e = dict(os.environ, **(env or {}))
        return subprocess.run([sys.executable, str(self.tool / script), *args],
                              capture_output=True, text=True, env=e)

    def sync(self, osm, today="2026-10-31", extra=(), env=None):
        fixture = self.dir / "fixture.json"
        fixture.write_text(json.dumps({"osm": osm}))
        return self.run("sync.py", "--offline", str(fixture), "--today", today, *extra, env=env)

    def apply(self, today="2026-10-31", env=None):
        return self.run("apply.py", "--apply", "--today", today, env=env)

    def read(self, name):
        p = self.tool / "state" / name
        if not p.exists():
            return []
        with p.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def write(self, name, rows):
        p = self.tool / "state" / name
        p.parent.mkdir(exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    def candidates(self):
        return {r["source_id"]: r for r in self.read("candidates.csv")}

    def approve(self, *sids):
        rows = self.read("candidates.csv")
        for r in rows:
            if r["source_id"] in sids:
                r["review_status"] = "approved"
        self.write("candidates.csv", rows)

    @property
    def cwb(self):
        return self.dir / "data" / "community-listings.xlsx"

    def listings(self, community=False):
        ws = openpyxl.load_workbook(self.cwb if community else self.wb, data_only=True)["Establishments"]
        hdr = [c.value for c in ws[1]]
        return [dict(zip(hdr, r)) for r in ws.iter_rows(min_row=2, values_only=True) if r[hdr.index("Name")]]

    def site_reads(self, community=False):
        """Number of listings the website would show, or raise if it would break."""
        r = subprocess.run(["node", str(TOOL / "tools" / "site_read_check.mjs"), str(self.cwb if community else self.wb)],
                           capture_output=True, text=True, cwd=TOOL / "tools")
        if r.returncode:
            raise AssertionError(r.stdout + r.stderr)
        return int(r.stdout.split("show ")[1].split(" ")[0])

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class Base(unittest.TestCase):
    settings = None

    def setUp(self):
        self.h = Harness(self.settings)

    def tearDown(self):
        self.h.cleanup()


# --------------------------------------------------------------------- sync --

class QualityGradeTests(unittest.TestCase):
    def test_grades(self):
        from dsync.quality import grade
        today = dt.date(2026, 10, 31)
        base = {"name": "X", "place_kind": "amenity=restaurant", "address": "1 Road", "postal_code": "123456",
                "osm_last_edit": "2025-01-01", "lifecycle": "", "check_date": ""}
        self.assertEqual(grade(base, today)[0], "publishable")
        self.assertEqual(grade(dict(base, name=""), today)[0], "rejected")
        self.assertEqual(grade(dict(base, place_kind="shop=supermarket"), today)[0], "rejected")
        self.assertEqual(grade(dict(base, place_kind="shop=bakery"), today)[0], "publishable")
        self.assertEqual(grade(dict(base, lifecycle="tagged was:amenity"), today)[0], "rejected")
        self.assertEqual(grade(dict(base, address="", postal_code=""), today)[0], "needs_location")
        self.assertEqual(grade(dict(base, osm_last_edit="2019-01-01"), today)[0], "needs_check")
        self.assertEqual(grade(dict(base, osm_last_edit="2019-01-01", check_date="2025-12-01"), today)[0], "publishable")
        self.assertIn("no postal code", grade(dict(base, postal_code=""), today)[1])
        self.assertEqual(grade(dict(base, postal_code="000101"), today)[0], "needs_check")
        self.assertEqual(grade(dict(base, latitude="3.15", longitude="101.7"), today)[0], "rejected")
        self.assertEqual(grade(dict(base, address="#03-21", postal_code=""), today)[0], "needs_location")
        self.assertEqual(grade(dict(base, address="#03-21"), today)[0], "publishable")  # postal code locates it
        self.assertEqual(grade(dict(base, duplicate_of="osm:node/1"), today)[0], "needs_check")

    def test_venue_detection(self):
        from dsync.quality import is_venue
        self.assertTrue(is_venue({"name": "Adam Food Centre"}))
        self.assertTrue(is_venue({"name": "Kedai Kopi", "place_kind": "amenity=restaurant"}))
        self.assertTrue(is_venue({"name": "X", "place_kind": "amenity=food_court"}))
        self.assertFalse(is_venue({"name": "Prata Corner", "place_kind": "amenity=restaurant"}))

    def test_same_name_within_50m_is_duplicate(self):
        from dsync.match import dedupe_sources
        a = {"source": "osm", "source_id": "osm:node/1", "name": "Nasi Lemak House", "postal_code": "730123",
             "address": "12 Woodlands Ave 1", "latitude": 1.3, "longitude": 103.85}
        b = dict(a, source_id="osm:way/2", postal_code="", address="", latitude=1.3002, longitude=103.8501)
        c = dict(a, source_id="osm:node/3", postal_code="", address="", latitude=1.35, longitude=103.9)
        self.assertEqual(dedupe_sources([a, b, c]), 1)
        self.assertEqual(b["duplicate_of"], "osm:node/1")
        self.assertNotIn("duplicate_of", c)  # same brand far away = separate branch


class SyncTests(Base):
    def test_month_end_guard(self):
        r = self.h.sync(BASE, today="2026-10-30")
        self.assertIn("not the last day", r.stdout)
        self.assertFalse((self.h.tool / "state" / "candidates.csv").exists())
        r = self.h.sync(BASE, today="2028-02-29")  # leap-year February
        self.assertIn("Monthly Synchronisation Report", r.stdout)

    def test_initial_import_and_idempotent_rerun(self):
        r = self.h.sync(BASE)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.h.candidates()), 5)
        before = (self.h.tool / "state" / "candidates.csv").read_text()
        self.h.sync(BASE)
        self.assertEqual(before, (self.h.tool / "state" / "candidates.csv").read_text())
        log = self.h.read("sync-log.csv")[-1]
        self.assertEqual((log["new"], log["unchanged"]), ("0", "5"))

    def test_branches_kept_separate(self):
        self.h.sync(BASE)
        c = self.h.candidates()
        self.assertEqual(c["osm:node/3"]["duplicate_of"], "")
        self.assertEqual(c["osm:node/4"]["duplicate_of"], "")

    def test_update_detected(self):
        self.h.sync(BASE)
        changed = [dict(e, tags=dict(e["tags"])) for e in BASE]
        changed[1]["tags"]["addr:postcode"] = "560999"
        self.h.sync(changed)
        self.assertIn("changed postal_code", self.h.candidates()["osm:node/2"]["change_note"])

    def test_missing_record_flagged_not_deleted(self):
        self.h.sync(BASE)
        self.h.sync(BASE[:4])
        self.assertEqual(self.h.candidates()["osm:node/5"]["missing_runs"], "1")

    def test_source_down_changes_nothing_but_is_logged(self):
        self.h.sync(BASE)
        before = (self.h.tool / "state" / "candidates.csv").read_text()
        wb_before = file_hash(self.h.wb)
        r = self.h.sync(None)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.h.read("sync-log.csv")[-1]["status"], "Failed")
        self.assertEqual(before, (self.h.tool / "state" / "candidates.csv").read_text())
        self.assertEqual(wb_before, file_hash(self.h.wb))

    def test_incomplete_source_treated_as_partial(self):
        self.h.sync(BASE)
        r = self.h.sync(BASE[:2])
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.h.read("sync-log.csv")[-1]["status"], "Partial")
        self.assertTrue(all(x["missing_runs"] == "0" for x in self.h.candidates().values()))

    def test_dry_run_writes_nothing(self):
        wb_before = file_hash(self.h.wb)
        self.h.sync(BASE, extra=["--dry-run"])
        self.assertFalse((self.h.tool / "state" / "candidates.csv").exists())
        self.assertEqual(wb_before, file_hash(self.h.wb))

    def test_privacy_scan_flags_contact_details(self):
        self.h.sync(BASE)
        rows = self.h.read("candidates.csv")
        rows[0]["review_note"] = "owner said ok, email boss@example.com"
        self.h.write("candidates.csv", rows)
        self.h.sync(BASE)
        issues = self.h.read("directory-issues.csv")
        self.assertTrue(any(i["issue"] == "Possible personal data in a public file" for i in issues))
        self.assertFalse(any("boss@example.com" in i["detail"] for i in issues), "must not repeat the data")


class PermittedDatasetTests(Base):
    CSV = ("establishment_name,establishment_type,certificate_number,address,postal_code,certificate_expiry\n"
           "Prata Corner,Restaurant,EERT00000001,1 Ang Mo Kio Ave 10,560456,2027-03-31\n")

    def test_requires_provenance_and_dedupes_with_osm(self):
        inbox = self.h.tool / "inbox" / "permitted"
        (inbox / "licensed.csv").write_text(self.CSV)
        r = self.h.sync(BASE)
        self.assertIn("NOT read", r.stdout)
        (inbox / "PROVENANCE.md").write_text("Permission: test licence ref 123\nPublication: permitted\n")
        self.h.sync(BASE)
        c = self.h.candidates()
        lic = c["permitted:licensed:EERT00000001"]
        self.assertEqual(lic["certifying_body"], "Muis (Singapore)")
        self.assertEqual(c["osm:node/2"]["duplicate_of"], lic["source_id"])

    def test_unpublishable_licence_kept_out_of_public_files(self):
        inbox = self.h.tool / "inbox" / "permitted"
        (inbox / "licensed.csv").write_text(self.CSV)
        (inbox / "PROVENANCE.md").write_text("Permission: test licence\nPublication: not permitted\n")
        r = self.h.sync(BASE)
        self.assertNotIn("EERT00000001", (self.h.tool / "state" / "candidates.csv").read_text())
        private = (self.h.tool / "state" / "private" / "candidates-permitted.csv").read_text()
        self.assertIn("EERT00000001", private)
        self.assertIn("Licensed records held privately (not published) | 1", r.stdout)
        for f in (self.h.tool / "reports").glob("*.md"):
            self.assertNotIn("EERT00000001", f.read_text())

    def test_secret_feed_failure_does_not_leak_url(self):
        secret = "https://127.0.0.1:9/private-feed.csv?sig=SECRET123"
        self.h.sync(BASE, env={"PERMITTED_DATASET_URL": secret, "PERMITTED_PROVENANCE": "Permission: x"})
        for p in list((self.h.tool / "state").rglob("*")) + list((self.h.tool / "reports").glob("*")):
            if p.is_file():
                self.assertNotIn("SECRET123", p.read_text(), p.name)
        self.assertEqual(self.h.read("sync-log.csv")[-1]["status"], "Partial")


class ScheduleTests(unittest.TestCase):
    def test_cron_and_guard_fire_exactly_on_last_day_at_2300_sgt(self):
        import yaml  # noqa: F401  (PyYAML ships with the GitHub runner image)
        wf = yaml.safe_load((REPO / ".github" / "workflows" / "directory-month-end.yml").read_text())
        cron = wf[True]["schedule"][0]["cron"] if True in wf else wf["on"]["schedule"][0]["cron"]
        minute, hour, dom, month, dow = cron.split()
        self.assertEqual((minute, hour, dom, month, dow), ("0", "15", "28-31", "*", "*"))
        from zoneinfo import ZoneInfo
        sys.path.insert(0, str(TOOL))
        from sync import is_month_end
        lo, hi = map(int, dom.split("-"))
        for year in (2026, 2027, 2028):
            for m in range(1, 13):
                fires = []
                for d in range(lo, calendar.monthrange(year, m)[1] + 1):
                    utc = dt.datetime(year, m, d, int(hour), int(minute), tzinfo=dt.timezone.utc)
                    sgt = utc.astimezone(ZoneInfo("Asia/Singapore"))
                    self.assertEqual((sgt.hour, sgt.minute), (23, 0))
                    if is_month_end(sgt.date()):
                        fires.append(sgt.date())
                self.assertEqual(fires, [dt.date(year, m, calendar.monthrange(year, m)[1])])


class LateStartTests(unittest.TestCase):
    """GitHub can start scheduled jobs late; the guard must neither skip nor double-run a month."""

    def setUp(self):
        import sync
        self.sync = sync
        self.tmp = Path(tempfile.mkdtemp())
        self._state = sync.STATE
        sync.STATE = self.tmp

    def tearDown(self):
        self.sync.STATE = self._state
        shutil.rmtree(self.tmp, ignore_errors=True)

    def at(self, *a):
        from zoneinfo import ZoneInfo
        return dt.datetime(*a, tzinfo=ZoneInfo("Asia/Singapore"))

    def test_last_day_job_starting_after_midnight_still_runs(self):
        self.assertEqual(self.sync.late_start_date(self.at(2026, 11, 1, 0, 40), None), dt.date(2026, 10, 31))

    def test_not_rerun_if_month_already_logged(self):
        (self.tmp / "sync-log.csv").write_text("run_at_sgt,status\n2026-10-31 23:02,Successful\n")
        self.assertIsNone(self.sync.late_start_date(self.at(2026, 11, 1, 0, 40), None))

    def test_rerun_if_logged_run_failed(self):
        (self.tmp / "sync-log.csv").write_text("run_at_sgt,status\n2026-10-31 23:02,Failed\n")
        self.assertEqual(self.sync.late_start_date(self.at(2026, 11, 1, 0, 40), None), dt.date(2026, 10, 31))

    def test_daytime_on_first_is_not_month_end(self):
        self.assertIsNone(self.sync.late_start_date(self.at(2026, 11, 1, 9, 0), None))


# ------------------------------------------------------------ workbook writes --

@unittest.skipUnless(HAS_SOFFICE, "LibreOffice not installed")
class ApplyTests(Base):
    def test_demo_rows_already_removed(self):
        self.assertEqual(self.h.listings(), [])
        if HAS_SHEETJS:
            self.assertEqual(self.h.site_reads(), 0)

    def test_osm_candidate_refused_while_publishing_off(self):
        self.h.sync(BASE)
        self.h.approve("osm:node/1")
        before = file_hash(self.h.wb)
        r = self.h.apply()
        self.assertIn("OpenStreetMap publishing is off", r.stdout)
        self.assertEqual(before, file_hash(self.h.wb))

    def test_certified_listing_from_certificate(self):
        self.h.write("verifications.csv", [verification()])
        r = self.h.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [row] = self.h.listings()
        self.assertEqual(row["ID"], "est-001")
        self.assertEqual(row["Listing Status"], "Halal certified")
        self.assertEqual(row["Certification Status"], "Halal-certified (Muis)")
        self.assertEqual(str(row["Halal Certified"]).upper(), "TRUE")
        self.assertEqual(str(row["Certificate Expiry"])[:10], "2027-06-30")
        self.assertIn("EERT00001234", row["Basis of Listing"])
        self.assertIn("verified 2026-10-20", row["Basis of Listing"])
        self.assertEqual(row["Area / Prefecture"], "Bedok")
        v = self.h.read("verifications.csv")[0]
        self.assertEqual((v["status"], v["applied_to"]), ("applied", "est-001"))
        if HAS_SHEETJS:
            self.assertEqual(self.h.site_reads(), 1)
        # Re-running applies nothing twice.
        before = file_hash(self.h.wb)
        self.h.apply()
        self.assertEqual(before, file_hash(self.h.wb))

    def test_bad_evidence_refused_and_workbook_untouched(self):
        cases = {
            "V-exp": {"certificate_expiry": "2026-09-30"},
            "V-noev": {"evidence_ref": ""},
            "V-type": {"evidence_type": "heard from a friend"},
            "V-pii": {"evidence_ref": "emailed by owner@restoran.sg", "establishment_name": "Other Place"},
            "V-old": {"verified_on": "2026-08-01"},
            "V-body": {"certifying_body": "Muis"},
        }
        self.h.write("verifications.csv", [verification(verification_id=k, **v) for k, v in cases.items()])
        before = file_hash(self.h.wb)
        r = self.h.apply()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(before, file_hash(self.h.wb))
        notes = {v["verification_id"]: v["notes"] for v in self.h.read("verifications.csv")}
        self.assertIn("expired", notes["V-exp"])
        self.assertIn("evidence_ref is required", notes["V-noev"])
        self.assertIn("evidence_type", notes["V-type"])
        self.assertIn("email address", notes["V-pii"])
        self.assertIn("older than", notes["V-old"])
        self.assertIn("certifying_body", notes["V-body"])
        self.assertTrue(all(v["status"] == "approved" for v in self.h.read("verifications.csv")))

    def enable_osm(self):
        st = json.loads((self.h.tool / "settings.json").read_text())
        st["osm_publishing_accepted"] = True
        (self.h.tool / "settings.json").write_text(json.dumps(st))

    def test_community_listings_go_to_separate_file_with_stable_ids(self):
        self.enable_osm()
        self.h.sync(BASE)
        self.h.approve("osm:node/1", "osm:node/2", "osm:node/3")
        r = self.h.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.h.listings(), [], "main workbook holds no community data")
        rows = {x["Name"]: x for x in self.h.listings(community=True)}
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(x["ID"].startswith("com-") for x in rows.values()))
        nasi = rows["Nasi Lemak House"]
        self.assertEqual(nasi["Listing Status"], "Community suggested — not verified")
        self.assertEqual(nasi["Certification Status"], "Not verified — community-suggested")
        self.assertIn(str(nasi["Halal Certified"] or ""), ("", "None"))
        self.assertIn("not evidence of halal certification", nasi["Basis of Listing"])
        self.assertIn("OpenStreetMap", nasi["Additional Notes"])
        self.assertEqual(nasi["Area / Prefecture"], "Woodlands")
        self.assertNotIn("every stall", nasi["Basis of Listing"])
        wb = openpyxl.load_workbook(self.h.cwb)
        self.assertIn("Licence", wb.sheetnames)
        if HAS_SHEETJS:
            self.assertEqual(self.h.site_reads(community=True), 3)
        self.h.sync(BASE, today="2026-11-30")
        self.assertEqual(self.h.candidates()["osm:node/1"]["match_status"], "listed")
        self.assertEqual(self.h.read("sync-log.csv")[-1]["new"], "0")

    def test_quality_gates(self):
        self.enable_osm()
        stale = node(6, "Old Kopitiam", "123456", timestamp="2016-01-01T00:00:00Z")
        shop = node(7, "Corner Mart", "234567", amenity=None, shop="convenience")
        shop["tags"].pop("amenity")
        closed = node(8, "Gone Cafe", "345678", **{"disused:amenity": "cafe"})
        self.h.sync(BASE + [stale, shop, closed])
        c = self.h.candidates()
        self.assertEqual(c["osm:node/1"]["quality_tier"], "publishable")
        self.assertEqual(c["osm:node/5"]["quality_tier"], "needs_location")
        self.assertEqual(c["osm:node/6"]["quality_tier"], "needs_check")
        self.assertEqual(c["osm:node/7"]["quality_tier"], "rejected")
        self.assertEqual(c["osm:node/8"]["quality_tier"], "rejected")
        self.h.approve("osm:node/5", "osm:node/6", "osm:node/7", "osm:node/8")
        before = file_hash(self.h.wb)
        r = self.h.apply()
        self.assertEqual(r.stdout.count("REFUSED"), 4, r.stdout)
        self.assertFalse(self.h.cwb.exists() and self.h.listings(community=True))
        # An administrator who confirms the stale record still operates can publish it.
        rows = self.h.read("candidates.csv")
        for x in rows:
            if x["source_id"] == "osm:node/6":
                x["review_note"] = "checked open 2026-10"
        self.h.write("candidates.csv", rows)
        r = self.h.apply()
        self.assertIn("1 community listing(s) added", r.stdout)
        self.assertEqual(before, file_hash(self.h.wb))

    def test_food_centre_wording_does_not_imply_every_stall_is_halal(self):
        self.enable_osm()
        venue = node(9, "Adam Food Centre", "289876", amenity="food_court")
        self.h.sync(BASE + [venue])
        self.h.approve("osm:node/9")
        r = self.h.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [row] = self.h.listings(community=True)
        self.assertIn("does not mean every stall is halal", row["Basis of Listing"])

    def test_certifying_a_community_listing_moves_it(self):
        self.enable_osm()
        self.h.sync(BASE)
        self.h.approve("osm:node/1", "osm:node/2", "osm:node/3")
        self.h.apply()
        comm = {x["Name"]: x["ID"] for x in self.h.listings(community=True)}
        self.h.write("verifications.csv", [verification(
            target=comm["Prata Corner"], establishment_name="Prata Corner", address="1 Ang Mo Kio Ave 10",
            postal_code="560456")])
        r = self.h.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [cert] = self.h.listings()
        self.assertEqual((cert["Name"], cert["Listing Status"]), ("Prata Corner", "Halal certified"))
        after = {x["Name"]: x["ID"] for x in self.h.listings(community=True)}
        self.assertEqual(after, {k: v for k, v in comm.items() if k != "Prata Corner"}, "other IDs unchanged")
        self.assertEqual(self.h.candidates()["osm:node/2"]["directory_id"], cert["ID"])
        if HAS_SHEETJS:
            self.assertEqual(self.h.site_reads(), 1)
            self.assertEqual(self.h.site_reads(community=True), 2)

    def test_closure_after_publication_flagged_not_removed(self):
        self.enable_osm()
        self.h.sync(BASE)
        self.h.approve("osm:node/1")
        self.h.apply()
        closed = [dict(e, tags=dict(e["tags"])) for e in BASE]
        closed[0]["tags"]["disused:amenity"] = "restaurant"
        self.h.sync(closed, today="2026-11-30")
        self.assertEqual(len(self.h.listings(community=True)), 1)
        self.assertIn("Source reports closed", {i["issue"] for i in self.h.read("directory-issues.csv")})

    def test_certify_candidate_by_source_id(self):
        self.h.sync(BASE)
        self.h.write("verifications.csv", [verification(
            target="osm:node/4", establishment_name="Burger Barn @ Jurong", address="1 Jurong West Central 2",
            postal_code="609601")])
        r = self.h.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [row] = self.h.listings()
        self.assertEqual(row["Listing Status"], "Halal certified")
        self.assertNotIn("OpenStreetMap", str(row["Additional Notes"] or ""), "certified rows use certificate data")
        self.assertEqual(self.h.candidates()["osm:node/4"]["review_status"], "promoted")

    def test_duplicate_verification_refused(self):
        self.h.write("verifications.csv", [verification()])
        self.h.apply()
        self.h.write("verifications.csv", [verification(verification_id="V-002")])
        before = file_hash(self.h.wb)
        r = self.h.apply()
        self.assertIn("already listed as est-001", r.stdout)
        self.assertEqual(before, file_hash(self.h.wb))

    def test_expired_certification_withdrawn_at_month_end(self):
        self.h.write("verifications.csv", [verification(certificate_expiry="2026-11-15")])
        self.h.apply(today="2026-10-31")
        r = self.h.sync(BASE, today="2026-11-30")
        self.assertEqual(r.returncode, 0, r.stderr)
        [row] = self.h.listings()
        self.assertEqual(row["Listing Status"], "Pending verification")
        self.assertIn(str(row["Halal Certified"] or ""), ("", "None"))
        self.assertIn("expired", row["Certification Status"])
        issues = {i["issue"] for i in self.h.read("directory-issues.csv")}
        self.assertIn("Certified status withdrawn", issues)
        if HAS_SHEETJS:
            self.assertEqual(self.h.site_reads(), 1)

    def test_expiring_and_reverification_flags(self):
        self.h.write("verifications.csv", [verification(certificate_expiry="2026-11-20")])
        self.h.apply(today="2026-10-31")
        self.h.sync(BASE, today="2026-10-31")
        kinds = {i["issue"] for i in self.h.read("directory-issues.csv")}
        self.assertIn("Certificate expiring", kinds)

    def test_failed_recalculation_leaves_workbook_untouched(self):
        self.h.write("verifications.csv", [verification()])
        before = file_hash(self.h.wb)
        no_office = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep)
                                    if not (Path(p) / "soffice").exists() and not (Path(p) / "libreoffice").exists())
        r = self.h.apply(env={"PATH": no_office})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("LibreOffice is required", r.stderr)
        self.assertEqual(before, file_hash(self.h.wb))
        self.assertEqual(self.h.read("verifications.csv")[0]["status"], "approved")

    def test_remove_demo_with_backup(self):
        backup = TOOL / "backups" / "2026-10-16-before-demo-removal.xlsx"
        if not backup.exists():
            self.skipTest("demo backup not present")
        shutil.copy(backup, self.h.wb)
        r = self.h.run("remove_demo.py", "--apply", "--workbook", str(self.h.wb))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Removed 8 demo listing(s)", r.stdout)
        self.assertEqual(self.h.listings(), [])
        wb = openpyxl.load_workbook(self.h.wb)
        ws = wb["Establishments"]
        self.assertEqual(wb.sheetnames, ["Establishments", "Singapore_Postal_Lookup", "Japan_Prefecture_Lookup",
                                         "Lists", "Instructions"])
        self.assertEqual(sum(1 for c in ws[2] if isinstance(c.value, str) and c.value.startswith("=")), 6)


if __name__ == "__main__":
    unittest.main()
