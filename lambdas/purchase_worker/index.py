"""Hand off purchases to a Standard Step Functions workflow."""

import json
import logging
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

from purchase_dispatch import order_fingerprint, persist_pending_order, read_order, serialize_order

logger = logging.getLogger(__name__)
REQUIRED_FIELDS = ("orderId", "userId", "eventId", "seatId")
# Never recreate an execution when its 90-day name protection may have elapsed.
MAX_PENDING_AGE = 89 * 24 * 60 * 60


def _process(record):
    order = json.loads(record["body"])
    quantity_order = isinstance(order, dict) and order.get("schemaVersion") == 2
    fields = ("orderId", "userId", "eventId") if quantity_order else REQUIRED_FIELDS
    expected = {*fields, "quantity", "schemaVersion"} if quantity_order else set(REQUIRED_FIELDS)
    if not isinstance(order, dict) or set(order) != expected:
        raise ValueError("Invalid versioned purchase fields")
    if quantity_order and (type(order["quantity"]) is not int or not 1 <= order["quantity"] <= 20):
        raise ValueError("Invalid ticket quantity")
    for field in fields:
        value = order[field]
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or len(value) > 128
        ):
            raise ValueError(f"Invalid {field}")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", order["orderId"]):
        raise ValueError("orderId must be a valid execution name")
    if not quantity_order and not re.fullmatch(r"[1-9][0-9]{0,9}", order["seatId"]):
        raise ValueError("seatId must be a canonical positive integer string")

    workflow_input = serialize_order(order)
    fingerprint = order_fingerprint(workflow_input)
    table = boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])
    item = read_order(table, order["orderId"])
    if item is None:
        # Messages queued before intake began writing orders still need a record.
        item = persist_pending_order(table, order, workflow_input)
    if (
        item.get("requestFingerprint") != fingerprint
        or item.get("workflowInput") != workflow_input
        or any(item.get(field) != order[field] for field in expected)
    ):
        raise ValueError("Order identity conflicts with the persisted purchase")

    if item["dispatchStatus"] == "STARTED":
        return
    if int(time.time()) - item["createdAt"] >= MAX_PENDING_AGE:
        raise RuntimeError("Old pending order needs manual reconciliation")

    # Use the persisted ARN and exact input even if configuration changes on retry.
    client = boto3.client("stepfunctions")
    try:
        result = client.start_execution(
            stateMachineArn=item["workflowArn"], name=order["orderId"], input=item["workflowInput"]
        )
        execution_arn = result["executionArn"]
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ExecutionAlreadyExists":
            raise
        # Closed executions also raise AlreadyExists. Verify identity before ACK;
        # failed fulfillment remains failed and must not become a new purchase.
        base_arn = item["workflowArn"].split(":stateMachine:", 1)[0]
        machine_name = item["workflowArn"].split(":stateMachine:", 1)[1].split(":", 1)[0]
        execution_arn = f"{base_arn}:execution:{machine_name}:{order['orderId']}"
        execution = client.describe_execution(executionArn=execution_arn)
        if (
            execution["input"] != item["workflowInput"]
            or execution["stateMachineArn"] != item["workflowArn"]
        ):
            raise ValueError("Existing execution does not match the persisted purchase") from exc

    # Do not overwrite workflow-owned order status or ticket fields. If this
    # write fails, redelivery reconciles the execution instead of purchasing again.
    table.update_item(
        Key={"orderId": order["orderId"]},
        UpdateExpression="SET dispatchStatus = :started, executionArn = :arn",
        ConditionExpression="requestFingerprint = :fingerprint",
        ExpressionAttributeValues={
            ":started": "STARTED",
            ":arn": execution_arn,
            ":fingerprint": fingerprint,
        },
    )


def lambda_handler(event, context):
    failures = []
    for record in event.get("Records", []):
        message_id = record["messageId"]
        try:
            _process(record)
        except ClientError as exc:
            logger.error(
                "Purchase message %s failed in %s (%s, AWS request %s)",
                message_id, exc.operation_name, exc.response["Error"]["Code"],
                exc.response.get("ResponseMetadata", {}).get("RequestId", "unavailable"),
            )
            failures.append({"itemIdentifier": message_id})
        except Exception as exc:
            logger.error("Purchase message %s failed (%s)", message_id, type(exc).__name__)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
