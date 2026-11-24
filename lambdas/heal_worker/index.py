"""Re-enable the purchase worker's queue trigger if it has been disabled.

In the AWS Academy lab the trigger between the purchase queue and the worker has
been found Disabled (reason USER_INITIATED) after the lab was stopped and started
again, and purchases then wait in the queue forever. This function runs every few
minutes from an EventBridge schedule and turns the trigger back on. Enabling it
only makes the worker process the orders that were already waiting.
"""

import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_lambda = boto3.client("lambda")


def handler(event, context):
    worker = os.environ["WORKER_FUNCTION_NAME"]
    re_enabled = []

    pages = _lambda.get_paginator("list_event_source_mappings").paginate(FunctionName=worker)
    for page in pages:
        for mapping in page["EventSourceMappings"]:
            if mapping.get("State") == "Disabled":
                _lambda.update_event_source_mapping(UUID=mapping["UUID"], Enabled=True)
                logger.warning("Re-enabled the queue trigger %s of %s", mapping["UUID"], worker)
                re_enabled.append(mapping["UUID"])

    return {"reEnabled": re_enabled}
