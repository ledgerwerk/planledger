from __future__ import annotations

from pathlib import Path
from typing import Any

from planledger.baseline import apply_baseline, review_baseline
from planledger.bundle import apply_bundle, load_bundle
from planledger.errors import PlanledgerError
from planledger.models import Workspace


def backfill_apply(
    workspace: Workspace,
    bundle_path: Path,
    *,
    provenance: str = "inferred",
    evidence: list[dict[str, str]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    bundle = load_bundle(bundle_path)
    if bundle.get("schema") == "planledger.baseline.v1":
        return apply_baseline(workspace, bundle_path, dry_run=dry_run)

    if provenance == "inferred" and not evidence:
        raise PlanledgerError(
            "missing_evidence",
            "Inferred backfill requires evidence entries.",
            remediation=[
                "Provide --evidence entries like:",
                '  --evidence path:README.md reason:"Existing goal inferred"',
            ],
        )

    result = apply_bundle(
        workspace,
        bundle,
        dry_run=dry_run,
        provenance=provenance,
        evidence=evidence,
    )

    return {
        "kind": "planledger_backfill_apply",
        "provenance": provenance,
        "dry_run": dry_run,
        "created": result.created,
        "reused": result.reused,
        "plan_id": result.plan_id,
        "events": result.events,
    }


def backfill_review(workspace: Workspace) -> dict[str, Any]:
    result = review_baseline(workspace)
    result["kind"] = "planledger_backfill_review"
    return result
