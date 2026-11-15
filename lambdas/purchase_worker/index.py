"""Persist each order once and hand it off to a Standard Step Functions workflow."""

import hashlib
import json
import logging
import os
import re
import time

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
REQUIRED_FIELDS = ("orderId", "userId", "eventId", "seatId")
# Never recreate an execution when its 90-day name protection may have elapsed.
MAX_PENDING_AGE = 89 * 24 * 60 * 60


def _process(record):
    order = json.loads(record["body"])
    if not isinstance(order, dict) or set(order) != set(REQUIRED_FIELDS):
        raise ValueError("Order must contain exactly the four purchase fields")
    for field in REQUIRED_FIELDS:
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
    if not re.fullmatch(r"[1-9][0-9]{0,9}", order["seatId"]):
        raise ValueError("seatId must be a canonical positive integer string")

    workflow_input = json.dumps(order, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    fingerprint = hashlib.sha256(workflow_input.encode("utf-8")).hexdigest()
    table = boto3.resource("dynamodb").Table(os.environ["ORDERS_TABLE"])
    now = int(time.time())
    item = {
        **order,
        "requestFingerprint": fingerprint,
        "workflowInput": workflow_input,
        "workflowArn": os.environ.get("WORKFLOW_ARN", ""),
        "createdAt": now,
        "orderStatus": "PENDING",
        "dispatchStatus": "PENDING",
    }
    if not item["workflowArn"]:
        raise RuntimeError("WORKFLOW_ARN is not configured")
    if not re.fullmatch(
        r"arn:[a-z0-9-]+:states:[a-z0-9-]+:[0-9]{12}:stateMachine:[A-Za-z0-9_-]+",
        item["workflowArn"],
    ):
        raise ValueError("WORKFLOW_ARN must be an unqualified state machine ARN")

    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(orderId)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        item = table.get_item(Key={"orderId": order["orderId"]}, ConsistentRead=True).get("Item")
        if (
            not item
            or item.get("requestFingerprint") != fingerprint
            or item.get("workflowInput") != workflow_input
            or any(item.get(field) != order[field] for field in REQUIRED_FIELDS)
        ):
            raise ValueError("Order identity conflicts with the persisted purchase") from exc

    if item["dispatchStatus"] == "STARTED":
        return
    if now - item["createdAt"] >= MAX_PENDING_AGE:
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
        except Exception as exc:
            logger.error("Purchase message %s failed (%s)", message_id, type(exc).__name__)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
