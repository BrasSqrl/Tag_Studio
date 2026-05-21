# Exception-First Section Review

Tag Studio will redesign Confirm Sections around Exception-First Section Review. High-confidence Ready Sections should not interrupt the normal reviewer flow. The reviewer should focus on Section Review Exceptions such as low-confidence matches, missing required sections, duplicate standard section mappings, suspicious boundaries, and text-quality issues.

## Considered Options

- Bulk section approval: simple to implement, but it forces nontechnical credit reviewers through every detected section and makes the workflow feel like a data-entry form.
- Exception-first review: requires clearer exception classification and gating logic, but it focuses the reviewer on decisions that actually affect downstream tagging and facility setup.

## Consequences

Confirm Sections should present a Review Section Exceptions queue, a collapsed Ready Sections area, and a clear All Required Sections Are Ready completion state. Blocking Section Exceptions must be resolved before facility setup. Section Warnings can remain visible without blocking when they do not affect required or facility-relevant sections. Heading Alias learning should occur only during deliberate Section Exception Resolution.

The first implementation stage should deliver the main UX transformation: exception classification, Must Fix / Can Review Later / Ready counts, exception-first UI, collapsed Ready Sections, immediate Accept Suggestion, a basic missing-section workflow, and boundary tools hidden behind Fix Boundary. Later stages can add admin-configurable thresholds, richer not-applicable rules, manual section creation polish, page preview integration, and more advanced suspicious-boundary scoring.
