import os


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing app setting: {name}")
    return value


def subscription_id() -> str:
    return require("AZURE_SUBSCRIPTION_ID")


def cosmos_endpoint() -> str:
    return require("COSMOS_ENDPOINT")


def cosmos_database() -> str:
    return require("COSMOS_DATABASE")


def storage_account_name() -> str:
    return require("STORAGE_ACCOUNT_NAME")


def log_analytics_workspace_id() -> str:
    return require("LOG_ANALYTICS_WORKSPACE_ID")


def openai_endpoint() -> str:
    return require("OPENAI_ENDPOINT")


def openai_deployment() -> str:
    return require("OPENAI_DEPLOYMENT")