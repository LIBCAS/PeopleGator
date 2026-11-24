# Agent instructions

Before changing code or documentation, read [README.md](README.md), the applicable guide in `docs/`, the complete GitHub issue, affected callers and existing tests. Base new work on the latest `origin/develop` and open pull requests against protected `develop`.

## Preparing issues

For a new feature, bug or maintenance request, follow [Creating GitHub issues](docs/ISSUE_WORKFLOW.md). Inspect related issues/PRs, documentation, affected source and tests before writing requirements. Ask the requester about material decisions that are not established; **do not guess behavior, defaults or contracts**. If explicitly asked to publish an issue with unresolved material decisions, use a `[Draft]` title and list the open questions rather than presenting it as implementation-ready. Otherwise resolve those decisions first. Reuse an existing relevant issue where possible, and publish a ready issue after approval or when explicitly instructed.

## Isolated implementation workspace (Codex CLI)

For **`Implement LIBCAS/PeopleGator issue #N`**, automatically follow the [agent-owned temporary-clone workflow](docs/AGENT_TEMP_CLONES.md); the requester does not need to provide workspace instructions. The same policy applies to PR revisions, not read-only reviews or issue preparation.

**Never modify the original checkout or another agent's workspace.** Verify the official remote, create a unique temporary clone of it, and use the latest `origin/develop` for new implementation or the existing remote PR branch for revisions. Perform all edits, installs, tests and Git operations inside that clone; do not use worktrees or fall back to the original checkout on permission failure. After pushing and handing off a PR against `develop`, remove **only** the agent-owned clone, and only after confirming clean, pushed state and a safe path. Otherwise preserve it and report the blocker. The linked guide contains the detailed portable setup, checks and cleanup gates.


- [Architecture](docs/ARCHITECTURE.md): module ownership and end-to-end job flow.
- [Processing](docs/PROCESSING.md): input, engine order and person-occurrence lifecycle.
- [Output formats](docs/OUTPUT_FORMATS.md): ALTO/PAGE structures, app persistence and re-export goals.
- [Testing](docs/TESTING.md): regression matrix, fixtures and validation plans.
- [Creating GitHub issues](docs/ISSUE_WORKFLOW.md): requirements and issue readiness.

## Before implementation

1. Read the **entire issue, comments, linked issues/PRs and dependencies**. An issue without a `[Draft]` prefix is not proof that every decision was made. If behavior, scope, defaults, validation/error handling, compatibility, persisted data or a public/API contract is materially unclear, **stop the affected work, ask the requester, and update the issue and plan with the decision before implementing it**. Do not invent a plausible requirement. Do not ask about details already settled by the issue, existing code, documentation or conventions.
2. Inspect affected code, existing model methods and utilities, callers, configuration, output formats and available tests. Distinguish current behavior from planned functionality. Follow established interfaces, especially ALTO/PAGE XML and PeopleGatorApp identity contracts.
3. Make a short implementation plan mapping **each acceptance criterion** to the smallest necessary change and a way to verify it. Keep implementation inside the approved scope and raise newly discovered requirements separately.
4. Check which development dependencies and tests can actually run. The repository is establishing packaging and a test suite; record any environment blockers rather than assuming checks are available.

## Implementation style and scope

- Prefer the **simplest direct implementation that humans can readily understand**; do not optimize for line count or add abstractions for hypothetical future needs.
- Before adding a helper, wrapper, model or module, check whether an existing model method, utility or engine already owns the responsibility. Share logic only when its semantics truly agree; keep engine-specific decisions in their engines.
- Initialize inherited engine infrastructure with `super().__init__()` before specialized members unless a concrete technical dependency requires another order; explain any exception.
- Use native typed ConfigParser getters and existing list/path helpers for engine configuration, retaining only necessary domain-specific validation.
- Prefer explicit data flow and initialized object invariants. Avoid repeated fallback checks, temporary state, extra context managers, redundant validation and compatibility shims **unless a concrete supported scenario requires them**. Necessary defensive handling and compatibility guarantees must be retained.
- Make focused edits: no unrelated refactoring, formatting churn, new configuration/dependencies, speculative edge cases or contract changes without approval. Record adjacent findings separately rather than expanding the issue.
- Remove superseded code, helpers and redundant tests/fixtures when replacing an implementation, while retaining meaningful regression coverage. Keep new tests and documentation proportional to the approved change.
- Review the final diff and justify any nontrivial new abstraction or layer; explain what behavior and contracts are preserved and what was actually verified.

## GitHub development workflow

All implementation work follows: **ready issue → branch → implementation and tests → verification → PR → review**.

1. **In the agent-owned temporary remote clone** described above, fetch `origin/develop` and create an issue-specific branch **from its latest commit** (unless the issue names another base), using `issue/<number>-short-description`. For an existing issue PR, fetch and check out its remote branch instead. Do not change the branch or files in the original checkout. Do not implement directly on `develop` or `main`.
2. Implement the agreed behavior in focused units and commit coherent, reviewable changes. Add or update regression tests for new functionality and bug fixes as you work.
3. Run the relevant tests and inspect produced data where applicable. Follow [Testing](docs/TESTING.md); report the exact checks, results and blocked checks. A syntax check alone does not verify expected behavior.
4. Re-read the issue before finishing: check **every acceptance criterion** against the code and test evidence, including important error/empty cases. Record anything still incomplete; do not silently mark it done.
5. Update relevant active documentation for changed engines, configuration, ALTO/PAGE XML, identity mapping or other public behavior. Review the final diff for unrelated changes.
6. Incorporate recent `origin/develop` changes when needed and resolve conflicts without overwriting others' work. Re-run affected checks after resolving conflicts.
7. Push the branch and open a PR **targeting `develop`**, using [the PR template](.github/pull_request_template.md). Link the issue (`Closes #N` only when complete; otherwise `Refs #N`), summarize behavior and acceptance-criteria evidence, list tests and limitations, and request human review. Use a **draft PR** while essential work or verification remains incomplete. Merge only with explicit authorization.
8. After confirming the pushed branch, PR, and clean state of the **temporary clone**, perform the safe cleanup described in [the temporary-clone guide](docs/AGENT_TEMP_CLONES.md). On failure, retain the clone and report its exact path; never remove the original checkout.

## Handoff

Provide the issue and PR links, branch/target, changed behavior/files, **acceptance criteria completed or outstanding**, tests actually run and their results, checks not run (with reasons), documentation changes, justification for any new abstraction, temporary-clone cleanup status (or preserved recovery path) and remaining risks/decisions. Link newly discovered work to a separate GitHub issue. Opening a PR requests review; it does not authorize merging.
