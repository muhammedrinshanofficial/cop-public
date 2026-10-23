import json

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from . import config

_credential = None
_cosmos_client = None
_blob_client = None


def credential() -> DefaultAzureCredential:
    global _credential
    if _credential is None:
        _credential = DefaultAzureCredential()
    return _credential


def _container(name: str):
    global _cosmos_client
    if _cosmos_client is None:
        _cosmos_client = CosmosClient(config.cosmos_endpoint(), credential=credential())
    database = _cosmos_client.get_database_client(config.cosmos_database())
    return database.get_container_client(name)


def upsert(container_name: str, item: dict) -> None:
    _container(container_name).upsert_item(item)


def read_item(container_name: str, item_id: str, partition_key: str) -> dict | None:
    try:
        return _container(container_name).read_item(item=item_id, partition_key=partition_key)
    except CosmosResourceNotFoundError:
        return None


def archive_json(blob_path: str, payload: dict) -> None:
    """Write a raw copy to the raw-snapshots container (it is deleted after 30 days by the lifecycle rule)."""
    global _blob_client
    if _blob_client is None:
        account_url = f"https://{config.storage_account_name()}.blob.core.windows.net"
        _blob_client = BlobServiceClient(account_url, credential=credential())
    blob = _blob_client.get_blob_client(container="raw-snapshots", blob=blob_path)
    blob.upload_blob(
        json.dumps(payload),
        overwrite=True,
        content_settings=ContentSettings(content_type="application/json"),
    )


def query(container_name: str, query: str, parameters: list | None = None, partition_key: str | None = None) -> list[dict]:
    """Run a SQL query. With a partition key it stays inside one partition (cheap); without one it fans out."""
    options: dict = {"query": query, "parameters": parameters or []}
    if partition_key is None:
        options["enable_cross_partition_query"] = True
    else:
        options["partition_key"] = partition_key
    return list(_container(container_name).query_items(**options))