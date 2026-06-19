{
  "schema": "planledger.structured_workshop.v1",
  "operation": "update",
  "workshop_id": "workshop-0001",
  "reason": "Record accepted scenarios.",
  "components": {
    "acceptance_scenarios": "### SCENARIO-001: Successful login\n\nGiven a registered user exists\nWhen valid credentials are submitted\nThen the user reaches the dashboard.",
    "decisions": "- [x] Use a generic invalid-credentials error.",
    "scope": "### In scope\n\n- Email/password login.\n\n### Out of scope\n\n- Social login."
  }
}
