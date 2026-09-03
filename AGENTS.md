# Drug Discovery Agent

Read these documents before modifying code:

1. docs/PIPELINE_SPEC.md
2. docs/SCIENTIFIC_INVARIANTS.md
3. docs/ARCHITECTURE.md

The files under legacy/ contain the researcher's original working
implementations and are the behavioral source of truth.

Do not modify files under legacy/.

New production code belongs under:
src/drug_discovery_agent/

When refactoring legacy behavior:
- preserve outputs unless a documented bug is being fixed;
- add regression tests before replacing functionality;
- keep target-specific scientific parameters in configuration;
- never hardcode NS1-specific coordinates or residue numbers into
  generic modules;
- record all transformations and external command invocations;
- failures must be explicit and resumable.

Do not invent scientific assumptions when the legacy code or project
documentation does not define them. Surface them as required project
inputs/checkpoints instead.