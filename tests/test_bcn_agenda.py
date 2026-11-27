import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import import_bcn_agenda as bcn  # noqa: E402
from test_categories import backend_categories  # noqa: E402


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
        self.assertEqual(item["genre"], "music")
        self.assertEqual(item["date"], "2027-01-25")
        self.assertEqual(item["externalUrl"], "https://www.palaumusica.cat/")
        self.assertIn("Ajuntament de Barcelona", item["imageAttribution"])

    def test_without_image_or_in_the_past_is_skipped(self):
        self.assertIsNone(bcn.convert(record(image=None), "2026-11-24"))
        self.assertIsNone(bcn.convert(record(start="2026-01-01T10:00:00+01:00"), "2026-11-24"))
        self.assertIsNone(bcn.convert(record(start=None), "2026-11-24"))

    def category(self, *classes):
        item = bcn.convert(record(classes=classes), "2026-11-24")
        return item and item["genre"]

    def test_city_topics_map_to_our_categories(self):
        cases = {
            ("Cuina i gastronomia",): "food",
            ("Degustacions, menjars populars, professionals, de germanor",): "food",
            ("Cursos i tallers", "Artesania i manualitats"): "workshops",
            ("Festivals",): "festivals",
            ("Activitats de Nadal",): "festivals",
            ("Cavalcades i rues",): "festivals",
            ("Exposicions",): "art",
            ("Activitats dels museus i arxius de Barcelona",): "art",
            ("Col·loquis, xerrades",): "talks",
            ("Teatre",): "theatre",
            ("Vida nocturna",): "music",
            ("Esports",): "sports",
            ("Internet i noves tecnologies",): "tech",
            ("Medi ambient, sostenibilitat, ecologia",): "sustainability",
            ("Activitats per a infants i per a famílies",): "family",
        }
        for classes, expected in cases.items():
            self.assertEqual(self.category(*classes), expected, classes)

    def test_specific_topics_win_over_broad_ones(self):
        self.assertEqual(self.category("Cursos i tallers", "Cuina i gastronomia"), "food")
        self.assertEqual(self.category("Exposicions", "Activitats de Nadal"), "festivals")
        self.assertEqual(self.category("Col·loquis, xerrades", "Medi ambient, sostenibilitat, ecologia"),
                         "sustainability")

    def test_a_concert_is_always_music(self):
        self.assertEqual(self.category("Concerts"), "music")
        self.assertEqual(self.category("Teatre", "Concerts"), "music")
        self.assertEqual(self.category("Concerts", "Activitats per a infants i per a famílies"), "music")
        self.assertEqual(self.category("Jazz, Blues", "Concerts"), "music")

    def test_events_outside_our_categories_are_skipped(self):
        self.assertIsNone(bcn.convert(record(classes=("Activitats per al públic en general",)), "2026-11-24"))
        self.assertIsNone(bcn.convert(record(classes=()), "2026-11-24"))

    def test_every_importer_category_is_a_shared_category(self):
        produced = {"music"} | {category for category, _ in bcn.CATEGORY_RULES}
        self.assertLessEqual(produced, set(backend_categories()))
        self.assertLessEqual(set(bcn.CATEGORY_CAPS), set(backend_categories()))

    def test_link_falls_back_to_venue_page_and_ignores_bad_urls(self):
        self.assertEqual(bcn.convert(record(web="not a url"), "2026-11-24")["externalUrl"], "https://www.barcelona.cat/venue")

    def test_free_entry_gets_price_zero_otherwise_no_price(self):
        free = record()
        free["tickets_data"] = [{"id": 3, "name": "Lliure"}]
        item = bcn.convert(free, "2026-11-24")
        self.assertEqual((item["price"], item["currency"]), (0, "EUR"))
        self.assertNotIn("price", bcn.convert(record(), "2026-11-24"))

    def test_city_spelling_is_normalised(self):
        for town, expected in (("BARCELONA", "Barcelona"), (" barcelona ", "Barcelona"), ("", "Barcelona"),
                               (None, "Barcelona"), ("L'Hospitalet de Llobregat", "L'Hospitalet de Llobregat")):
            rec = record()
            rec["addresses"][0]["town"] = town
            self.assertEqual(bcn.convert(rec, "2026-11-24")["city"], expected)

    def test_pick_caps_each_category_and_removes_duplicates(self):
        records = [record(name=f"C{i}", reg=f"R{i}", start=f"2027-01-{10 + i:02d}T20:00:00+01:00") for i in range(5)]
        records.append(records[0])
        self.assertEqual(len(bcn.pick(records, "2026-11-24", 3, caps={})), 3)
        self.assertEqual(len(bcn.pick(records, "2026-11-24", 10, caps={})), 5)
    def test_pick_mixes_categories_with_a_lower_music_cap(self):
        def batch(prefix, classes, n):
            return [record(name=f"{prefix}{i}", reg=f"{prefix}{i}", classes=classes,
                           start=f"2027-01-{10 + i:02d}T20:00:00+01:00") for i in range(n)]
        records = batch("M", ("Concerts",), 10) + batch("F", ("Cuina i gastronomia",), 10)
        chosen = bcn.pick(records, "2026-11-24", 6, caps={"music": 2})
        counts = {c: sum(1 for i in chosen if i["genre"] == c) for c in ("music", "food")}
        self.assertEqual(counts, {"music": 2, "food": 6})
        self.assertEqual([i["name"] for i in chosen if i["genre"] == "music"], ["M0", "M1"])  # soonest first
    def test_pick_keeps_one_date_of_a_repeated_show(self):
        records = [record(name="Espectacle 'A taula!'", reg=f"R{i}", classes=("Teatre",),
                          start=f"2027-01-{10 + i:02d}T20:00:00+01:00") for i in range(4)]
        chosen = bcn.pick(records, "2026-11-24", 10)
        self.assertEqual([(i["name"], i["date"]) for i in chosen], [("Espectacle 'A taula!'", "2027-01-10")])


if __name__ == "__main__":
    unittest.main()
