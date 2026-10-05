"""Create the local staging S3 bucket idempotently."""
from __future__ import annotations

import os

import boto3
from botocore.exceptions import ClientError


def main() -> None:
    bucket = os.environ["S3_BUCKET"]
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT"],
        region_name=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
    )
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as exc:
        code = str((exc.response.get("Error") or {}).get("Code", ""))
        if code not in {"403", "404", "NoSuchBucket"}:
            raise
        client.create_bucket(Bucket=bucket)
    print("staging S3 bucket ready")


if __name__ == "__main__":
    main()
