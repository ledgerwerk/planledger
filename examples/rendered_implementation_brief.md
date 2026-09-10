---
planledger_schema: planledger.rendered_plan.v2
plan_id: plan-0003
global_ref: pl:plan-0003
title: Dependency upgrade recovery
status: done
version: 2
---

# Dependency upgrade recovery

## Purpose

Recover the repository after a dependency upgrade without broad unrelated cleanup.

## Executive verdict

The primary correction should be implemented before addressing follow-up cleanup.

## Root cause analysis

Observed evidence identifies one integration boundary regression. Proposed changes are limited to that boundary.

## P0 — Resolve the integration regression

**Target files**

- [`src/integration.py`](src/integration.py)

**Acceptance criteria**

- [ ] The upgraded dependency path works.

**Validation**

- `python -m pytest tests/test_integration.py -q`

## P1 — Remove confirmed duplication

**Target files**

- [`src/bootstrap.py`](src/bootstrap.py)

**Acceptance criteria**

- [ ] Initialization has one owner.

**Validation**

- `python -m pytest tests/test_bootstrap.py -q`

## Detailed implementation sequence

1. Fix the P0 integration boundary.
2. Remove only duplication confirmed by call-site inspection.

## Full acceptance checklist

- [ ] The baseline regression is covered.
- [ ] The handoff validation commands are executable.

## Non-goals

- No unrelated refactor or dependency migration is included.

## Final recommendation

Implement the P0 correction, then validate the focused and full suites before the P1 cleanup.
