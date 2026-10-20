# Agent instructions

Before changing code, read [README.md](README.md), the applicable guide in `docs/`, the complete GitHub issue, affected callers and existing tests. Base new work on the latest `origin/develop` and open pull requests against protected `develop`.

## Preparing issues

For a new feature, bug or maintenance request, follow [Creating GitHub issues](docs/ISSUE_WORKFLOW.md). Turn the user's plain-language description into a clear, testable issue by inspecting related issues/PRs, docs and affected source code. Ask focused questions for material missing decisions; otherwise draft the full issue with scope, acceptance criteria and a validation plan. Reuse an existing relevant issue when possible. Publish a new issue after the user approves the draft, or immediately when explicitly instructed to create it.

## Read before editing

- [Architecture](docs/ARCHITECTURE.md): module ownership and end-to-end job flow.
- [Processing](docs/PROCESSING.md): input, engine order and person-occurrence lifecycle.
- [Output formats](docs/OUTPUT_FORMATS.md): ALTO/PAGE structures, app persistence and re-export goals.
- [Testing](docs/TESTING.md): regression matrix, fixtures and validation plans.
- [Creating GitHub issues](docs/ISSUE_WORKFLOW.md): requirements and issue readiness.

## Before implementation

1. Read the **entire issue, comments, linked issues/PRs and dependencies**. Check that the goal, scope and acceptance criteria are clear. Resolve material questions with the requester and update the issue before coding; a `[Draft]` issue with open decisions needs refinement first.
2. Inspect affected code, callers, configuration, output formats and available tests. Distinguish current behavior from planned functionality. Follow established interfaces, especially ALTO/PAGE XML and PeopleGatorApp identity contracts.
3. Make a short implementation plan mapping **each acceptance criterion** to the intended change and a way to verify it. Keep the implementation inside the approved scope and raise newly discovered requirements separately.
4. Check which development dependencies and tests can actually run. The repository is establishing packaging and a test suite; record any environment blockers rather than assuming checks are available.

## GitHub development workflow

All implementation work follows: **ready issue → branch → implementation and tests → verification → PR → review**.

1. Fetch `origin/develop` and create an issue-specific branch **from its latest commit** (unless the issue names another base), using `issue/<number>-short-description`. Preserve unrelated local changes. Do not implement directly on `develop` or `main`.
2. Implement the agreed behavior in focused units and commit coherent, reviewable changes. Add or update regression tests for new functionality and bug fixes as you work.
3. Run the relevant tests and inspect produced data where applicable. Follow [Testing](docs/TESTING.md); report the exact checks, results and blocked checks. A syntax check alone does not verify expected behavior.
4. Re-read the issue before finishing: check **every acceptance criterion** against the code and test evidence, including important error/empty cases. Record anything still incomplete; do not silently mark it done.
5. Update relevant active documentation for changed engines, configuration, ALTO/PAGE XML, identity mapping or other public behavior. Review the final diff for unrelated changes.
6. Incorporate recent `origin/develop` changes when needed and resolve conflicts without overwriting others' work. Re-run affected checks after resolving conflicts.
7. Push the branch and open a PR **targeting `develop`**, using [the PR template](.github/pull_request_template.md). Link the issue (`Closes #N` only when complete; otherwise `Refs #N`), summarize behavior and acceptance-criteria evidence, list tests and limitations, and request human review. Use a **draft PR** while essential work or verification remains incomplete. Merge only with explicit authorization.

## Handoff

Provide the issue and PR links, branch/target, changed behavior/files, **acceptance criteria completed or outstanding**, tests actually run and their results, checks not run (with reasons), documentation changes and remaining risks/decisions. Link newly discovered work to a separate GitHub issue. Opening a PR requests review; it does not authorize merging.
