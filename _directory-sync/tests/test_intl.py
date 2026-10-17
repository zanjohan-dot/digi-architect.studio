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
