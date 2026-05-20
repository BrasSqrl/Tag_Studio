# Tag Studio Context

Tag Studio is a credit memo tagging context for creating reviewed training data from underwriting memos. Its language separates as-of credit judgment from later loan performance so the dataset can preserve both credit-review discipline and outcome signal.

## Language

**As-Of Credit Review Tags**:
Tags that capture what a credit officer could reasonably conclude from the memo and supporting documents at the time credit was extended. These tags must not use later loan performance to rewrite the original credit view.
_Avoid_: Hindsight tags, outcome review tags

**Outcome Tags**:
Tags that capture what happened after credit was extended, anchored to the facility closing date when available. Outcome Tags are separate from As-Of Credit Review Tags even when the reviewer already knows the later outcome.
_Avoid_: As-of tags, credit decision tags

**Outcome Availability State**:
The field that states whether the facility outcome is usable, immature, unavailable, unchecked, or clean after seasoning. It is separate from the Outcome Event Type.
_Avoid_: Outcome label, unknown outcome

**Outcome Event Type**:
The field that states what adverse event occurred when Outcome Availability State is Known Outcome. It is blank or N/A for Not Seasoned Yet, Outcome Data Unavailable, Outcome Not Checked, or No Adverse Outcome Observed.
_Avoid_: Outcome status, availability

**Primary Adverse Outcome**:
The most severe observed Outcome Event Type for a facility, derived from the severity ranking rather than reviewer preference. A facility can have multiple adverse events, but only one Primary Adverse Outcome.
_Avoid_: Selected outcome, main outcome

**Known Outcome**:
A documented post-closing adverse event at any time, or a documented non-adverse outcome after the applicable seasoning window has been reached. A negative event is a Known Outcome even if it occurs less than one year after closing.
_Avoid_: Mature outcome, seasoned outcome

**Not Seasoned Yet**:
A facility state where no adverse outcome has occurred, but less than the applicable seasoning window has passed since the Facility Closing Date. This is not the same as a Known Outcome.
_Avoid_: Performing, no issue, unknown

**Seasoning Window**:
The elapsed time after Facility Closing Date needed before clean performance can be treated as a non-adverse outcome. The default Seasoning Window is 12 months unless a facility-specific rule says otherwise.
_Avoid_: Observation period, waiting period

**Outcome Not Checked**:
A draft-only facility state where the reviewer has not reviewed outcome status. It blocks approval/export because it indicates incomplete workflow rather than reliable credit performance information.
_Avoid_: Unknown, not seasoned

**Outcome Data Unavailable**:
A facility state where the reviewer looked for outcome status, but the required source was unavailable or incomplete. This is different from Outcome Not Checked.
_Avoid_: Unknown, not checked

**Outcome Source**:
The documented source used to support a Known Outcome or No Adverse Outcome Observed, such as a servicing system, risk rating system, watchlist report, workout system, covenant tracker, credit file, or reviewer attestation. Outcome Source is mandatory for known positive or negative outcomes.
_Avoid_: Outcome note, memory

**Outcome Source Type**:
A controlled source category for outcome evidence: servicing system, risk rating system, watchlist or criticized report, workout system, covenant tracking system, credit file, loan review report, reviewer attestation, or other. Reviewer Attestation, Other, and low-confidence sources require a note.
_Avoid_: Free-form source name

**Memo Evidence**:
Evidence excerpted from the credit memo or supporting underwriting package. Memo Evidence supports As-Of Credit Review Tags and Foreseeability, not the fact that a later outcome occurred.
_Avoid_: Outcome evidence, source evidence

**Outcome Source Evidence**:
Evidence from a later system, report, credit file, or Reviewer Attestation that proves an Outcome Availability State, Outcome Event Type, event date, or No Adverse Outcome Observed. Outcome Source Evidence must not be used to justify an as-of underwriting weakness.
_Avoid_: Memo evidence, as-of evidence

**Evidence Record**:
A typed evidence record used in exports and audit trails. Evidence Record can be Memo Evidence or Outcome Source Evidence, with different required fields for each type.
_Avoid_: Citation only, attachment only

