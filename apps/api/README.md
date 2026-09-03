# Hosted control-plane API

This minimal FastAPI/SQLite service stores only identities, sanitized workflow
configuration, connectivity, jobs, aggregate progress, and timestamps. It has
no scientific file upload or processing endpoint. Set `DRUG_AGENT_API_DB` and a
strong `DRUG_AGENT_API_TOKEN` before deployment; the module-level defaults are
development-only. Replace the token map and SQLite adapter for a real identity
provider/database without changing runner or scientific interfaces.

Pocket selection adds only the generic `pocket_selection`/
`awaiting_user_selection` event and `candidate_count`. After local confirmation,
the browser requeues the same job through a metadata-only resume endpoint so
the outbound runner—not the hosted API—continues scientific execution.
