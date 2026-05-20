# Customer ID and Upstream Memo Sanitization

Tag Studio will use a bank-assigned Customer ID as the normal intake identifier instead of borrower or customer name. Any mapping from Customer ID to customer name, and any borrower-name redaction or sanitization inside uploaded PDFs, is handled upstream outside Tag Studio in V1.

## Considered Options

- In-app borrower name handling and redaction: convenient for users, but makes Tag Studio responsible for a high-risk document redaction workflow.
- Customer ID with upstream sanitization: narrower scope, clearer privacy boundary, and avoids weak redaction promises.

## Consequences

The normal UI should ask for Customer ID, not borrower name. Training exports must not introduce borrower identity fields, and Tag Studio should not claim that uploaded PDF text has been redacted unless a later explicit redaction feature is built.