**As-Of Review Example**:
A training example that asks the model to review a memo as of approval using memo text, facility structure, and Memo Evidence only. It must not include later outcome facts in the context or response.
_Avoid_: Outcome-aware review example

**Outcome Learning Example**:
A training example that asks the model to analyze the relationship between later outcomes and the as-of memo record. It may include memo text, outcome event summary, Outcome Source Evidence, Foreseeability, and linked Memo Evidence.
_Avoid_: As-of review example

**Outcome-Aware Training Lane**:
The separate training lane that uses outcome data from the start, with instructions that explicitly ask the model to analyze later outcomes in relation to the as-of memo record. Outcome-Aware Training Lane examples must not be mixed into normal As-Of Review Examples.
_Avoid_: General review training, hidden outcome training

**Outcome Explanation**:
An outcome-aware training target that explains how a known later outcome relates to the as-of memo evidence. It is preferred over prediction for initial outcome-aware training.
_Avoid_: Outcome prediction, default forecast

**Seasoned Non-Adverse Outcome**:
A No Adverse Outcome Observed state after the Seasoning Window has elapsed. Seasoned Non-Adverse Outcomes belong in the Outcome-Aware Training Lane so the model learns positive credit signal as well as adverse credit signal.
_Avoid_: Clean before seasoning, unseasoned performing

**Stratified Outcome Dataset**:
An outcome-aware dataset organized into documented slices such as adverse severity, seasoned non-adverse outcomes, facility type, memo type, industry, deal size, and data availability. Adverse outcomes may be intentionally oversampled, but the sampling strategy must be transparent.
_Avoid_: Balanced dataset, random sample

**Dataset Slice Metadata**:
Metadata captured by Tag Studio to support stratified training and evaluation, such as outcome availability state, primary adverse outcome, severity rank, facility type, memo type, seasoning window, industry, source confidence, and permitted reviewer or business-unit fields. Tag Studio captures slice metadata but does not assign training weights.
_Avoid_: Training weights, sampling policy

**Deal Size Band**:
A sample-selection attribute handled upstream before memos enter Tag Studio. It is not required as a Tag Studio input because the project population is controlled through memo selection.
_Avoid_: Required intake field, facility field

**Industry Group**:
An optional but encouraged broad industry category used as Dataset Slice Metadata. Tag Studio should not require precise NAICS-style classification.
_Avoid_: Required industry code, NAICS requirement

**Industry Detail**:
Optional free-text detail about the borrower industry from the memo. Memo Evidence is required when industry detail is used to support a material risk or mitigant.
_Avoid_: Industry code, sector taxonomy

**Reviewer Identity**:
The person who performed tagging or approval. Reviewer Identity must not be included in Training Files, should be excluded from Review Workbooks by default, and may appear in Audit Packages only when explicitly enabled by bank admin configuration.
_Avoid_: Training feature, reviewer cohort

**Customer ID**:
A bank-assigned numeric or opaque identifier supplied upstream before a memo enters Tag Studio. Customer ID is the normal Tag Studio intake field; any outside translation between Customer ID and customer name happens outside the app and training data.
_Avoid_: Borrower name, customer name, pseudonymization inside Tag Studio

**Traceability Identifier**:
An identifier used to connect app records, review artifacts, and audit packages without teaching the model customer-specific information. Customer ID is a Traceability Identifier, not training content.
_Avoid_: Training feature, model input

**Export-Scoped ID**:
A temporary identifier generated for a Training File export, used to group examples without exposing permanent app IDs or Customer ID to the model. Export-Scoped IDs replace internal memo and facility IDs in training JSONL.
_Avoid_: Permanent ID, customer ID, internal ID

**Export ID Mapping**:
The mapping between Export-Scoped IDs and internal app IDs or Customer ID. Export ID Mapping belongs in Audit Packages, may appear in Review Workbooks only when enabled by admin configuration, and must not appear in Training Files.
_Avoid_: Training metadata, JSONL mapping

