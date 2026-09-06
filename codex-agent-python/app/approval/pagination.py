import base64
import binascii
import json
from datetime import datetime
from uuid import UUID


def encode_cursor(created_at: datetime, approval_id: str) -> str:
    value = json.dumps([created_at.isoformat(), approval_id]).encode()
    return base64.urlsafe_b64encode(value).decode()


def decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        if len(value) > 512:
            raise ValueError("Oversized cursor")
        data = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        if not isinstance(data, list) or len(data) != 2:
            raise ValueError("Invalid cursor shape")
        timestamp, identifier = datetime.fromisoformat(data[0]), str(UUID(data[1]))
        if timestamp.tzinfo is None:
            raise ValueError("Cursor requires a timezone")
        return timestamp, identifier
    except (ValueError, TypeError, binascii.Error, UnicodeError, AttributeError) as exc:
        raise ValueError("INVALID_APPROVAL_CURSOR") from exc
