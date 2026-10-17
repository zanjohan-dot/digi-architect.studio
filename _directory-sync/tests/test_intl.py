"""Tests for Malaysia / Japan listings (dsync.intl and research_build)."""
import datetime as dt
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from dsync.intl import TownIndex, dedupe_intl, name_key, names_for, norm_postal_intl  # noqa: E402
import research_build as rb  # noqa: E402

TODAY = dt.date(2026, 10, 17)


def el(i, tags, lat=35.68, lon=139.76, ts="2025-06-01T00:00:00Z", kind="node"):
    return {"type": kind, "id": i, "lat": lat, "lon": lon, "timestamp": ts, "tags": tags}


TOWNS = TownIndex([{"name": "Tokyo", "lat": 35.68, "lon": 139.76, "place": "city"},
                   {"name": "Johor Bahru", "lat": 1.46, "lon": 103.76, "place": "city"}])


class NamesAndPostcodes(unittest.TestCase):
    def test_japanese_name_key_kept(self):
        self.assertEqual(name_key("ハラールラーメン 新宿店"), name_key("ハラールラーメン新宿店".replace("ラーメン", "ラーメン ")))
        self.assertTrue(name_key("らーめん 山田"))  # norm_name would return ""

    def test_postcodes(self):
        self.assertEqual(norm_postal_intl("１６０-００２２", "JP"), "160-0022")
        self.assertEqual(norm_postal_intl("1600022", "JP"), "160-0022")
        self.assertEqual(norm_postal_intl("81300", "MY"), "81300")
        self.assertEqual(norm_postal_intl("8130", "MY"), "")
        self.assertEqual(norm_postal_intl("123-45", "JP"), "")

    def test_display_and_local_names(self):
        self.assertEqual(names_for({"name": "らーめん山田", "name:en": "Ramen Yamada"}, "JP"), ("Ramen Yamada", "らーめん山田"))
        self.assertEqual(names_for({"name": "らーめん山田"}, "JP"), ("らーめん山田", ""))
        self.assertEqual(names_for({"name": "Restoran Ali"}, "MY"), ("Restoran Ali", ""))


class Classification(unittest.TestCase):
    def rec(self, tags, **kw):
        tags = {"amenity": "restaurant", "name": "Test", "addr:postcode": "1600022", **tags}
        return rb.record(el(kw.pop("i", 1), tags, **kw), "JP", "Tokyo", TOWNS)

    def test_limited_means_selected_items(self):
        r = self.rec({"diet:halal": "limited"})
        self.assertEqual(r["halal_scope"], "Selected halal items only (community report)")
        tier, notes = rb.grade(r, "JP", TODAY)
        self.assertEqual(tier, "publishable")
        self.assertIn("selected dishes", notes)
        row = rb.listing_row({**r, "quality_notes": notes}, TODAY, lambda s: "com-x")
        self.assertIn("some dishes here are halal", row["Basis of Listing"])
        self.assertEqual(row["Listing Status"], "Community suggested — not verified")
        self.assertEqual(row["Certification Status"], "Not verified — community-suggested")
        self.assertEqual(row["Muslim-Owned"], "Unknown")

    def test_osm_certification_note_is_never_certification(self):
        r = self.rec({"diet:halal": "only", "halal:certification": "Japan Halal Association"})
        self.assertTrue(r["certification_claim"])
        row = rb.listing_row({**r, "quality_notes": ""}, TODAY, lambda s: "com-x")
        self.assertNotIn("Halal Certified", row)
        self.assertIn("has not been checked", row["Additional Notes"])
        self.assertIsNone(row.get("Certifying Body"))

    def test_vegetarian_or_pork_free_is_not_a_halal_claim(self):
        r = rb.record(el(9, {"amenity": "restaurant", "name": "Veg", "diet:vegetarian": "only",
                             "diet:pork": "no"}), "JP", "Tokyo", TOWNS)
        self.assertEqual(r["halal_claim"], "")
        self.assertEqual(r["halal_scope"], "")

    def test_stale_and_closed(self):
        r = self.rec({"diet:halal": "yes"}, ts="2018-01-01T00:00:00Z")
        self.assertEqual(rb.grade(r, "JP", TODAY)[0], "needs_check")
        r = self.rec({"diet:halal": "yes", "disused:amenity": "restaurant"})
        self.assertEqual(rb.grade(r, "JP", TODAY)[0], "rejected")
        r = self.rec({"diet:halal": "yes"}, lat=1.3, lon=103.8)
        self.assertEqual(rb.grade(r, "JP", TODAY)[0], "rejected")

    def test_not_open_or_pork_held_back(self):
        r = self.rec({"diet:halal": "yes", "name": "Sajian Warisan (opening soon)"})
        self.assertEqual(rb.grade(r, "JP", TODAY)[0], "needs_check")
        r = self.rec({"diet:halal": "yes", "name": "とんかつ 山田"})
        tier, notes = rb.grade(r, "JP", TODAY)
        self.assertEqual(tier, "needs_check")
        self.assertIn("pork", notes)
        r = rb.record(el(7, {"amenity": "restaurant", "name": "Restoran Bak Kut Teh", "diet:halal": "yes"},
                         lat=1.46, lon=103.76), "MY", "Johor", TOWNS)
        self.assertEqual(rb.grade(r, "MY", TODAY)[0], "needs_check")

    def test_contradictory_halal_and_non_halal_held_back(self):
        r = self.rec({"diet:halal": "yes", "diet:non-halal": "yes"})
        tier, notes = rb.grade(r, "JP", TODAY)
        self.assertEqual(tier, "needs_check")
        self.assertIn("contradictory", notes)

    def test_food_court_wording(self):
        r = rb.record(el(5, {"amenity": "food_court", "name": "Food Court A", "diet:halal": "yes"},
                         lat=1.46, lon=103.76), "MY", "Johor", TOWNS)
        row = rb.listing_row({**r, "quality_notes": ""}, TODAY, lambda s: "com-y")
        self.assertIn("does not mean every stall is halal", row["Basis of Listing"])
        self.assertEqual(r["city"], "Johor Bahru")
        self.assertEqual(r["city_basis"], "nearest town")


