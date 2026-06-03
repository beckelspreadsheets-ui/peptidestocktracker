Task 008 — Gemini claim review queue

Implement a claim-seeding script that reads `docs/GEMINI_FINDINGS_REVIEW.md` and `docs/CLAIMS_TO_VERIFY.md` and inserts claims into the database as `needs_verification` or the provided status. Do not promote claims to confirmed unless a primary source adapter verifies them.
