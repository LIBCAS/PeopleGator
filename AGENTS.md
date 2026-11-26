# Agent instructions

Before changing code or documentation, read [README.md](README.md), the applicable guide in `docs/`, the complete GitHub issue, affected callers and existing tests. Base new work on the latest `origin/develop` and open pull requests against protected `develop`.

## Preparing issues

For a new feature, bug or maintenance request, follow [Creating GitHub issues](docs/ISSUE_WORKFLOW.md). Inspect related issues/PRs, documentation, affected source and tests before writing requirements. **Every requirement, scope item and acceptance criterion must come from an explicit requester instruction, a verified applicable project contract or a specific proposal explicitly approved by the requester.** Distinguish verified behavior from proposals and approved requirements; an assistant's recommendation, unreviewed draft or instruction to publish is not approval of an added requirement. Ask about unsettled material decisions rather than guessing. Before creating or updating an issue, audit its requirements against those sources, even when immediate publication is requested. Remove unsupported additions or identify them separately as unapproved proposals; exclude them from implementation scope. If a material decision remains open, use the existing `[Draft]` workflow for explicitly requested publication; otherwise resolve it first. Reuse an existing relevant issue where possible, and publish a ready issue after approval or when explicitly instructed.

## Isolated implementation workspace (Codex CLI)

For **`Implement LIBCAS/PeopleGator issue #N`**, automatically follow the [agent-owned temporary-clone workflow](docs/AGENT_TEMP_CLONES.md); the requester does not need to provide workspace instructions. The same policy applies to PR revisions, not read-only reviews or issue preparation.

**Never modify the original checkout or another agent's workspace.** Verify the official remote, create a unique temporary clone of it, and use the latest `origin/develop` for new implementation or the existing remote PR branch for revisions. Perform all edits, installs, tests and Git operations inside that clone; do not use worktrees or fall back to the original checkout on permission failure. After pushing and handing off a PR against `develop`, remove **only** the agent-owned clone, and only after confirming clean, pushed state and a safe path. Otherwise preserve it and report the blocker. The linked guide contains the detailed portable setup, checks and cleanup gates.


- [Architecture](docs/ARCHITECTURE.md): module ownership and end-to-end job flow.
- [Processing](docs/PROCESSING.md): input, engine order and person-occurrence lifecycle.
- [Output formats](docs/OUTPUT_FORMATS.md): ALTO/PAGE structures, app persistence and re-export goals.
- [Testing](docs/TESTING.md): regression matrix, fixtures and validation plans.
- [Creating GitHub issues](docs/ISSUE_WORKFLOW.md): requirements and issue readiness.

## Before implementation

1. Read the **entire issue, comments, linked issues/PRs and dependencies**. An issue without a `[Draft]` prefix is not proof that every decision was made. If a material requirement is unclear or lacks an approved origin, or a decision about behavior, scope, defaults, validation/error handling, compatibility, persisted data or a public/API contract is unresolved, **stop the affected work, ask the requester, and update the issue and plan with the decision before implementing it**. Do not invent a plausible requirement. Do not ask about details already settled by the issue, existing code, documentation or conventions.
2. Inspect affected code, existing model methods and utilities, callers, configuration, output formats and available tests. Distinguish current behavior from planned functionality. Follow established interfaces, especially ALTO/PAGE XML and PeopleGatorApp identity contracts.
3. Make a short implementation plan mapping **each acceptance criterion** to the smallest necessary change and a way to verify it. Keep implementation inside the approved scope and raise newly discovered requirements separately. Distinguish a defect that prevents the approved outcome from an optional improvement: explain necessary in-scope corrections in the PR; report prerequisite defects requiring material scope expansion and obtain approval before expanding the issue. Leave optional adjacent improvements out unless explicitly approved.
4. Check which development dependencies and tests can actually run. The repository is establishing packaging and a test suite; record any environment blockers rather than assuming checks are available.

## Implementation style and scope

