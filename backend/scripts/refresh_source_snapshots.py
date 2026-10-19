"""Out-of-build refresh of the committed Source_Snapshots (the ONLY live-fetch path).

This script is the single, explicit, out-of-build step where a Source_Connector's
``fetch()`` runs live (R9.4). Every other code path -- build, fit, test,
measurement, the dataset generator, the engine provider -- reads the committed
snapshot bytes by checksum and NEVER fetches. Mirrors the ``sample-imports/
make_*.py`` stdlib + ``--check`` generator pattern.

Guards
------
- It is guarded so it is never triggered by a build/test/import: it does real
  work only under ``if __name__ == "__main__"`` AND only when the explicit
  ``--i-understand-this-fetches-live`` opt-in flag is passed for a live fetch.
  Importing this module runs nothing.
- A live HTTP client is imported INSIDE the fetch path only (never at module
  load), so importing this file pulls in no network dependency. The shipped
  connectors have no live ``fetch()`` wired (they raise), so by default this
  script only re-verifies/pins checksums from existing snapshots.

Usage
-----
    # verify the committed snapshots match their pinned checksums (no write):
    python scripts/refresh_source_snapshots.py --check

    # re-pin checksums from the current snapshot files (local maintenance):
    python scripts/refresh_source_snapshots.py --repin

    # perform a LIVE fetch + rewrite (requires the opt-in flag; only works for
    # connectors that implement a live fetch()):
    python scripts/refresh_source_snapshots.py --i-understand-this-fetches-live

Standard library only at import time.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``app`` importable when run as a plain script from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.data.connectors.base import (  # noqa: E402
    SourceConnectorError,
    canonical_bytes,
    compute_checksum,
    write_snapshot,
)
from app.data.connectors.connector_registry import default_connectors  # noqa: E402


def verify_snapshots() -> int:
    """Verify every connector's committed snapshot against its pinned checksum.

    Returns 0 when all match (idempotent, no-write check), else 1. This is the
    build/CI-safe mode: it only reads bytes, never fetches.
    """
    ok = True
    for conn in default_connectors():
        name = conn.provenance().name
        try:
            conn.read_raw()  # raises on missing file or checksum mismatch.
        except SourceConnectorError as exc:
            print(f"FAIL {name}: {exc}")
            ok = False
            continue
        print(f"ok   {name}: {conn.snapshot_path.name} matches pinned checksum")
    return 0 if ok else 1


def repin_checksums() -> int:
    """Print the canonical-JSON checksum of each current snapshot file.

    A maintenance aid: paste the printed value into the connector's
    ``expected_checksum`` after a legitimate snapshot update. Writes nothing.
    """
    for conn in default_connectors():
        name = conn.provenance().name
        path = conn.snapshot_path
        if not path.exists():
            print(f"MISSING {name}: {path}")
            continue
        import json  # local: stdlib only, kept out of the hot import path

        parsed = json.loads(path.read_bytes().decode("utf-8"))
        checksum = compute_checksum(canonical_bytes(parsed))
        print(f"{name}: {checksum}")
    return 0


def refresh_live() -> int:
    """Perform a LIVE fetch for each connector and rewrite its snapshot.

    This is the only place ``fetch()`` is invoked. Any HTTP client a connector
    needs is imported INSIDE its own ``fetch()`` (never at module load), so this
    script imports no network dependency until a live fetch actually runs. The
    shipped connectors raise from ``fetch()`` (no live source wired), so this
    mode is a no-op for them until a real fetch is implemented.
    """
    rewrote = 0
    for conn in default_connectors():
        name = conn.provenance().name
        try:
            raw = conn.fetch()  # LIVE network call (connector-local HTTP import).
        except SourceConnectorError as exc:
            print(f"skip {name}: {exc}")
            continue
        ref = write_snapshot(conn.snapshot_path, raw)
        print(f"wrote {ref.path.name} ({name}) checksum={ref.checksum}")
        rewrote += 1
    print(f"refreshed {rewrote} snapshot(s); re-pin checksums with --repin")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--check",
        action="store_true",
        help="verify committed snapshots match pinned checksums (no write, CI-safe)",
    )
    group.add_argument(
        "--repin",
        action="store_true",
        help="print current snapshot canonical checksums for re-pinning (no write)",
    )
    group.add_argument(
        "--i-understand-this-fetches-live",
        dest="live",
        action="store_true",
        help="perform a LIVE network fetch and rewrite snapshots (out-of-build only)",
    )
    args = parser.parse_args(argv)

    if args.live:
        return refresh_live()
    if args.repin:
        return repin_checksums()
    # Default and --check are both the safe, no-fetch verification path.
    return verify_snapshots()


if __name__ == "__main__":
    raise SystemExit(main())
