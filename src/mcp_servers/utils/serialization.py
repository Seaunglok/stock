"""
Serialization helpers for consistent JSON-safe outputs.

- Convert Decimal → float
- Convert UUID → str
- Convert datetime/date → ISO string

Beginner notes:
    - The conversion is recursive and safe for nested dict/list/tuple/set.
    - Use this before returning arbitrary data in MCP responses to avoid
      non-serializable types leaking to clients.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID


def to_serializable(obj: Any) -> Any:
    """
    Recursively convert common non-JSON types to JSON-safe values.

    - Decimal → float
    - UUID → str
    - datetime/date → ISO string
    - dict/list/tuple/set → recurse
    """
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [to_serializable(v) for v in obj]
    return obj
