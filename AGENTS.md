# Agent instructions

Before changing code, read [README.md](README.md), the applicable guide in `docs/`, the complete GitHub issue, affected callers and existing tests. Base new work on the latest `origin/develop` and open pull requests against protected `develop`.

## Preparing issues

For a new feature, bug or maintenance request, follow [Creating GitHub issues](docs/ISSUE_WORKFLOW.md). Turn the user's plain-language description into a clear, testable issue by inspecting related issues/PRs, docs and affected source code. Ask focused questions for material missing decisions; otherwise draft the full issue with scope, acceptance criteria and a validation plan. Reuse an existing relevant issue when possible. Publish a new issue after the user approves the draft, or immediately when explicitly instructed to create it.

## Isolated implementation workspace (Codex CLI)

For a request consisting only of **`Implement LIBCAS/PeopleGator issue #N`**, carry out the entire [temporary-clone workflow](docs/AGENT_TEMP_CLONES.md) automatically. The user must not need to supply workspace, branch or cleanup instructions. This rule applies to implementation and PR revisions, not read-only reviews or preparing issues.

1. Treat the checkout where Codex was started as **read-only**. Read its instructions, verify the official `LIBCAS/PeopleGator` remote and the issue/PR, and do not switch branches or modify files there.
2. Create a **unique, agent-owned OS temporary directory** (for example with Python `tempfile.mkdtemp()`) and clone the **remote repository**, never the potentially dirty local checkout. Fetch the latest `origin/develop`. For new implementation, create `issue/<number>-short-description` from it; for PR updates, check out the existing remote issue branch. Do not use Git worktrees.
3. Perform **all edits, dependency installs, tests, Git operations and PR preparation within the temporary clone**. Set the working directory explicitly for each tool invocation; a shell `cd` may not persist. Never touch another agent's clone. Keep the existing development/PR workflow below.
4. After a successful push and PR creation/update, verify a clean clone, no unpushed commits, the correct remote branch/PR target, and the exact agent-owned directory before deleting **only that temporary clone**. If any work is uncommitted/unpushed or the handoff fails, preserve it and report its path and the blocker. For review changes, use a fresh clone of the existing remote issue branch.
5. If the sandbox prevents modifying the temporary clone or Git metadata, or blocks network operations, request **narrowly scoped approval** or report the blocker. Do not fall back to editing the primary checkout or disabling the sandbox globally.

See [Temporary clones for coding agents](docs/AGENT_TEMP_CLONES.md) for portable setup, verification, review and cleanup instructions.

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

1. **In the agent-owned temporary remote clone** described above, fetch `origin/develop` and create an issue-specific branch **from its latest commit** (unless the issue names another base), using `issue/<number>-short-description`. For an existing issue PR, fetch and check out its remote branch instead. Do not change the branch or files in the original checkout. Do not implement directly on `develop` or `main`.
2. Implement the agreed behavior in focused units and commit coherent, reviewable changes. Add or update regression tests for new functionality and bug fixes as you work.
3. Run the relevant tests and inspect produced data where applicable. Follow [Testing](docs/TESTING.md); report the exact checks, results and blocked checks. A syntax check alone does not verify expected behavior.
4. Re-read the issue before finishing: check **every acceptance criterion** against the code and test evidence, including important error/empty cases. Record anything still incomplete; do not silently mark it done.
5. Update relevant active documentation for changed engines, configuration, ALTO/PAGE XML, identity mapping or other public behavior. Review the final diff for unrelated changes.
6. Incorporate recent `origin/develop` changes when needed and resolve conflicts without overwriting others' work. Re-run affected checks after resolving conflicts.
7. Push the branch and open a PR **targeting `develop`**, using [the PR template](.github/pull_request_template.md). Link the issue (`Closes #N` only when complete; otherwise `Refs #N`), summarize behavior and acceptance-criteria evidence, list tests and limitations, and request human review. Use a **draft PR** while essential work or verification remains incomplete. Merge only with explicit authorization.
8. After confirming the pushed branch, PR, and clean state of the **temporary clone**, perform the safe cleanup described in [the temporary-clone guide](docs/AGENT_TEMP_CLONES.md). On failure, retain the clone and report its exact path; never remove the original checkout.

## Handoff

Provide the issue and PR links, branch/target, changed behavior/files, **acceptance criteria completed or outstanding**, tests actually run and their results, checks not run (with reasons), documentation changes, temporary-clone cleanup status (or preserved recovery path) and remaining risks/decisions. Link newly discovered work to a separate GitHub issue. Opening a PR requests review; it does not authorize merging.
