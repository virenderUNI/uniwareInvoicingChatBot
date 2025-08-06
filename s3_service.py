import boto3
import logging
from botocore.exceptions import ClientError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class S3Service:
    def __init__(self):
        # Initialize S3 client
        self.s3_client = boto3.client('s3')

    def upload_file(self, file_path, bucket_name, key=None):
        """
        Upload a file to S3 bucket
        :param file_path: Path to the file to upload
        :param bucket_name: Name of the S3 bucket
        :param key: S3 key for the file (optional, defaults to file name)
        :return: URL of the uploaded file
        """
        try:
            # If key is not provided, use the file name
            if key is None:
                key = file_path.split('/')[-1]

            logger.info(f"Uploading file to S3 filename:{file_path}, bucketName:{bucket_name}")

            # Upload file with public-read ACL
            self.s3_client.upload_file(
                file_path,
                bucket_name,
                key,
                ExtraArgs={'ACL': 'public-read'}
            )

            # Generate the resource URL
            resource_url = f"https://{bucket_name}.s3.amazonaws.com/{key}"
            logger.info(f"Uploaded file to S3 filename:{file_path}, resourceUrl:{resource_url}")

            return resource_url

        except ClientError as e:
            logger.error(f"Error while uploading file to S3: {str(e)}")
            raise RuntimeError(str(e))
        except Exception as e:
            logger.error(f"Error while uploading file to S3: {str(e)}")
            raise RuntimeError(str(e))