from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext

MAX_DIGITS = 38


def canonical_decimal(value: str) -> str:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal: {value!r}") from exc
    if not number.is_finite():
        raise ValueError("non-finite decimals are not accepted")
    if len(number.as_tuple().digits) > MAX_DIGITS:
        raise ValueError(f"decimal exceeds {MAX_DIGITS}-digit policy")
    result = format(number, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    return "0" if result in {"-0", ""} else result


def parse_localized_decimal(raw: str, convention: str) -> str:
    value = raw.strip().replace("\u00a0", " ").replace("'", "").replace(" ", "")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1]
    value = re.sub(r"[^0-9,\.\-+]", "", value)
    if convention == "decimal_comma":
        value = value.replace(".", "").replace(",", ".")
    elif convention == "decimal_point":
        value = value.replace(",", "")
    else:
        raise ValueError(f"unknown numeric convention: {convention}")
    if negative:
        value = "-" + value
    return canonical_decimal(value)


def multiply(*values: str) -> str:
    with localcontext() as context:
        context.prec = MAX_DIGITS
        result = Decimal("1")
        for value in values:
            result *= Decimal(value)
    return canonical_decimal(str(result))


def numeric_sort(values: list[str]) -> list[str]:
    return sorted(values, key=Decimal)
