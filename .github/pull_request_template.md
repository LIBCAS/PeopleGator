<!-- Use this template for PRs implementing PeopleGator issues.
Follow AGENTS.md and docs/TESTING.md. Keep actual results separate from planned checks. -->

## Summary

<!-- Describe the resulting behavior or bug fix in 1–3 sentences. -->

## Related issue

<!-- Closes #N if every acceptance criterion is fulfilled; otherwise Refs #N. -->

## Acceptance criteria

<!-- Copy or paraphrase every criterion from the issue. Link its evidence;
mark outstanding criteria explicitly and keep the PR in draft if essential
work or validation is incomplete. -->

| Issue criterion | Status | Evidence |
| --- | --- | --- |
| <!-- Expected outcome --> | <!-- Met / Pending --> | <!-- Test, result or file --> |

## Validation

<!-- List the exact commands/checks actually run and their outcomes.
Explain any unrun/blocked tests and why; a syntax check is not behavioral proof. -->

## Changes to contracts and documentation

<!-- Note relevant ALTO/PAGE XML, identity mapping, configuration and external
API contract effects. Link updated docs or state "None" when applicable. -->

## Outstanding work or risks

<!-- Unresolved requirements, compatibility risks and follow-up issues;
write "None" when all work is complete. -->

## Review checklist

- [ ] The changes stay within the issue's agreed scope.
- [ ] Every acceptance criterion has an outcome and supporting evidence.
- [ ] Relevant processing tests ran successfully, or blockers are documented.
- [ ] Applicable documentation and output contracts are updated.
- [ ] The PR targets `develop` and is ready for human review (or remains a draft).
