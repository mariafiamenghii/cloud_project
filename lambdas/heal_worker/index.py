"""Re-enable the purchase worker's SQS trigger after an AWS Academy lab restart.

When the Academy lab stops, LabRole temporarily loses its SQS permissions. Lambda's
queue poller then fails and Lambda disables the trigger itself (CloudTrail event
LambdaESMDisabled; the mapping reports StateTransitionReason USER_INITIATED). It is
not re-enabled when the lab starts again, so purchases wait in the queue.

EventBridge runs this function every five minutes. Each run:

1. Reads the one mapping named by MAPPING_UUID and refuses to act unless it connects
   QUEUE_ARN to WORKER_FUNCTION_NAME.
2. Does nothing unless the mapping is Disabled.
3. Does nothing while the maintenance flag (SSM parameter MAINTENANCE_PARAMETER) is
   "on", or when the flag cannot be read.
4. Checks that the worker's role can reach the queue again before enabling.
5. Enables that single mapping.

It never disables a trigger and never touches orders, tickets or inventory: it only
uses the Lambda, SQS (read-only), SSM (read-only) and STS APIs.
"""

import json
import logging
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MAINTENANCE_ON = "on"
MAINTENANCE_OFF = "off"


class HealConfigError(Exception):
    """The deployed configuration does not describe the mapping we expect."""


def _log(level, outcome, **fields):
    logger.log(level, json.dumps({"component": "heal-worker", "outcome": outcome, **fields}, default=str))


def _error_code(exc):
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code", "ClientError")
    return type(exc).__name__


def _role_of(arn):
    """Return the role name from a role ARN or an assumed-role session ARN."""
    resource = arn.split(":", 5)[-1]
    if resource.startswith("assumed-role/"):
        return resource.split("/")[1]
    if resource.startswith("role/"):
        return resource.split("/")[-1]
    return None


def _maintenance_state(ssm, name):
    """Return "on", "off" or None (unreadable or invalid, so do not enable)."""
    try:
        value = ssm.get_parameter(Name=name)["Parameter"]["Value"].strip().lower()
    except (ClientError, BotoCoreError) as exc:
        _log(logging.ERROR, "maintenance_flag_unreadable", parameter=name, error=_error_code(exc),
             detail=str(exc), action="not re-enabling; will retry on the next schedule")
        return None
    if value not in (MAINTENANCE_ON, MAINTENANCE_OFF):
        _log(logging.ERROR, "maintenance_flag_invalid", parameter=name, value=value,
             action="not re-enabling; set the parameter to 'on' or 'off'")
        return None
    return value


def handler(event, context):
    worker = os.environ["WORKER_FUNCTION_NAME"]
    uuid = os.environ["MAPPING_UUID"]
    queue_arn = os.environ["QUEUE_ARN"]
    queue_url = os.environ["QUEUE_URL"]
    flag_name = os.environ["MAINTENANCE_PARAMETER"]
    base = {"mappingUuid": uuid, "worker": worker, "queue": queue_arn}

    lam = boto3.client("lambda")
    try:
        mapping = lam.get_event_source_mapping(UUID=uuid)
    except (ClientError, BotoCoreError) as exc:
        _log(logging.ERROR, "mapping_lookup_failed", error=_error_code(exc), detail=str(exc), **base)
        raise

    # Only ever act on the purchase queue -> purchase worker mapping.
    mapped_function = mapping.get("FunctionArn", "")
    if mapping.get("EventSourceArn") != queue_arn or mapped_function.split(":function:")[-1].split(":")[0] != worker:
        _log(logging.ERROR, "mapping_mismatch", foundQueue=mapping.get("EventSourceArn"),
             foundFunction=mapped_function, action="refusing to modify an unexpected mapping", **base)
        raise HealConfigError(f"Mapping {uuid} does not connect {queue_arn} to {worker}")

    state = mapping.get("State")
    reason = mapping.get("StateTransitionReason")
    if state != "Disabled":
        # Enabled, Enabling, Updating, Creating, Disabling, ...: nothing to heal.
        _log(logging.INFO, "no_action", state=state, reason=reason, **base)
        return {"outcome": "no_action", "state": state}

    _log(logging.WARNING, "trigger_disabled_detected", state=state, reason=reason,
         lastModified=mapping.get("LastModified"), **base)

    maintenance = _maintenance_state(boto3.client("ssm"), flag_name)
    if maintenance is None:
        return {"outcome": "maintenance_flag_unreadable", "state": state}
    if maintenance == MAINTENANCE_ON:
        _log(logging.WARNING, "maintenance_hold", parameter=flag_name,
             action="leaving trigger disabled on purpose", **base)
        return {"outcome": "maintenance_hold", "state": state}

    # The probe below runs with this function's credentials, so it only proves
    # anything about the worker if both functions share the same role.
    try:
        worker_role = _role_of(lam.get_function_configuration(FunctionName=worker)["Role"])
        own_role = _role_of(boto3.client("sts").get_caller_identity()["Arn"])
    except (ClientError, BotoCoreError) as exc:
        _log(logging.WARNING, "permissions_not_ready", check="role_lookup", error=_error_code(exc),
             detail=str(exc), action="will retry on the next schedule", **base)
        return {"outcome": "permissions_not_ready", "state": state}
    if not worker_role or worker_role != own_role:
        _log(logging.ERROR, "role_mismatch", workerRole=worker_role, healRole=own_role,
             action="cannot verify worker permissions; not re-enabling", **base)
        raise HealConfigError("Heal worker and purchase worker must share the same execution role")

    # Read-only probe. ReceiveMessage/DeleteMessage are not probed because receiving
    # would change message visibility and receive counts. If they are still denied,
    # Lambda disables the trigger again and the next run retries; no message is lost.
    try:
        attributes = boto3.client("sqs").get_queue_attributes(
            QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages"]
        )["Attributes"]
    except (ClientError, BotoCoreError) as exc:
        _log(logging.WARNING, "permissions_not_ready", check="sqs:GetQueueAttributes", role=own_role,
             error=_error_code(exc), detail=str(exc), action="will retry on the next schedule", **base)
        return {"outcome": "permissions_not_ready", "state": state}
    backlog = int(attributes.get("ApproximateNumberOfMessages", 0))

    _log(logging.WARNING, "re_enable_attempt", queuedMessages=backlog, **base)
    try:
        result = lam.update_event_source_mapping(UUID=uuid, Enabled=True)
    except (ClientError, BotoCoreError) as exc:
        _log(logging.ERROR, "re_enable_failed", error=_error_code(exc), detail=str(exc), **base)
        raise

    _log(logging.WARNING, "re_enabled", newState=result.get("State"), queuedMessages=backlog, **base)
    return {"outcome": "re_enabled", "state": result.get("State"), "queuedMessages": backlog}