**Borrower Identity**:
The borrower or customer name, tax identifier, or other direct customer identifier. Borrower Identity should be kept outside Tag Studio by upstream memo selection and ID assignment.
_Avoid_: Training feature, borrower name in JSONL, in-app pseudonymization

**Upstream Memo Sanitization**:
The process outside Tag Studio that prepares uploaded PDFs so they are acceptable for tagging and training preparation. Tag Studio V1 does not promise borrower-name redaction inside PDF text.
_Avoid_: In-app redaction, Tag Studio redaction

**Outcome Source Note**:
The V1 audit text used to describe the outcome source when an uploaded source document is unavailable or optional. Outcome Source Note is mandatory for Reviewer Attestation, Other source type, and low-confidence sources.
_Avoid_: Reviewer comment, free-form outcome

**Reviewer Attestation**:
An Outcome Source where the reviewer documents outcome status from direct knowledge rather than a system of record. It is allowed, but should carry a source confidence and short explanation.
_Avoid_: Verbal source, reviewer memory

**No Adverse Outcome Observed**:
A documented non-adverse facility state after the applicable seasoning window has been reached. This should not be used before the seasoning window unless a separate policy explicitly allows it.
_Avoid_: Performing before seasoning, no bad outcome

**Adverse Outcome**:
A documented post-closing credit-stress event that makes the facility a Known Outcome immediately, regardless of seasoning. Adverse Outcomes include covenant breach, payment delinquency, risk rating downgrade, watchlist/criticized/classified status, stress-driven forbearance or amendment, workout or restructuring, nonaccrual, default, charge-off or realized loss, bankruptcy, and liquidation.
_Avoid_: Routine amendment, clean renewal, administrative waiver

**Foreseeability**:
The relationship between an Outcome Tag and the As-Of Credit Review Tags, indicating whether the later outcome was visible, partially visible, or hindsight-only based on the memo record.
_Avoid_: Blame, prediction accuracy

**Visible In Memo**:
A Foreseeability value meaning the memo contained clear risk facts that pointed toward the adverse outcome.
_Avoid_: Obvious default, proven causation

**Partially Visible**:
A Foreseeability value meaning the memo contained some warning signs, but the eventual severity or path was not fully supported by the as-of memo record.
_Avoid_: Weakly predicted, maybe visible

**Hindsight-Only**:
A Foreseeability value meaning the adverse outcome happened, but the memo did not reasonably show the cause or risk pattern. This protects the training dataset from rewriting the as-of credit view with later information.
_Avoid_: Missed risk, bad review

**Facility Closing Date**:
The date credit was legally extended and the commitment became binding. It is the preferred timing anchor for outcome windows.
_Avoid_: Funding date, first draw date

**Facility-Level Outcome**:
The primary outcome record for Tag Studio, tied to a specific credit facility. Each Facility-Level Outcome has its own status, event date, seasoning window, and foreseeability.
_Avoid_: Borrower-only outcome, memo-level outcome

**Facility Outcome Summary**:
The one-per-facility outcome summary that states Outcome Availability State, Seasoning Window, derived Primary Adverse Outcome, and approval readiness. It is the summary record, not the adverse event sequence itself.
_Avoid_: Outcome event, single outcome label

**Outcome Event**:
A dated adverse event tied to a facility, such as covenant breach, risk rating downgrade, nonaccrual, default, or charge-off. A facility can have zero, one, or many Outcome Events.
_Avoid_: Outcome summary, availability state

**Manual Outcome Event Entry**:
The initial Tag Studio workflow where reviewers enter Outcome Events by hand with source type, source checked date, source confidence, and source note. The structure should remain import-ready for later system integration.
_Avoid_: System integration, automated outcome feed

**Foreseeability Assessment**:
The assessment linking an adverse outcome back to the as-of memo record. In the initial Tag Studio model, the Foreseeability Assessment is tied to the Primary Adverse Outcome.
_Avoid_: Outcome event, outcome source

