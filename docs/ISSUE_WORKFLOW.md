# Creating GitHub issues

PeopleGator issues describe **what should change and how the result will be verified**. Start from a brief explanation in ordinary language; an AI assistant can inspect the repository, ask for essential missing details and prepare the issue.

## From an idea to an issue

1. **Describe the request.** Explain the problem or desired result in your own words. Add a sample document, error, XML fragment or expected output when useful.
2. **Investigate.** The AI assistant searches existing open and closed issues/PRs and [TODO.md](TODO.md), reads [AGENTS.md](../AGENTS.md) and the relevant processing, architecture and output-format docs, and inspects affected code.
3. **Clarify only important decisions.** Ask focused questions if the intended behavior, scope or a data contract is genuinely unclear. Resolve details already documented in the repository without asking the user.
4. **Draft the issue.** Use the sections below and the [change-request template](../.github/ISSUE_TEMPLATE/change_request.md). Distinguish verified current behavior, requested changes, and assumptions.
5. **Review and publish.** Let the requester review the proposed title and body before posting unless they explicitly asked the assistant to create the issue immediately. Reuse or refine an existing issue when it covers the request.
6. **Implement later.** Work starts from an issue-specific branch based on `develop` and finishes with a tested pull request for review, following [AGENTS.md](../AGENTS.md).

If an important decision is still unresolved, keep a `[Draft]` title and list the open questions. A draft can be refined in the same issue once requirements are settled.

## What a complete issue contains

| Section | What to include |
| --- | --- |
| **Summary** | The requested change and its purpose in a few sentences. |
| **Problem / current behavior** | What happens today, with reproduction steps for bugs or links to relevant code. |
| **Intended behavior** | What should happen after the change; include input/output examples where helpful. |
| **Scope** | Affected processing stages, modules or documents; important boundaries and exclusions when relevant. |
| **Acceptance criteria** | Short, testable checkboxes describing observable results and edge cases. |
| **Validation plan** | Proposed checks from [TESTING.md](TESTING.md), especially synthetic fixtures and ALTO/PAGE XML assertions. |
| **Related work and decisions** | Relevant issues/PRs, dependencies, interface changes and open questions, when applicable. |

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
Ask me short, focused questions if an important requirement needs a
decision. Otherwise draft the full title and issue body for my review.
Create the GitHub issue when I approve it.
```

An AI agent should:

- Prefer refining a relevant existing issue over creating a duplicate; preserve its original goal and discussion.
- Explain current behavior only when supported by code, tests or another cited source. Mark proposals and assumptions clearly.
- Define testable acceptance criteria and a focused validation plan rather than prescribing routine implementation details.
- Flag decisions about person matching, confidence, model choice, coordinates, XML compatibility or API data contracts for clarification when they change existing behavior.
- Keep each implementation issue small enough for a focused pull request; use a parent issue with linked tasks for a larger project.
- Propose labels and priority only when supported by existing repository labels and user instructions.

**Issue preparation and implementation are separate steps.** Drafting or creating an issue does not change code. Tests and actual results belong in the implementation PR.
