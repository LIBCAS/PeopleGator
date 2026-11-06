# Agent-owned temporary clones for issue implementation

This is the implementation workspace policy referenced by [`AGENTS.md`](../AGENTS.md). It applies to **coding/documentation changes and PR-review revisions**, not read-only inspection or drafting issues.

## One-line Codex workflow

From the **root** of the existing local PeopleGator checkout, start Codex normally:

```console
codex
```

The entire user instruction can be:

```text
Implement LIBCAS/PeopleGator issue #N
```

Codex loads the repository-root `AGENTS.md` at session start; the agent must follow its temporary-clone policy without a longer task prompt. Do **not** use `codex --worktree`. If the expected rules are not loaded, check the starting directory and whether an `AGENTS.override.md` or global guidance supersedes them; restart Codex after changing instruction files.

## Required lifecycle (agent-owned)

1. **Inspect, without modifying the primary checkout.** Read the complete issue, comments, relevant PRs, `AGENTS.md`, and applicable docs. Verify that the checkout's `origin` points to the official `LIBCAS/PeopleGator` GitHub repository (HTTPS or SSH, with normal existing authentication). Check for an existing issue branch/PR. If the issue is not implementation-ready, resolve the blocker before coding.
2. **Create a unique temporary clone.** Use the operating system's temporary-directory facility (e.g. Python `tempfile.mkdtemp(prefix="peoplegator-issue-<N>-")`). This respects `TMPDIR`/`TEMP`/`TMP` as appropriate. Store the created root path for later verification. Clone the **official remote URL**, not `.`, a local path, or the primary checkout. Never copy local ignored files or credentials into the clone.
3. **Check out the issue branch within the clone.** Fetch and inspect `origin/develop`. For a new issue, create `issue/<number>-short-description` from that current remote commit. If continuing an existing PR, fetch and check out its **existing remote issue branch**, verifying the PR head and owner first; do not create a competing branch or force-push over another agent's work. Use a distinct issue branch for distinct simultaneous tasks.
4. **Keep all mutations inside the clone.** Execute source edits, patch tools, dependency installation, tests, `git add`/`commit`/`push`, and PR preparation with the temporary clone as their explicit working directory. A `cd` from one shell invocation may not affect later commands; set each command's `cwd`/`workdir`, use `git -C <clone>`, and ensure patch tools target clone paths. **Never** switch branches, reset/clean, edit, stage or commit in the primary checkout or another agent's directory.
5. **Verify and hand off.** Complete the issue's tests and acceptance review. Push to the correct remote issue branch and create/update the PR targeting protected `develop` following [the PR template](../.github/pull_request_template.md). Use `Closes #N` only if the issue is fully implemented; otherwise use `Refs #N` and a draft PR where essential work remains. Do not merge without human authorization.
6. **Safely remove the temporary clone when complete.** See the checks below. When a PR needs review changes, start a **new temporary clone** and fetch that PR's existing branch; there is no need to retain the original clone after a successful push and PR handoff.

### Portable setup example for an agent

The user does **not** run these commands; the agent carries out the equivalent steps. This Python example works with standard temporary-directory conventions on Linux, macOS and Windows (given an installed Python and Git):

```python
from pathlib import Path
import subprocess
import tempfile

issue_number = 34  # Example only: use the requested issue.
primary = Path.cwd()  # Read-only; must be the official repository root.
remote = subprocess.check_output(
    ["git", "-C", str(primary), "remote", "get-url", "origin"],
    text=True,
).strip()
# Verify that this is the official LIBCAS/PeopleGator HTTPS/SSH remote
# before running git clone. Do not clone from a local filesystem path.

temp_root = Path(
    tempfile.mkdtemp(prefix=f"peoplegator-issue-{issue_number}-")
).resolve()
clone = temp_root / "PeopleGator"
subprocess.run(["git", "clone", remote, str(clone)], check=True)
subprocess.run(["git", "-C", str(clone), "fetch", "origin", "develop"], check=True)
subprocess.run(
    [
        "git", "-C", str(clone), "switch", "-c",
        f"issue/{issue_number}-short-description", "origin/develop",
    ],
    check=True,
)
# Subsequent tool operations must explicitly target clone, not primary.
```

This example shows a **new** branch. For PR revisions, replace the new-branch step with fetching and checking out the existing PR head from the remote. If a branch with the intended name already exists, inspect it first rather than overwriting it.

## Sandbox, network and shared resources

- Use `/status` in Codex CLI to inspect active sandbox/approval settings and writable roots. System temporary locations may be writable by default, but cloned `.git` metadata can still be protected; fetching, cloning and pushing can also require network approval. Request **narrowly scoped approvals** when prompted. Do not recommend `--dangerously-bypass-approvals-and-sandbox`, `danger-full-access` or unrestricted filesystem access.
- If the agent cannot reliably write to the temporary clone or direct its editing tools there, **stop and report the permission/workdir blocker**. Do not edit the original checkout as a fallback.
- Install dependencies into an environment belonging to the clone (e.g. its own `.venv`), and keep output/test artifacts inside it. Worktree isolation is not relevant here: these are full independent Git clones. Separate agents must still coordinate any shared external databases, server ports, caches, model files or services.
- A temporary directory is disposable and may be purged by the OS. Recoverable changes must be **committed and pushed** before deleting it. Never rely on a temp path as a durable backup.

## Safe cleanup gate

The agent may delete **only its own recorded temporary directory**, and only **after all** checks succeed:

- The requested implementation and verification/handoff are finished, and the PR exists (or has been updated) against `develop`; record the PR URL.
- Every intended change is committed, and the clone has **no meaningful uncommitted or untracked work**. Check `git status --porcelain --untracked-files=all`.
- The issue branch is pushed and its local `HEAD` agrees with the remote issue branch after fetching its latest state; no local unpushed commits remain.
- The path is exactly the unique temporary root the agent created. Verify its name, ownership, resolved location and contained clone; it must **not** be the original checkout, its ancestor, an unrelated shared directory, or another agent's clone.

Only then remove that recorded temporary root, without wildcard paths or forced Git cleanup. **Never** delete a clone with unpushed commits, work worth preserving, an unsuccessful PR handoff or an uncertain directory identity. Instead retain it and report the path, branch, status and blocker. An agent must not delete a user's primary checkout even if it happens to be located in the OS temporary directory.

For a later review iteration, make a fresh temporary clone, fetch the already-pushed issue branch, commit/push the requested changes to the same PR, and repeat the cleanup checks.

## Verification

- Run two distinct isolated clones/issue branches in parallel; confirm both have different work directories and Git metadata and the original checkout remains unchanged.
- Verify that fresh `origin/develop` is used for new issues; review iterations correctly reuse their existing remote issue branch.
- Verify the clone remains intact when changes are uncommitted, unpushed or PR creation fails; successful push plus PR handoff permits safe deletion.
- Confirm cross-platform temporary paths, link targets and documentation consistency. Record exactly which Codex/sandbox/remote checks were executed and which were blocked.
