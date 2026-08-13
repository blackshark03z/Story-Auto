"""Google Flow adapter boundary; browser details never enter core planning."""

from .service import (FlowError, FlowExecutor, adopt_manual_recovery, execute_generation,
                      reconcile_local_assets, reject_selected_asset, reopen_verified_pre_dispatch_failure)
from .session import FlowCapabilities, FlowRuntime, launch_dedicated_session, preflight

__all__ = ["FlowCapabilities", "FlowError", "FlowExecutor", "FlowRuntime", "adopt_manual_recovery",
           "execute_generation", "launch_dedicated_session", "preflight", "reconcile_local_assets",
           "reject_selected_asset", "reopen_verified_pre_dispatch_failure"]