**Borrower-Level Outcome Rollup**:
A derived summary of facility outcomes for the borrower, normally reflecting the most severe Facility-Level Outcome. It should not replace facility-level tagging when facilities have different structures or performance paths.
_Avoid_: Primary outcome tag, manual borrower outcome

**As-Of Pass**:
The first tagging pass, focused only on what the credit memo and supporting documents show at the time credit was extended. Outcome fields are not part of the As-Of Pass.
_Avoid_: Initial pass, blind review

**Outcome Pass**:
The second tagging pass, focused on facility-level outcome, event timing, seasoning state, outcome source, and Foreseeability. It is separate from the As-Of Pass even when the same reviewer performs both passes.
_Avoid_: Hindsight pass, performance review

## Example Dialogue

Dev: "The reviewer knows this loan defaulted. Should the repayment tag say the deal was weak?"

Domain expert: "Only if the weakness was visible in the memo as of approval. Put the default itself in Outcome Tags and use Foreseeability to say whether the memo showed warning signs."

Dev: "What date starts the outcome window?"

Domain expert: "Use Facility Closing Date, because that is when the bank extended legally binding credit."

Dev: "If a loan defaults six months after closing, is it Not Seasoned Yet?"

Domain expert: "No. A negative event is a Known Outcome immediately. Not Seasoned Yet only applies when no adverse event is known and the seasoning window has not elapsed."

Dev: "If a loan has no adverse events six months after closing, can we tag it as No Adverse Outcome Observed?"

Domain expert: "No. Under the default rule, clean performance before 12 months is Not Seasoned Yet. After 12 months, no adverse event can become No Adverse Outcome Observed."

Dev: "Does every amendment count as an adverse outcome?"

Domain expert: "No. A routine amendment, clean renewal, administrative waiver, pricing change, or borrower-initiated refinance is not adverse unless the documented reason is credit stress."

Dev: "The revolver is fine, but the term loan defaulted. What is the borrower outcome?"

Domain expert: "Tag the default on the term loan first. The borrower-level rollup can reflect the default, but the facility-level outcome remains the primary record."

Dev: "Can an adverse outcome be approved for training with Foreseeability set to Not assessed?"

Domain expert: "No. Adverse outcomes require Foreseeability before approval. Not assessed is only a temporary draft state for adverse outcomes."

Dev: "The reviewer already knows the deal defaulted. Is the As-Of Pass pointless?"

Domain expert: "No. The As-Of Pass is workflow discipline. It captures what the memo supported before the Outcome Pass records what later happened."

Dev: "Can a known outcome be approved without saying where it came from?"

Domain expert: "No. Known positive or negative outcomes require an Outcome Source. Reviewer Attestation is allowed, but it needs confidence and a note."

Dev: "Can we approve a memo when the outcome is Outcome Not Checked?"

Domain expert: "No. Outcome Not Checked means the workflow is incomplete. If the reviewer tried and could not get the data, use Outcome Data Unavailable with a source note."

Dev: "Is Default the same kind of field as Not Seasoned Yet?"

Domain expert: "No. Not Seasoned Yet is an Outcome Availability State. Default is an Outcome Event Type used when the availability state is Known Outcome."

Dev: "A facility had a covenant breach and later defaulted. Which is primary?"

Domain expert: "Default is primary because Primary Adverse Outcome is always the most severe observed event. Keep the covenant breach too because the event sequence matters."

Dev: "Can the reviewer manually pick Covenant Breach as primary if they think it matters most?"

Domain expert: "No. The reviewer edits the event records. Tag Studio derives Primary Adverse Outcome from severity rank, using earliest event date only as a tie-breaker."

Dev: "Can a default notice prove that repayment support was weak in the original memo?"

Domain expert: "No. The default notice is Outcome Source Evidence. Weak repayment support needs Memo Evidence from the as-of package."

Dev: "Can Foreseeability be Visible in Memo without citing the memo?"

Domain expert: "No. Visible In Memo and Partially Visible require linked Memo Evidence. Otherwise the label is not auditable or useful for training."

