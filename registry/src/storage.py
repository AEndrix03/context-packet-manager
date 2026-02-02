import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


class S3Storage:
    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key: str | None,
        secret_key: str | None,
        force_path_style: bool = True,
    ):
        self.bucket = bucket
        self.region = region

        cfg = Config(
            region_name=region,
            s3={"addressing_style": "path" if force_path_style else "virtual"},
        )

        session = boto3.session.Session()
        self.client = session.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=cfg,
        )

    def ensure_bucket(self) -> None:
        """
        Ensure bucket exists.
        - If it exists: OK
        - If not: create it
        - If permissions are missing: raise clear error
        """
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return  # exists
        except ClientError as e:
            error = e.response.get("Error", {})
            code = error.get("Code", "")

            # Bucket does not exist → create
            if code in ("404", "NoSuchBucket", "NotFound"):
                pass
            else:
                # real error (auth, forbidden, etc.)
                raise RuntimeError(
                    f"Failed to access bucket '{self.bucket}': {code} {error.get('Message')}"
                ) from e

        # Create bucket
        try:
            if self.region and self.region != "us-east-1":
                self.client.create_bucket(
                    Bucket=self.bucket,
                    CreateBucketConfiguration={
                        "LocationConstraint": self.region
                    },
                )
            else:
                # us-east-1 MUST NOT have LocationConstraint
                self.client.create_bucket(Bucket=self.bucket)
        except ClientError as e:
            error = e.response.get("Error", {})
            raise RuntimeError(
                f"Failed to create bucket '{self.bucket}': {error.get('Code')} {error.get('Message')}"
            ) from e

    def head(self, key: str) -> dict | None:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=key)
            return response
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return None
            raise

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def get_streaming_body(self, key: str):
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response['Body']
