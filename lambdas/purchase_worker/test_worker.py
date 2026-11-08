
import os
from unittest.mock import patch

from index import lambda_handler


def test_purchase_worker():
    event = {
        "Records": [
            {
                "messageId": "message-001",
                "body": (
                    '{"orderId":"ORDER-001",'
                    '"userId":"USER-123",'
                    '"eventId":"CONCERT-001",'
                    '"seatId":"A12"}'
                ),
            }
        ]
    }

    with patch.dict(os.environ, {"DRY_RUN": "true"}):
        result = lambda_handler(event, None)

    assert result == {"batchItemFailures": []}
    print("SUCCESS: purchase request processed correctly!")


if __name__ == "__main__":
    test_purchase_worker()
