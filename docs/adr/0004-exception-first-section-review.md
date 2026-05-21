# Credit-User Memo Section Review

Tag Studio will redesign the section step around credit-user language. High-confidence section matches should not interrupt the normal reviewer flow. The reviewer should focus on items that need judgment, such as low-confidence matches, missing required sections, duplicate standard section mappings, section text placed in the wrong area, and text-quality issues.

## Considered Options

- Bulk section approval: simple to implement, but it forces nontechnical credit reviewers through every detected section and makes the workflow feel like a data-entry form.
- Parser-style split/merge controls: powerful for developers, but clunky and unintuitive for credit reviewers.
- Credit-user section cleanup: requires block-level cleanup behavior, but lets reviewers decide where memo text belongs without line numbers or parser language.

## Consequences

Review Memo Sections should present items that need correction, items that need reviewer acceptance, and items already accepted. Blocking items must be resolved before facility setup. Optional checks can remain visible without blocking when they do not affect required or facility-relevant sections, but every detected section still needs explicit Section Acceptance before the workflow continues.

Normal reviewers should use Accept This Section to confirm that a section's text belongs under the displayed Standard Memo Section. Ready Sections can be accepted one at a time or through Accept All Looks Good Sections. If duplicate Standard Memo Section warnings are intentional because the memo has multiple text blocks that belong under the same Standard Memo Section, accepting those sections resolves the warning. Normal reviewers should use Clean Up Section Text to move paragraph-sized blocks, start a new section from selected text, add text to the prior section, or mark duplicate text. Normal reviewers should not see split, merge, boundary, or alias language. Heading learning should happen quietly from saved section corrections and remain visible only to administrators.
