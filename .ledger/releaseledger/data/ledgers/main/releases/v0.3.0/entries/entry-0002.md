---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0002
release_version: v0.3.0
kind: changed
summary: Changed persistence layer with dedicated record, plan, and workshop stores
status: accepted
audience: null
scopes: []
source_refs:
  - git:f809a38655b8ed1ae295e521db7e5345315f85d3
paths:
  - planledger/persistence.py
  - planledger/record_store.py
  - planledger/plan_store.py
  - planledger/workshop_store.py
  - planledger/storage.py
  - planledger/ledgercore_backend.py
  - planledger/project_context.py
  - planledger/cli.py
issues: []
prs: []
sources:
  - git:f809a38655b8ed1ae295e521db7e5345315f85d3
breaking: false
internal: false
order: 2
---
