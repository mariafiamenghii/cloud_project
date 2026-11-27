"""Recommendation scoring with event categories and followed associations."""
import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from test_categories import backend_categories
from test_purchases import load_lambda

# Only the scoring functions are tested; no AWS call is made. A region is still
# needed because the module creates its DynamoDB resource when it is imported.
with patch.dict(os.environ, {"AWS_DEFAULT_REGION": "us-east-1"}):
    recommend = load_lambda("recommend")


def event(**fields):
    return {"eventId": fields.pop("eventId", "e1"), "date": "2027-01-10", **fields}


class ScoreTests(unittest.TestCase):
    def test_category_interest_scores_three_with_a_reason(self):
        score, why = recommend.score_event(event(genre="finance"), {"genres": ["finance", "food"]})
        self.assertEqual((score, why), (3, ["you're interested in finance"]))

    def test_every_shared_category_can_match(self):
        for category in backend_categories():
            score, _ = recommend.score_event(event(genre=category), {"genres": [category]})
            self.assertEqual(score, 3, category)

    def test_multi_word_categories_match_ignoring_case_and_spaces(self):
        score, why = recommend.score_event(event(genre="social impact"), {"genres": ["Social  Impact "]})
        self.assertEqual((score, why), (3, ["you're interested in social impact"]))

    def test_old_music_genres_count_as_music_both_ways(self):
        # Old imported event ("jazz") and a new survey answer ("music").
        self.assertEqual(recommend.score_event(event(genre="jazz"), {"genres": ["music"]})[0], 3)
        # New event ("music") and an old survey answer ("rock").
        self.assertEqual(recommend.score_event(event(genre="music"), {"genres": ["rock"]})[0], 3)
        # Unrelated category does not match.
        self.assertEqual(recommend.score_event(event(genre="jazz"), {"genres": ["finance"]})[0], 0)

    def test_followed_association_scores_five(self):
        prefs = {"favoriteArtists": ["ESADE Finance Club"]}
        score, why = recommend.score_event(event(artist="esade finance  club"), prefs)
        self.assertEqual(score, 5)
        self.assertEqual(why, ["by esade finance  club, which you follow"])

    def test_followed_name_can_be_part_of_the_full_name(self):
        prefs = {"favoriteArtists": ["Finance Club"]}
        self.assertEqual(recommend.score_event(event(artist="ESADE Finance Club"), prefs)[0], 5)
        # Too short to match inside another name, and no empty matches.
        self.assertEqual(recommend.score_event(event(artist="ESADE Art Club"), {"favoriteArtists": ["art"]})[0], 0)
        self.assertEqual(recommend.score_event(event(artist=""), {"favoriteArtists": [" "]})[0], 0)

    def test_city_and_budget(self):
        prefs = {"city": "Barcelona", "maxPrice": Decimal(20)}
        score, why = recommend.score_event(event(city="barcelona", price=Decimal(15)), prefs)
        self.assertEqual((score, why), (3, ["in barcelona", "fits your budget"]))
        self.assertEqual(recommend.score_event(event(price=Decimal(25)), prefs)[0], 0)

    def test_free_event_says_free_entry(self):
        score, why = recommend.score_event(event(price=0), {"maxPrice": 30})
        self.assertEqual((score, why), (1, ["free entry"]))
        # Without a saved budget the price does not score.
        self.assertEqual(recommend.score_event(event(price=0), {})[0], 0)

    def test_all_reasons_add_up(self):
        prefs = {"genres": ["networking"], "favoriteArtists": ["ESADE Finance Club"],
                 "city": "Barcelona", "maxPrice": 30}
        score, why = recommend.score_event(
            event(genre="networking", artist="ESADE Finance Club", city="Barcelona", price=10), prefs)
        self.assertEqual(score, 11)
        self.assertEqual(len(why), 4)


class RecommendTests(unittest.TestCase):
    def test_best_matches_first_then_soonest(self):
        events = [
            event(eventId="talk", genre="talks", date="2027-01-05"),
            event(eventId="fin-late", genre="finance", date="2027-02-01"),
            event(eventId="fin-soon", genre="finance", date="2027-01-20"),
            event(eventId="past", genre="finance", date="2020-01-01"),
        ]
        result = recommend.recommend(events, {"genres": ["finance"]}, "2026-12-01")
        self.assertEqual([e["eventId"] for e in result], ["fin-soon", "fin-late"])
        self.assertEqual(result[0]["reasons"], ["you're interested in finance"])

    def test_without_survey_shows_the_soonest_events(self):
        events = [event(eventId="b", date="2027-01-20"), event(eventId="a", date="2027-01-05")]
        result = recommend.recommend(events, {}, "2026-12-01")
        self.assertEqual([e["eventId"] for e in result], ["a", "b"])
        self.assertEqual(result[0]["reasons"], ["coming up soon"])


if __name__ == "__main__":
    unittest.main()
