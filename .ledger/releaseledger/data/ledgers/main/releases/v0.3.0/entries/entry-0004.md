---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0004
release_version: v0.3.0
kind: fixed
summary:
  Fixed write lock PID liveness check on Windows to avoid TerminateProcess
  side-effect
status: accepted
audience: null
scopes: []
source_refs:
  - git:5339b168cf559ae1b41df8435c0a99bc1d026f17
paths:
  - planledger/write_lock.py
issues: []
prs: []
sources:
  - git:5339b168cf559ae1b41df8435c0a99bc1d026f17
breaking: false
internal: false
order: 4
---
