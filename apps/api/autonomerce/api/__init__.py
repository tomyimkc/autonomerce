"""FastAPI composition surface for Autonomerce.

The API package depends only on the shared contracts at import time.  Optional
Gemini, Circle, and seller-agent implementations are injected through the
small adapter interfaces exported here.
"""

from .adapters import (
    AdapterBundle,
    FulfillmentExecution,
    PaymentExecution,
    load_optional_adapters,
)
from .app import create_app
from .repository import InMemoryRepository

__all__ = [
    "AdapterBundle",
    "FulfillmentExecution",
    "InMemoryRepository",
    "PaymentExecution",
    "create_app",
    "load_optional_adapters",
]
