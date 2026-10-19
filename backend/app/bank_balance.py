from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


class BankBalanceSourceUnavailable(Exception):
    pass


@dataclass(frozen=True)
class VerifiedBankBalance:
    balance: Decimal
    recorded_at: datetime
    source: str
    source_reference: str


def fetch_verified_member_balance(member_id: int) -> VerifiedBankBalance:
    """Fetch a fresh balance from a trusted provider with a stable check reference."""
    raise BankBalanceSourceUnavailable(
        "No authorized bank-balance provider is configured. "
        "Member profile banking details cannot be used to verify a balance."
    )
