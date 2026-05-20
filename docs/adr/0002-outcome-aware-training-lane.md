# Outcome-Aware Training Lane

Tag Studio will use outcome data as training data from the start, but only in a separate Outcome-Aware Training Lane whose instructions explicitly ask the model to analyze later outcomes in relation to the as-of memo record. Normal As-Of Review Examples must not include later outcome facts, so the model can learn outcome signal without smuggling hindsight into ordinary credit review behavior.

## Considered Options

- Evaluation-first outcome use: safer against hindsight contamination, but delays the project thesis that credit memo outcomes contain trainable underwriting signal.
- Mixed normal training: maximizes exposure to outcome data, but risks teaching the model to behave as if future performance is available during as-of review.
- Segregated outcome-aware training: uses outcome signal immediately while preserving clean as-of review examples.

## Consequences

Export generation must keep As-Of Review Examples and Outcome Learning Examples separate. Fine-tuning jobs should preserve this distinction through explicit instructions, dataset naming, and evaluation slices.
