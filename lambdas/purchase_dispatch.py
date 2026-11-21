"""Persist the dispatch record shared by purchase intake and the SQS worker."""

import hashlib
import json
import os
import re
import time

from botocore.exceptions import ClientError


def serialize_order(order):
    return json.dumps(order, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def order_fingerprint(workflow_input):
    return hashlib.sha256(workflow_input.encode("utf-8")).hexdigest()


def read_order(table, order_id):
    return table.get_item(Key={"orderId": order_id}, ConsistentRead=True).get("Item")


def persist_pending_order(table, order, workflow_input):
    workflow_arn = os.environ["WORKFLOW_ARN"]
    if not re.fullmatch(
        r"arn:[a-z0-9-]+:states:[a-z0-9-]+:[0-9]{12}:stateMachine:[A-Za-z0-9_-]+",
        workflow_arn,
    ):
        raise ValueError("WORKFLOW_ARN must be an unqualified state machine ARN")

    item = {
        **order,
        "requestFingerprint": order_fingerprint(workflow_input),
        "workflowInput": workflow_input,
        "workflowArn": workflow_arn,
        "createdAt": int(time.time()),
        "orderStatus": "PENDING",
        "dispatchStatus": "PENDING",
    }
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(orderId)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        item = read_order(table, order["orderId"])
        if item is None:
            raise RuntimeError("Order disappeared after a conditional write") from exc
    return item
