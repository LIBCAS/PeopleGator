# Creating GitHub issues

PeopleGator issues describe **what should change and how the result will be verified**. Start from a brief explanation in ordinary language; an AI assistant can inspect the repository, ask for essential missing details and prepare the issue.

## From an idea to an issue

1. **Describe the request.** Explain the problem or desired result in your own words. Add a sample document, error, XML fragment or expected output when useful.
2. **Investigate.** The AI assistant searches existing open and closed issues/PRs and [TODO.md](TODO.md), reads [AGENTS.md](../AGENTS.md) and the relevant processing, architecture and output-format docs, and inspects affected code.
3. **Clarify material decisions before deciding.** If behavior, scope, defaults, validation/error handling, compatibility, stored data or an API contract is not established by the request or repository, ask the requester concise, focused questions. Do not guess. Resolve details already settled by the code or documentation without asking.
4. **Draft the issue.** Use the sections below and the [change-request template](../.github/ISSUE_TEMPLATE/change_request.md). Separate verified current behavior, approved requirements, unapproved proposals and unresolved decisions. Apply the requirement-origin rule below.
5. **Review and publish.** Audit requirement origins before creating or updating an issue, including immediate publication requests. Let the requester review the proposed title and body unless explicitly asked to publish immediately. If immediate publication was requested despite unresolved material decisions, publish a `[Draft]` issue with visible open questions. Otherwise clarify those decisions before publishing a ready issue. Reuse or refine an existing issue when it covers the request.
6. **Implement later.** Work starts from an issue-specific branch based on `develop` and finishes with a tested pull request for review, following [AGENTS.md](../AGENTS.md).

A `[Draft]` issue must identify the outstanding decisions in an **Open questions / decisions** section. Update that same issue with the requester's answers before removing `[Draft]`; do not start implementation while material decisions remain open.

