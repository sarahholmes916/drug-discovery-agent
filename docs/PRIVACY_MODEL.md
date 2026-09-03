# Privacy and localhost threat model

## Data classification

Scientific inputs, identities, structures, sequences, SMILES, prepared and
predicted artifacts, MSAs/arrays, interactions, reports, detailed results, raw
logs, commands containing paths, and filesystem paths are **local data**. They
remain on the runner by default. Account IDs, opaque project/machine/run/job
IDs, connectivity, non-sensitive boolean/version capabilities, stage status,
aggregate counts, and timestamps are **control-plane metadata**.

There is no automatic scientific-data upload path. Cloud serialization uses
allowlisted DTO constructors rather than recursively filtering local objects.
Tests scan serialized payloads for forbidden content and absolute paths. Future
synchronization must be a separately authenticated, explicit opt-in feature
with a visible artifact allowlist; it is out of scope for the default design.

## Hosted-service behavior

In the default companion deployment, the hosted service is static and receives
neither scientific data nor control-plane metadata. The browser talks directly
to the loopback companion, which stores orchestration state in local SQLite and
executes jobs locally.

Browser file inputs for new projects are posted directly to the paired loopback
origin. The companion accepts only fixed receptor/PDBQT/ligand fields, validates
extensions and size limits, assigns its own destination filenames, stages the
files beneath the local projects root, and atomically registers the project.
The hosted origin never receives the file request or its contents.

The chat model is downloaded from public WebLLM/model artifact hosts and runs
inside a browser worker. Inference requests are not sent to those hosts: the
model sees only text the user types into chat plus an allowlisted summary of
visible workflow settings. Molecular file contents, protein sequences, local
paths, results, companion credentials, and pairing state are not included in
the model prompt. The artifact hosts still receive ordinary model-download
request metadata such as the user's IP address and browser headers.

After pairing, the browser may request a list of registered local projects.
That response contains display metadata, workflow flags, run status, timestamps,
and result counts only; it omits local paths, sequences, receptor/ligand data,
and result contents. A result ZIP is created only after an explicit download
action and contains registered artifacts plus local provenance metadata, never
the original receptor or ligand uploads.

The optional remote-control deployment can schedule a cloud-neutral workflow
and observe progress. The runner resolves an opaque local project reference,
executes locally, and sends only payloads such as:

```json
{"run_id":"run_123","stage":"RUN_VINA","status":"RUNNING","completed":843,"total":1200,"failed":7}
```

Messages are deliberately generic. Exception strings, ligand labels, command
lines, and local paths stay in local runtime/provenance logs.

While the PocketMiner gate is paused, the only additional cloud metadata is:

```json
{"run_id":"run_123","stage":"pocket_selection","status":"awaiting_user_selection","completed":0,"total":3,"failed":0,"candidate_count":3}
```

Residue identities, scores, pocket metrics, centers, box dimensions, receptor
visualization, and the selected pocket remain on the local bridge.

## Outbound runner channel

The runner initiates HTTPS polling (or a future authenticated secure WebSocket),
so no inbound internet port is needed. Machine credentials are scoped to one
account/machine, stored locally with restrictive permissions where the platform
supports it, rotated, and sent only over TLS. Job claims are idempotent and
bound to the authenticated machine.

## Localhost bridge threats and controls

Threats include a malicious website probing localhost, CSRF, stolen bearer
tokens, path traversal, symlink escape, arbitrary file reads, command injection,
and another local process impersonating the UI.

Controls:

- bind to loopback only;
- create high-entropy pairing and session credentials internally, compare their
  digests in constant time, and never require the user to copy or type them;
- display the exact requesting origin on a local approval page and scope every
  approved session to that origin;
- optionally lock release builds to an exact origin allowlist and always deny
  absent or malformed browser origins;
- allow only `GET`/`POST` endpoints with JSON and reject form-simple requests;
- expose fixed operations, never arbitrary commands;
- limit PocketMiner routes to normalized scores, ranked candidates, the fixed
  visualization receptor, canonical selection, and run resume;
- expose registered project/artifact IDs, never arbitrary filesystem paths;
- list only sanitized project summaries and build downloads from registered
  manifest artifacts rather than caller-supplied paths;
- resolve and verify paths remain inside the registered project root, including
  after symlink resolution;
- use explicit OS file-picker flows outside the HTTP API for new source files;
- return artifact bytes with safe content types and no path metadata;
- require per-request project authorization and make cancellation idempotent;
- avoid reflecting secrets or scientific data in logs and errors;
- keep browser-facing capabilities and progress sanitized.

Opening an output directory is a local runner action against a registered
project, not a caller-supplied path. TLS on loopback may be added, but local
approval, origin scoping, and session authentication remain necessary.

## Privacy failure behavior

A cloud payload that fails the allowlist/forbidden-content validator is rejected
locally and recorded as a local communication error. Scientific computation can
continue offline; privacy validation is never bypassed to restore telemetry.
