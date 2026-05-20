# Split Outcome Data Model

Tag Studio will model outcome tagging as separate Facility Outcome Summary, Outcome Event, and Foreseeability Assessment concepts instead of a single outcome label on a facility. This preserves the distinction between outcome availability, adverse event sequence, derived primary adverse outcome, outcome source evidence, and as-of memo foreseeability, which is necessary for auditable training data.

## Considered Options

- Single facility outcome label: simpler UI and storage, but it collapses seasoning, event type, source, severity, and foreseeability into one muddy field.
- Split outcome model: more UI and export work, but it keeps outcome signal usable for credit-risk tuning and prevents hindsight contamination.

## Consequences

Primary Adverse Outcome is derived from Outcome Events using severity rank, not manually selected. Positive foreseeability values must be backed by Memo Evidence. In V1, known positive or negative outcomes require outcome source metadata: source type, checked date, confidence, and source note when the source is reviewer attestation, other, or low confidence. Uploaded Outcome Source Evidence can be added later without changing the split model.
