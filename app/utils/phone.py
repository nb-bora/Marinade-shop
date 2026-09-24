import re
from dataclasses import dataclass


CAMEROON_COUNTRY_CODE = "+237"


@dataclass(frozen=True)
class MobileOperator:
    code: str
    name: str
    prefixes: tuple[str, ...]


# Cameroon Mobile Money defaults from the ART numbering plan. Production
# deployments should load additional prefixes from MobileOperatorPrefix.
MOBILE_OPERATORS: tuple[MobileOperator, ...] = (
    MobileOperator("MTN_CM", "MTN Cameroun", ("650", "651", "652", "653", "654", "67")),
    MobileOperator("ORANGE_CM", "Orange Cameroun", ("655", "656", "657", "658", "659", "69")),
)


def normalize_cameroon_mobile(raw: str, operators: tuple[MobileOperator, ...] = MOBILE_OPERATORS) -> tuple[str, MobileOperator]:
    """Normalize a Cameroon mobile number and identify its longest matching prefix."""
    if not isinstance(raw, str):
        raise ValueError("Phone number must be a string")
    value = re.sub(r"[\s().-]", "", raw)
    if value.startswith("00"):
        value = "+" + value[2:]
    elif value.startswith("237"):
        value = "+" + value
    if not value.startswith(CAMEROON_COUNTRY_CODE):
        raise ValueError("Only Cameroon Mobile Money numbers are supported")
    national = value[len(CAMEROON_COUNTRY_CODE):]
    if not re.fullmatch(r"[1-9]\d{8}", national):
        raise ValueError("Cameroon mobile numbers must contain 9 national digits")
    if not national.startswith("6"):
        raise ValueError("Only mobile numbers are supported")
    matches = [operator for operator in operators if any(national.startswith(prefix) for prefix in operator.prefixes)]
    if not matches:
        raise ValueError("Mobile operator is not supported for Mobile Money")
    return value, max(matches, key=lambda operator: max(len(prefix) for prefix in operator.prefixes))


def normalize_cameroon_phone(raw: str) -> str:
    return normalize_cameroon_mobile(raw)[0]
