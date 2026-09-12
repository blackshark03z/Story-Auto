"""Research-only Elyum Seedance provider for Goal 54.

This package is intentionally not wired into production routing. It exists to
qualify Elyum's API-first task/recovery contract before any routing decision.
"""
from .client import (
    DEFAULT_ENDPOINT,
    DEFAULT_FAST_I2V_MODEL,
    DEFAULT_REFERENCE_MODEL,
    ElyumSeedanceClient,
    ElyumSeedanceError,
)
from .research import (
    keep_experiment_preview,
    kill_experiment_preview,
    prepare_reference_upload,
    run_experiment_preview,
)

__all__ = [
    "DEFAULT_ENDPOINT",
    "DEFAULT_FAST_I2V_MODEL",
    "DEFAULT_REFERENCE_MODEL",
    "ElyumSeedanceClient",
    "ElyumSeedanceError",
    "prepare_reference_upload",
    "run_experiment_preview",
    "keep_experiment_preview",
    "kill_experiment_preview",
]
