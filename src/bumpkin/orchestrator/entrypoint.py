from __future__ import annotations


def run() -> int:
    # Compatibility bridge: keep action entrypoint stable while internal modules evolve.
    from main import main as legacy_main

    return legacy_main()
