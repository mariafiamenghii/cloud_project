
import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REQUIRED_FIELDS = ("orderId", "userId", "eventId", "seatId")


def lambda_handler(event, context):
    """Process purchase requests received from SQS."""

    failures = []

    for record in event.get("Records", []):
        message_id = record["messageId"]

        try:
            # 1. Read the purchase request
            order = json.loads(record["body"])

            # 2. Validate required fields
            if not isinstance(order, dict):
                raise ValueError("Order must be a JSON object")

            for field in REQUIRED_FIELDS:
                if not isinstance(order.get(field), str) or not order[field].strip():
                    raise ValueError(f"Missing or invalid field: {field}")

            logger.info(
                "Processing order %s for event %s, seat %s",
                order["orderId"],
                order["eventId"],
                order["seatId"],
            )

            # 3. Start the purchase workflow
            workflow_arn = os.environ.get("WORKFLOW_ARN")

            if os.environ.get("DRY_RUN") == "true":
                logger.info("DRY RUN: workflow not started")

            elif workflow_arn:
                client = boto3.client("stepfunctions")

                client.start_execution(
                    stateMachineArn=workflow_arn,
                    name=order["orderId"],
                    input=json.dumps(order),
                )

                logger.info("Workflow started for %s", order["orderId"])

            else:
                raise RuntimeError("WORKFLOW_ARN is not configured")

        except Exception:
            logger.exception("Failed to process message %s", message_id)
            failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": failures}
