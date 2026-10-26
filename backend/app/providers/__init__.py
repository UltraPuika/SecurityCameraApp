"""Provider registry. Adding a brand = one module here plus a register() call."""

from app.providers.base import AccountProvider, Provider
from app.providers.generic import BitVisionProvider, GenericRtspProvider
from app.providers.imou import ImouAccountProvider, ImouProvider

PROVIDERS: dict[str, Provider] = {}
ACCOUNT_PROVIDERS: dict[str, AccountProvider] = {}


def register(provider: Provider) -> None:
    PROVIDERS[provider.id] = provider


def register_account(provider: AccountProvider) -> None:
    ACCOUNT_PROVIDERS[provider.id] = provider


register(GenericRtspProvider())
register(BitVisionProvider())
register(ImouProvider())
register_account(ImouAccountProvider())
