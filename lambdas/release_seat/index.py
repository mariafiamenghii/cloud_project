import os

import boto3

_ddb = boto3.resource("dynamodb")


def handler(event, context):
    # Compensation step. Step Functions routes the TakePayment error here with
    # ResultPath preserving the original order, so the order fields are at the
    # top level of the state. This must always succeed (unconditional write).
    table = _ddb.Table(os.environ["SEATS_TABLE"])
    table.update_item(
        Key={"eventId": event["eventId"], "seatId": event["seatId"]},
        UpdateExpression="SET #s = :free REMOVE holdExpiresAt, heldBy, heldForUser",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":free": "free"},
    )

    return {"orderId": event["orderId"], "seatStatus": "free", "released": True}
