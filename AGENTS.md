# Agent instructions

Before changing code, read [README.md](README.md), the applicable guide in `docs/`, the complete GitHub issue, affected callers and existing tests. Base new work on the latest `origin/develop` and open pull requests against protected `develop`.

## Preparing issues

For a new feature, bug or maintenance request, follow [Creating GitHub issues](docs/ISSUE_WORKFLOW.md). Turn the user's plain-language description into a clear, testable issue by inspecting related issues/PRs, docs and affected source code. Ask focused questions for material missing decisions; otherwise draft the full issue with scope, acceptance criteria and a validation plan. Reuse an existing relevant issue when possible. Publish a new issue after the user approves the draft, or immediately when explicitly instructed to create it.

## Read before editing

- [Architecture](docs/ARCHITECTURE.md): module ownership and end-to-end job flow.
- [Processing](docs/PROCESSING.md): input, engine order and person-occurrence lifecycle.
- [Output formats](docs/OUTPUT_FORMATS.md): ALTO/PAGE structures, app persistence and re-export goals.
- [Testing](docs/TESTING.md): regression matrix, fixtures and validation plans.

## GitHub development workflow

All future implementation jobs must follow this GitHub workflow:

**GitHub issue → issue branch → commits for functional units → pull request.**

1. Start from a GitHub issue, read the problem, scope and verifiable acceptance criteria.
2. Branch from the latest `develop` (unless an issue specifies another base), using `issue/<number>-short-description`. Limit the branch to its issue/scope.
3. Make focused changes in coherent commits and preserve unrelated work. Keep changes reviewable through pull requests.
4. Run appropriate checks, update relevant active docs, and report results accurately.
5. Merge recent `origin/develop` into the topic branch when needed and resolve conflicts locally.
6. Push the issue branch and open a PR targeting `develop`; link the issue, describe resulting behavior, document XML/API changes and include test evidence. Use a draft PR while implementation or validation is in progress.

## Handoff

Report scope, changed behavior/files, tests actually run, unrun checks, and remaining risks/decisions. Link newly discovered actionable gaps to a GitHub issue and update the relevant active documentation.
