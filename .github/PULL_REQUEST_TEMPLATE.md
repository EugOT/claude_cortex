<!--
  PR Template
  -----------
  Fill out every section. PRs without a clear summary, test plan, and
  audit notes do not pass review.
-->

## Summary

<!-- One paragraph: what changed and why. Link the issue this addresses. -->

Closes #

## Type of change

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would change existing behavior)
- [ ] Refactor (no functional change; rules/coding-standards.md compliance)
- [ ] Documentation only
- [ ] Audit-finding closure (cite the finding ID)

## Test plan

<!--
  How was this verified? List the specific tests run.
  - Existing tests: `zig build test` pass count?
  - New tests: what mutations would they catch?
  - Manual verification: what did you exercise that automated tests don't?
-->

- [ ] All existing tests pass.
- [ ] New tests added for new behavior.
- [ ] Mutation survival check: I considered what mutations would NOT be caught.
- [ ] Manual verification of any UI / CLI / MCP-tool behavior changes.

## Audit notes

<!--
  Which audit lenses ran on this change? What did they find?
  See CONTRIBUTING.md for the audit cycle.
-->

- Engineering review (code-reviewer / architect / refactorer / test-engineer): findings + closures
- Evidence review (claim verification / measurement / falsifiability / correctness): findings + closures
- Outstanding deferred findings (with follow-up issue links):

## Coding-standards compliance

<!-- See rules/coding-standards.md (or the linked zetetic standard). -->

- [ ] §2.2 Layer dependency direction preserved (no inward layer imports outward).
- [ ] Native Zig allocator ownership is explicit.
- [ ] I/O boundaries are visible and testable.
- [ ] Unsupported compatibility tools return explicit native unsupported status.
- [ ] User-visible claims match implemented and tested behavior.
- [ ] No dead code, no stale runtime instructions, no TODOs without issue references.

## Breaking changes

<!--
  If this is breaking, document:
  - what was the old behavior?
  - what is the new behavior?
  - how do consumers migrate?
-->

## Screenshots / logs

<!-- For UI changes or non-trivial output changes. -->

## Reviewer checklist

- [ ] CHANGELOG.md updated under the appropriate section.
- [ ] Documentation updated (README / SKILL.md / docs/).
- [ ] No secrets / credentials / PII in the diff.
- [ ] CI passes on the latest commit.