- Prefer the **simplest direct implementation that humans can readily understand**. Implement the approved requirements, not a more sophisticated system that might be needed later; do not optimize for line count.
- Follow **separation of concerns and single responsibility**: before adding or substantially modifying a function, method or class, identify the established responsibilities of its containing component and place the functionality in the appropriate existing architectural layer. See [component boundaries](docs/ARCHITECTURE.md#repository-responsibilities). Communication, serialization and persistence infrastructure must not own caller-specific workflows or processing/domain decisions; common endpoint payload/response handling and transport authentication remain infrastructure responsibilities. If ownership is materially unclear or a departure from established responsibilities is necessary, stop the affected work, consult the requester and document the approved decision before implementing it, following the existing scope and requirement-approval rules.
- Follow [processing responsibilities](docs/ARCHITECTURE.md#processing-implementation-principles): the parser orchestrates engines; each engine owns its algorithm, decisions and engine-specific LLM input/output preparation in its own module. Reuse shared LLM infrastructure without depending on another engine's internals.
- Before adding a helper or abstraction, inspect existing callers and semantics. Use existing models for operations on their own data, lookup and common serialization; share genuinely identical logic through existing model, text or utility modules. Retain meaningful helpers, response schemas and distinct algorithmic policies. Do not duplicate or bypass suitable existing model methods, utilities or processing algorithms. Do not relocate functionality merely to shorten a caller or introduce services, context objects, intermediate representations, superclasses or layers when an existing component already owns the functionality.
- Prefer original object references and ordinary local variables/collections. Compute invariant information outside loops and avoid redundant traversal, resolution, serialization and intermediate data only as behavior-preserving implementation choices within approved scope. Generic simplicity, reuse or efficiency guidance never authorizes new requirements. Do not introduce unrequested optimizations, caching/memoization (including operation-local state to suppress external requests), deduplication, batching, or changes to request frequency, validation, restrictions, defaults, fallback/recovery, persistence or other behavior unless explicitly requested, required by a verified applicable contract or explicitly approved as a proposal. Preserve ordering, mutation boundaries and failure semantics. Choosing a data structure for an approved operation is routine; deciding to suppress repeated calls is not (see the [#76 / PR #77 example](docs/ISSUE_WORKFLOW.md#when-to-ask-rather-than-assume)).
- Follow established PeopleGator conventions and, where relevant, AnnoPage and pero-ocr. Initialize inherited engine infrastructure with `super().__init__()` before specialized members unless a concrete technical dependency requires another order; explain any exception. Use inherited attributes, native typed ConfigParser getters and existing list/path helpers instead of custom wrappers.
- **Do not use `getattr()` in PeopleGator implementation code.** Access model and object attributes directly. Handle optional values through explicit `None` checks and heterogeneous object types through appropriate type checks. Do not introduce reflection-based attribute access, fallback initialization or compatibility shims to conceal missing attributes. Any departure from this rule requires explicit requester approval.
- Implement only established or approved validation, integrity, compatibility, error and recovery policies. Do not invent extra checks, restrictions or failure conditions; retain necessary domain/interface validation and ask before adding or removing a material requirement. Prefer standard library and existing infrastructure to custom machinery; avoid unnecessary context managers and temporary state.
- Make focused edits: no unrelated refactoring, formatting churn, new configuration/dependencies, speculative edge cases or contract changes without approval. Record adjacent findings separately rather than expanding the issue.
- Remove superseded implementations, redundant checks, tests and fixtures while retaining meaningful regression coverage. Follow [behavior-oriented testing guidance](docs/TESTING.md#how-to-write-new-tests); keep tests and documentation proportional to the approved change.
- Review the final diff against approved requirements and their origins, not merely the written issue: disclose any additional changes (including necessary in-scope corrections) and unresolved decisions in the PR. Do not treat an agent-authored acceptance criterion as evidence of approval. Justify any nontrivial new abstraction or layer; explain what behavior and contracts are preserved and what was actually verified.

## Architectural review

For the implementing agent's final diff self-review and every independent PR review (including read-only reviews and reviews of revised PRs), assess architecture separately from functional correctness, acceptance-criteria coverage and test results. For each new or substantially modified function, method or class, check:

- Whether its functionality belongs to the containing class/module and architectural layer, and preserves the component's established responsibilities and boundaries.
- Whether suitable existing functionality is duplicated or bypassed.
- Whether new state, dependencies, helpers and abstraction layers are necessary and appropriately owned.
- Whether any departure from established responsibilities has explicit requester approval and is documented.

Report actionable architectural findings even when behavior is correct and tests pass. Assess their severity and consequences and account for them in the merge recommendation. An author's checked checklist, fulfilled acceptance criteria or passing tests are not substitutes for this independent assessment.

## GitHub development workflow

All implementation work follows: **ready issue → branch → implementation and tests → verification → PR → review**.

1. **In the agent-owned temporary remote clone** described above, fetch `origin/develop` and create an issue-specific branch **from its latest commit** (unless the issue names another base), using `issue/<number>-short-description`. For an existing issue PR, fetch and check out its remote branch instead. Do not change the branch or files in the original checkout. Do not implement directly on `develop` or `main`.
2. Implement the agreed behavior in focused units and commit coherent, reviewable changes. Add or update regression tests for new functionality and bug fixes as you work.
3. Run the relevant tests and inspect produced data where applicable. Follow [Testing](docs/TESTING.md); report the exact checks, results and blocked checks. A syntax check alone does not verify expected behavior.
4. Re-read the issue before finishing: check **every acceptance criterion** against the code and test evidence, including important error/empty cases. Record anything still incomplete; do not silently mark it done.
5. Update relevant active documentation for changed engines, configuration, ALTO/PAGE XML, identity mapping or other public behavior. Review the final diff for unrelated changes and perform the [architectural self-review](#architectural-review).
6. Incorporate recent `origin/develop` changes when needed and resolve conflicts without overwriting others' work. Re-run affected checks after resolving conflicts.
7. Push the branch and open a PR **targeting `develop`**, using [the PR template](.github/pull_request_template.md). Link the issue (`Closes #N` only when complete; otherwise `Refs #N`), summarize behavior and acceptance-criteria evidence, list tests and limitations, and request human review. Use a **draft PR** while essential work or verification remains incomplete. Merge only with explicit authorization.
8. After confirming the pushed branch, PR, and clean state of the **temporary clone**, perform the safe cleanup described in [the temporary-clone guide](docs/AGENT_TEMP_CLONES.md). On failure, retain the clone and report its exact path; never remove the original checkout.

## Handoff

Provide the issue and PR links, branch/target, changed behavior/files, **acceptance criteria completed or outstanding**, tests actually run and their results, checks not run (with reasons), documentation changes, justification for any new abstraction, temporary-clone cleanup status (or preserved recovery path) and remaining risks/decisions. Link newly discovered work to a separate GitHub issue. Opening a PR requests review; it does not authorize merging.
