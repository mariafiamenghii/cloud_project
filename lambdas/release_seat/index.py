import os

import boto3

_ddb = boto3.resource("dynamodb")


def handler(event, context):
    # Compensation step for a failed payment. Step Functions routes the
    # TakePayment error here with ResultPath preserving the original order, so
    # the order fields are at the top level of the state.
    #
    # Only release the seat if it is still HELD BY THIS ORDER. This prevents a
    # late/duplicate compensation from freeing a seat that another order has
    # since reserved, or from undoing a seat that is already "sold".
    order_id = event["orderId"]
    table = _ddb.Table(os.environ["SEATS_TABLE"])
    try:
        table.update_item(
            Key={"eventId": event["eventId"], "seatId": event["seatId"]},
            UpdateExpression="SET #s = :free REMOVE holdExpiresAt, heldBy, heldForUser",
            ConditionExpression="#s = :held AND heldBy = :order",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":free": "free", ":held": "held", ":order": order_id},
        )
        released = True
    except _ddb.meta.client.exceptions.ConditionalCheckFailedException:
        # Seat is not held by this order (already freed, sold, or taken by
        # another order). Nothing to release; the purchase still fails cleanly.
        released = False

    return {"orderId": order_id, "seatStatus": "free" if released else "unchanged", "released": released}