**Implementation readiness:** Before assigning an issue to a coding agent, confirm that its intended outcome, scope, acceptance criteria and required decisions are clear enough to implement and verify. The agent should refine an issue with material open questions before beginning work, then follow the [implementation workflow](../AGENTS.md#github-development-workflow).

## Requirement origins and pre-publication audit

Every implementation requirement, scope item and acceptance criterion must be traceable to an explicit requester instruction, a verified existing project contract applicable to the task, or a specific proposal explicitly approved by the requester. A prior assistant recommendation, an unreviewed draft or a general request to create or publish an issue does not approve additional requirements. Verified current behavior is evidence, not automatic approval to change it.

Before publishing **or updating** an issue, compare each requirement, scope item and acceptance criterion with the original request, applicable verified contracts and approved decisions. Remove unsupported additions or label them separately as unapproved proposals outside implementation scope; ask for explicit approval before including them as requirements. An optional enhancement does not make an otherwise ready issue a Draft, but an unresolved material decision needed for implementation does. Immediate publication does not waive this audit or Draft handling. Keep the review proportionate; no mandatory provenance table or additional approval metadata is required.

## When to ask rather than assume

A decision is **material** when different reasonable answers would change the expected result or scope, a default or failure policy, a compatibility requirement, stored data, or an interface/API contract. Clarify it with the requester **before choosing an implementation**. Existing, verified applicable contracts and behavior-preserving implementation choices can resolve ordinary details without another question. Do not interpret general simplicity, reuse or efficiency guidance as approval for additional behavior. Unrequested optimizations, caching/memoization (including operation-local state to avoid API requests), deduplication, batching, validation, restrictions, defaults, fallback/recovery or other behavior changes require explicit approval unless already required by the requester or an applicable verified contract.

| Situation | Required action |
| --- | --- |
| It is unclear whether ambiguous matches should link to an existing identity or remain unmatched. | Ask which behavior is intended; do not invent a matching rule. |
| A proposed change would add a default, new validation failure, persistence field or compatibility behavior not requested or documented. | Ask whether that behavior is wanted; do not silently expand the issue. |
| Existing code and documentation unambiguously define the relevant engine interface or file/path convention. | Follow that contract without asking the requester to repeat it. |
| The choice is only an internal name, a data structure for an approved operation or an existing model method with identical semantics. | Choose the simplest behavior-preserving approach without unnecessary questions. |
| Suppressing repeated entity lookups when exporting faces with their original UUIDs ([#76](https://github.com/LIBCAS/PeopleGator/issues/76) / [PR #77](https://github.com/LIBCAS/PeopleGator/pull/77)). | The UUID requirement does not authorize changing request frequency. Ask before adding suppression, or omit it; once suppression is approved, selecting a local set to implement it is a routine choice. |

If a material question arises **during implementation**, follow [the agent instructions](../AGENTS.md#before-implementation): stop the affected work, obtain the decision, and update the issue before continuing. Distinguish necessary in-scope corrections (explain them in the PR) from prerequisite defects that require material scope expansion (report and obtain approval first) and optional adjacent improvements (leave out unless approved). Review the final diff against approved requirements and disclose additional changes and unresolved decisions.

## Implementing an existing issue with Codex CLI

Start `codex` normally from the **root of your existing PeopleGator checkout**, then give it only:

```text
Implement LIBCAS/PeopleGator issue #N
```

The root [`AGENTS.md`](../AGENTS.md) instructs the agent to create and work exclusively in **its own temporary remote clone**, push an issue branch, open a PR against `develop` and delete the clone **only after safe handoff**. You do not need to describe branching, sandbox or cleanup steps in every prompt, and should not use `codex --worktree` for this workflow. For permission prompts, review iterations, operating-system portability and safe cleanup, see [Temporary clones for coding agents](AGENT_TEMP_CLONES.md). This applies to **implementation**; issue drafting remains a separate workflow.

## What a complete issue contains

| Section | What to include |
| --- | --- |
| **Summary** | The requested change and its purpose in a few sentences. |
| **Problem / current behavior** | What happens today, with reproduction steps for bugs or links to relevant code. |
| **Intended behavior** | What should happen after the change; include input/output examples where helpful. |
| **Scope** | Affected processing stages, modules or documents; important boundaries and exclusions when relevant. |
| **Acceptance criteria** | Short, testable checkboxes describing observable results and edge cases. |
| **Validation plan** | Proposed checks from [TESTING.md](TESTING.md), especially synthetic fixtures and ALTO/PAGE XML assertions. |
| **Related work** | Relevant issues/PRs and dependencies, when applicable. |
| **Open questions / decisions** | Unresolved material decisions and separately identified unapproved proposals, when applicable; required for a `[Draft]` issue. |

Focus technical detail where it matters: image regions and face coordinates; OCR/caption context; proposed versus matched identities; ALTO/PAGE XML contracts; engine configuration; and PeopleGatorApp API interactions. Include DocAPI-related details only when the request concerns that integration.

Write proportionately. A small bug may need only a few paragraphs and checkboxes; a change to the XML format or matching behavior needs a more precise contract. Acceptance criteria should describe **outcomes**, not only tasks such as “write code” or “add tests.”

## AI-assisted issue writing

A reusable instruction for a GitHub-connected assistant:

```text
Create or refine a GitHub issue for LIBCAS/PeopleGator from this description:

<describe the change in ordinary language>

Follow docs/ISSUE_WORKFLOW.md and AGENTS.md. Search related issues/PRs
and inspect relevant code and documentation. Identify verified behavior,
the expected result, scope, acceptance criteria, and processing tests.
Trace every requirement, scope item and acceptance criterion to my explicit
instructions, a verified applicable project contract or a proposal I explicitly
approved. Do not guess or add unrequested optimizations or other behavior.
Ask focused questions about material decisions; keep unapproved optional
proposals outside implementation scope. Audit requirement origins before
creating or updating the issue, even if I request immediate publication.
Otherwise draft it for my review. Publish when I approve or explicitly request
publication; if material decisions remain open and I request publication, use
[Draft] and list the open questions.
```

An AI agent should:

- Prefer refining a relevant existing issue over creating a duplicate; preserve its original goal and discussion.
- Explain current behavior only when supported by code, tests or another cited source. Distinguish verified facts, explicit requirements, proposals and open questions.
- Define testable acceptance criteria derived from approved requirements and a focused validation plan rather than prescribing routine implementation details.
- Ask the requester about unresolved material decisions (for example person matching, confidence, model choice, coordinates, XML compatibility, error policy or API contracts) instead of assuming the answer.
- Keep each implementation issue small enough for a focused pull request; use a parent issue with linked tasks for a larger project.
- Propose labels and priority only when supported by existing repository labels and user instructions.

**Issue preparation and implementation are separate steps.** Drafting or creating an issue does not change code. Tests and actual results belong in the implementation PR.
