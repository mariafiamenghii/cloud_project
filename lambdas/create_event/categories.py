"""Event categories an association can choose when it publishes an event.

Single backend copy of the list. The web copy is CATEGORIES in
web/src/utils/eventMedia.ts; tests/test_categories.py fails if they diverge.
Values are stored lowercase in DynamoDB (field "genre", kept for compatibility).
"""

CATEGORIES = (
    # ESADE student association topics
    "consulting",
    "finance",
    "tech",
    "entrepreneurship",
    "marketing",
    "luxury",
    "sustainability",
    "networking",
    "sports",
    # City and culture
    "food",
    "music",
    "festivals",
    "workshops",
    "theatre",
    "art",
    "talks",
    "family",
)
