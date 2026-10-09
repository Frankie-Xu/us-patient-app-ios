"""Create the local staging S3 bucket idempotently."""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError


def main() -> None:
    bucket = os.environ["S3_BUCKET"]
    region = os.getenv("OBJECT_STORAGE_REGION", "us-east-1")
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=region,
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    )
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str((exc.response.get("Error") or {}).get("Code", ""))
        if code not in {"403", "404", "NoSuchBucket"}:
            raise
        create_kwargs = {"Bucket": bucket}
        # S3 requires an explicit location constraint for every region except
        # us-east-1.  LocalStack-compatible endpoints enforce the same rule.
        if region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": region,
            }
        client.create_bucket(**create_kwargs)
    print("staging S3 bucket ready")


if __name__ == "__main__":
    main()
