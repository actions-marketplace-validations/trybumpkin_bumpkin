"""Bumpkin internal package layout.

The legacy flat modules under ``src/`` remain supported for backwards compatibility.
New code should prefer package imports under ``bumpkin.*``.
"""

from . import (
    analysis,
    app,
    contracts,
    eval,
    io,
    licensing,
    orchestrator,
    planner,
    policies,
    providers,
    release_job,
    versioning,
)

__all__ = [
    "analysis",
    "app",
    "contracts",
    "eval",
    "io",
    "licensing",
    "orchestrator",
    "planner",
    "policies",
    "providers",
    "release_job",
    "versioning",
]
