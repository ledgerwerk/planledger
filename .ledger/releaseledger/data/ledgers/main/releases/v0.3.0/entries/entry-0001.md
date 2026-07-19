---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0001
release_version: v0.3.0
kind: changed
summary:
  Changed storage backend to Ledgercore 0.5.0 with schema-3 manifest and sibling-ledger
  provider
status: accepted
audience: null
scopes: []
source_refs:
  - git:d3485c1fed8f96f26061820a3bbab91a1412714c
  - git:64f208f4ee102b3b6583487399bd5f4b3372fd70
  - git:0f36a5d7aca404cb8ebc730a1c720459cb930398
paths:
  - planledger/ledgercore_backend.py
  - planledger/project_context.py
  - planledger/project_binding.py
  - planledger/initialization.py
  - planledger/storage.py
  - planledger/migration.py
  - planledger/domain_migration.py
  - planledger/legacy_layout.py
  - planledger/write_lock.py
  - planledger/cli.py
  - planledger/cli_writes.py
  - planledger/id_inventory.py
  - planledger/models.py
  - planledger/errors.py
  - docs/storage.rst
  - docs/architecture.rst
  - docs/cli.rst
  - pyproject.toml
issues: []
prs: []
sources:
  - git:d3485c1fed8f96f26061820a3bbab91a1412714c
  - git:64f208f4ee102b3b6583487399bd5f4b3372fd70
  - git:0f36a5d7aca404cb8ebc730a1c720459cb930398
breaking: false
internal: false
order: 1
---