class Dedupe(unittest.TestCase):
    def test_node_and_building_and_romanised(self):
        a = rb.record(el(1, {"amenity": "restaurant", "name": "らーめん山田", "name:en": "Ramen Yamada"}), "JP", "Tokyo", TOWNS)
        b = rb.record(el(2, {"amenity": "restaurant", "name": "らーめん山田"}, lat=35.6802, kind="way"), "JP", "Tokyo", TOWNS)
        c = rb.record(el(3, {"amenity": "restaurant", "name": "Ramen Yamada"}, lat=35.70), "JP", "Tokyo", TOWNS)  # 2 km away: branch
        n = dedupe_intl([a, b, c])
        self.assertEqual(n, 1)
        self.assertTrue(a["duplicate_of"] or b["duplicate_of"])
        self.assertFalse(c["duplicate_of"])
        dup = a if a["duplicate_of"] else b
        self.assertEqual(rb.grade(dup, "JP", TODAY)[0], "needs_check")


if __name__ == "__main__":
    unittest.main()


class EvidenceTiers(unittest.TestCase):
    CHAINS = [dict(pattern=p, chain=n, status=s, certifier="JAKIM", statement="x", source_url="https://example.org",
                   source_date="", checked="2026-10-17", _re=__import__("re").compile(p, 2))
              for p, n, s in (("marry ?brown", "Marrybrown", "reported"), ("zanmai", "Sushi Zanmai", "contradicted"))]

    def my(self, name, i=11):
        r = rb.record(el(i, {"amenity": "restaurant", "name": name, "diet:halal": "yes"}, lat=1.46, lon=103.76),
                      "MY", "Johor", TOWNS)
        r["quality_tier"], r["quality_notes"] = rb.grade(r, "MY", TODAY)
        rb.apply_chain(r, self.CHAINS)
        return r

    def test_chain_statement_is_reported_not_certified(self):
        r = self.my("Marrybrown Johor Bahru")
        row = rb.chain_row(rb.listing_row(r, TODAY, lambda s: "com-z"), r["chain"])
        self.assertEqual(row["Listing Status"], "Certification reported — not confirmed")
        self.assertIsNone(row.get("Halal Certified"))
        self.assertIn("not confirmed", row["Certification Status"])

    def test_contradicted_chain_held_back(self):
        r = self.my("Sushi Zanmai", i=12)
        self.assertEqual(r["quality_tier"], "needs_check")

    def research(self, **kw):
        base = {f: "" for f in ("id", "country", "state", "city", "name", "local_name", "address", "local_address",
                                "postal_code", "latitude", "longitude", "establishment_type", "cuisine", "website",
                                "halal_scope", "cert_status", "certifier", "listed_by", "establishment_declaration",
                                "certifier_confirmation", "tourism_listing", "openstreetmap_report", "osm_source_id",
                                "muslim_owned", "pork_served_on_premises", "alcohol_served",
                                "cooking_alcohol_in_halal_items", "separate_kitchen_or_utensils",
                                "advance_reservation_required", "prayer_space", "operating_status",
                                "latest_source_date", "not_yet_verified", "notes", "sources", "last_checked")}
        base.update(id="res-1", country="Japan", state="Tokyo", name="Test", address="1-1 Ginza", **kw)
        return base

    def test_research_tiers_stay_separate(self):
        self.assertEqual(rb.research_tier(self.research(cert_status="confirmed", certifier="X")), "certified")
        self.assertEqual(rb.research_tier(self.research(cert_status="reported")), "certification_reported")
        self.assertEqual(rb.research_tier(self.research(tourism_listing="Listed by a tourism body")), "self_declared")
        self.assertEqual(rb.research_tier(self.research(muslim_owned="Yes")), "unsupported")
        row = rb.research_row(self.research(cert_status="reported", certifier="JHA", muslim_owned="Yes"), TODAY)
        self.assertIsNone(row["Halal Certified"])
        self.assertEqual(row["Muslim-Owned"], "Yes (source cited)")

    def test_old_or_guide_only_records_need_checking(self):
        ready, issues = rb.research_readiness(self.research(establishment_declaration="halal menu", latest_source_date="2019"), TODAY)
        self.assertEqual(ready, "needs_check")
        ready, _ = rb.research_readiness(self.research(listed_by="Tokyo Convention & Visitors Bureau",
                                                       tourism_listing="Listed", latest_source_date="2025-11"), TODAY)
        self.assertEqual(ready, "needs_check")
        ready, _ = rb.research_readiness(self.research(establishment_declaration="halal menu", latest_source_date="2025"), TODAY)
        self.assertEqual(ready, "ready")

    def test_nothing_published_without_approval(self):
        gate = rb.load_publication()
        for cc in ("MY", "JP"):
            self.assertFalse(any(gate[cc].values()), f"{cc} publication must stay off until the owner approves")


class LandingPages(unittest.TestCase):
    def test_landing_pages_are_not_directories(self):
        for name in ("muslim-friendly-directory-malaysia.html", "muslim-friendly-directory-japan.html"):
            page = (HERE.parent / name).read_text(encoding="utf-8")
            self.assertNotIn("xlsx.full.min.js", page)
            self.assertNotIn('id="recordsGrid"', page)
            self.assertIn("/muslim-friendly-directory?country=", page)
