from typing import Any


def validate_cancel_order(arguments: dict[str, Any]) -> dict[str, Any]:
    """Exact business payload binding. Never normalize two distinct order identifiers."""
    if set(arguments) != {"orderId"}:
        raise ValueError("INVALID_OPERATION_ARGUMENTS")
    value = arguments["orderId"]
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or value != value.strip()
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError("INVALID_ORDER_ID")
    return {"orderId": value}
