"""Academy bootstrap: idempotently create the private media bucket after lab resets.

S3's denied Object Lock read prevents the standard Terraform bucket resource.
Terraform manages its security/settings; this helper never deletes a bucket.
"""
import boto3
from botocore.exceptions import ClientError

session = boto3.Session(region_name="us-east-1")
account = session.client("sts").get_caller_identity()["Account"]
bucket = "ticketing-event-images-" + account
s3 = session.client("s3")
try:
    s3.head_bucket(Bucket=bucket)
except ClientError as error:
    if error.response["Error"]["Code"] not in ("404", "NoSuchBucket"): raise
    s3.create_bucket(Bucket=bucket)
s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
    "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
})
print("Private event-image bucket is available; apply its Terraform configuration next.")
