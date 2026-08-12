"""Google Flow adapter boundary; browser details never enter core planning."""

from .service import FlowError, FlowExecutor, execute_generation
from .session import FlowCapabilities, FlowRuntime, preflight

__all__ = ["FlowCapabilities", "FlowError", "FlowExecutor", "FlowRuntime", "execute_generation", "preflight"]
