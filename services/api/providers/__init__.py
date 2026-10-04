"""Optional staging provider adapters.

Adapters are dependency-injected and do not import cloud SDKs, credentials, or
application UI code. Local tests use the fake client/queue implementations.
"""

from .processing_queue import (
    InMemoryProcessingQueue,
    ProcessingJob,
    ProcessingJobStatus,
    ProcessingQueue,
)
from .s3 import S3ObjectStore, S3ObjectStoreConfig

__all__ = [
    "InMemoryProcessingQueue",
    "ProcessingJob",
    "ProcessingJobStatus",
    "ProcessingQueue",
    "S3ObjectStore",
    "S3ObjectStoreConfig",
]
