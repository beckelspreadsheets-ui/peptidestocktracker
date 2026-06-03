# Data Model

Core entities:
- peptide
- peptide_alias
- company
- security
- asset
- trial
- patent_family
- regulatory_item
- source_document
- claim
- event
- alert

Special design choice: claims are stored separately from events. A low-confidence claim can exist without becoming a high-severity alert.
