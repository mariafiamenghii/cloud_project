# OWNER: person E (data). On-demand billing = pay only for what we use.

resource "aws_dynamodb_table" "events" {
  name         = "${var.prefix}-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "eventId"

  attribute {
    name = "eventId"
    type = "S"
  }
}

# One item per seat. Reserving a seat = conditional write:
# "only if status is free OR the hold (holdExpiresAt) has already expired".
# Do NOT rely on DynamoDB TTL to free seats: TTL deletion can be delayed.
resource "aws_dynamodb_table" "seats" {
  name         = "${var.prefix}-seats"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "eventId"
  range_key    = "seatId"

  attribute {
    name = "eventId"
    type = "S"
  }

  attribute {
    name = "seatId"
    type = "S"
  }
}

resource "aws_dynamodb_table" "orders" {
  name         = "${var.prefix}-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  attribute {
    name = "orderId"
    type = "S"
  }

  attribute {
    name = "userId"
    type = "S"
  }

  global_secondary_index {
    name            = "by-user"
    hash_key        = "userId"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "preferences" {
  name         = "${var.prefix}-preferences"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "userId"

  attribute {
    name = "userId"
    type = "S"
  }
}
