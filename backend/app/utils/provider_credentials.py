"""User credentials must have explicit provenance; legacy rows are ambiguous."""
from app.utils.secret_crypto import decrypt_secret


def user_provider_key(row) -> str:
    # Old releases copied server keys to every registered account. Neither the
    # current environment nor the saved URL can prove ownership of those keys.
    if getattr(row, "credential_source", None) != "user":
        return ""
    return decrypt_secret(row.api_key)