Dev: "Why not keep one outcome label on the facility?"

Domain expert: "Because availability, event sequence, primary adverse outcome, source evidence, and foreseeability are different concepts. Use Facility Outcome Summary, Outcome Event, and Foreseeability Assessment separately."

Dev: "Will outcome events come from a bank system in the first version?"

Domain expert: "No. V1 uses Manual Outcome Event Entry, but every event should carry enough source metadata that future imports can map into the same structure."

Dev: "Can the reviewer type any outcome source name they want?"

Domain expert: "No. Use Outcome Source Type. If they choose Reviewer Attestation, Other, or Low confidence, they must add a note."

Dev: "Does every outcome event need an uploaded source document?"

Domain expert: "No. In V1, source type, checked date, confidence, and Outcome Source Note are enough. Uploaded documents are optional."

Dev: "Should outcome source notes be exported separately from memo citations?"

Domain expert: "They are both Evidence Records, but with different evidence types. Memo Evidence has page and text fields; Outcome Source Evidence has source type, checked date, confidence, and source note."

Dev: "Can normal credit review examples include the fact that the loan defaulted?"

Domain expert: "No. That belongs in an Outcome Learning Example. As-Of Review Examples must not include later outcome facts."

Dev: "Are outcomes only for evaluation first?"

Domain expert: "No. Outcome data is used as training data from the start, but only in the Outcome-Aware Training Lane where the instruction clearly tells the model it is analyzing later outcome relationships."

Dev: "Should the model be trained to predict default from a memo?"

Domain expert: "Not first. Outcome-Aware Training should teach Outcome Explanation: whether the known outcome was visible, partially visible, or hindsight-only based on the memo evidence."

Dev: "Should outcome-aware training only use bad loans?"

Domain expert: "No. Include Seasoned Non-Adverse Outcomes too. The model needs to learn what good underwriting looks like, not only what failure patterns look like."

Dev: "Should we force a 50/50 split between good and bad loans?"

Domain expert: "No. Use a Stratified Outcome Dataset. You can oversample bad loans for signal, but record the sampling strategy so the model is not evaluated as if it saw a natural portfolio distribution."

Dev: "Should Tag Studio decide how much to oversample defaults?"

Domain expert: "No. Tag Studio captures Dataset Slice Metadata. The tuning pipeline decides training weights, splits, and curriculum."

Dev: "Should reviewers enter deal size band in Tag Studio?"

Domain expert: "No. Deal Size Band is handled by upstream memo selection, not by reviewer input."

Dev: "Does every memo need exact NAICS classification?"

Domain expert: "No. Industry Group is optional but encouraged, and Industry Detail can capture useful memo language without turning Tag Studio into an industry-code system."

Dev: "Should the training file include who tagged the memo?"

Domain expert: "No. Reviewer Identity is excluded from Training Files, excluded from Review Workbooks by default, and only included in Audit Packages when bank admin configuration enables it."

Dev: "Can training files include borrower names from the memo?"

Domain expert: "No. Tag Studio should receive a Customer ID instead of a name. Any mapping from Customer ID back to customer name happens outside the app and outside training data."

Dev: "Will Tag Studio redact borrower names inside uploaded PDFs?"

Domain expert: "No. Upstream Memo Sanitization handles that if required. Tag Studio V1 assumes uploaded PDFs are already acceptable for tagging and training preparation."

Dev: "Should JSONL include Customer ID?"

Domain expert: "No. Customer ID is a Traceability Identifier. It can appear in review or audit artifacts, but is excluded from training JSONL by default."

Dev: "How does the model know two section examples came from the same memo?"

Domain expert: "Use Export-Scoped IDs in Training Files. The export manifest can keep the mapping for audit, but the model does not see permanent IDs."

Dev: "Where does the mapping from export IDs back to internal records go?"

Domain expert: "Put Export ID Mapping in the Audit Package. Keep it out of Training Files, and only include it in Review Workbooks when admin configuration enables it."
