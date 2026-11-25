import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_bcn_agenda as bcn  # noqa: E402


def record(name="Concert X", start="2027-01-25T20:00:00+01:00", classes=("Concerts", "Música clàssica"),
           image="https://img.example/a.jpg", web="https://www.palaumusica.cat/", reg="AG.1"):
    return {
        "name": name,
        "start_date": start,
        "register_id": reg,
        "classifications_data": [{"name": c} for c in classes],
        "image_data": {"image_optimized": image} if image else None,
        "addresses": [{"place": "Palau de la Música Catalana", "town": "Barcelona",
                       "related_entity_data": {"canonical_url": "https://www.barcelona.cat/venue"}}],
        "attribute_categories": [{"attributes": [{"name": "Web venda d'entrades", "values": [{"value": web}]}]}],
    }


class ConvertTests(unittest.TestCase):
    def test_concert_is_converted_as_external(self):
        item = bcn.convert(record(), "2026-11-24")
        self.assertEqual(item["source"], "barcelona_open_data")
        self.assertEqual(item["capacity"], 0)
        self.assertEqual(item["genre"], "classical")
        self.assertEqual(item["date"], "2027-01-25")
        self.assertEqual(item["externalUrl"], "https://www.palaumusica.cat/")
        self.assertIn("Ajuntament de Barcelona", item["imageAttribution"])

    def test_without_image_or_in_the_past_is_skipped(self):
        self.assertIsNone(bcn.convert(record(image=None), "2026-11-24"))
        self.assertIsNone(bcn.convert(record(start="2026-01-01T10:00:00+01:00"), "2026-11-24"))
        self.assertIsNone(bcn.convert(record(start=None), "2026-11-24"))

    def test_non_music_without_known_category_is_skipped(self):
        self.assertIsNone(bcn.convert(record(classes=("Cuina i gastronomia",)), "2026-11-24"))
        self.assertEqual(bcn.convert(record(classes=("Exposicions",)), "2026-11-24")["genre"], "art")
        self.assertEqual(bcn.convert(record(classes=("Jazz, Blues", "Concerts")), "2026-11-24")["genre"], "jazz")

    def test_music_without_style_has_no_genre_field(self):
        item = bcn.convert(record(classes=("Concerts",)), "2026-11-24")
        self.assertNotIn("genre", item)

    def test_link_falls_back_to_venue_page_and_ignores_bad_urls(self):
        self.assertEqual(bcn.convert(record(web="not a url"), "2026-11-24")["externalUrl"], "https://www.barcelona.cat/venue")

    def test_free_entry_gets_price_zero_otherwise_no_price(self):
        free = record()
        free["tickets_data"] = [{"id": 3, "name": "Lliure"}]
        item = bcn.convert(free, "2026-11-24")
        self.assertEqual((item["price"], item["currency"]), (0, "EUR"))
        self.assertNotIn("price", bcn.convert(record(), "2026-11-24"))

    def test_pick_caps_each_genre_and_removes_duplicates(self):
        records = [record(name=f"C{i}", reg=f"R{i}", start=f"2027-01-{10 + i:02d}T20:00:00+01:00") for i in range(5)]
        records.append(records[0])
        self.assertEqual(len(bcn.pick(records, "2026-11-24", 3)), 3)
        self.assertEqual(len(bcn.pick(records, "2026-11-24", 10)), 5)


if __name__ == "__main__":
    unittest.main()
