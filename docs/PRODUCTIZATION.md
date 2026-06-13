# Productization Guide

This guide packages peptide-watch as a reusable public-source catalyst operating
system without carrying Seth's private operator memory, local credentials, or
deployment state into a new vertical.

The reusable pattern is:

1. Public-source adapters fetch official APIs, filings, registries, dockets,
   company pages, and other lawful public pages.
2. Normalizers store source records and immutable snapshots in the fact store.
3. Change detection creates factual events from new or changed public records.
4. Deterministic scoring orders events by source family, directness, confidence,
   novelty, and configured watch terms.
5. The cockpit exposes a read-only review surface for source facts, source
   health, deadlines, and entity detail pages.
6. The Telegram HQ command surface lets an operator manage workflow state.
7. Operator memory stores attention, notes, statuses, and briefing cursors in a
   separate database from source facts.
8. A language/compliance gate blocks advice, verdicts, private claims, and
   domain-specific prohibited language before any agent sends a briefing.

## What Can Be Reused

- `src/peptide_watch/sources/` adapter patterns.
- `schema/schema.sql` fact-store shape, adjusted for the new domain.
- `src/peptide_watch/relevance.py` deterministic scoring approach.
- `src/peptide_watch/operator_commands.py` command-router pattern.
- `src/peptide_watch/operator_memory.py` separate operator-memory pattern.
- `src/peptide_watch/web/` FastAPI + read-only dashboard API shape.
- `dashboard/` cockpit structure.
- `tools/check_language.py`, `tools/forbidden_language.txt`, and
  `tools/allowed_language.txt`.
- `scripts/peptide_watch_daily.sh`, `scripts/peptide_watch_weekly.sh`, and
  systemd unit patterns after renaming paths/services.
- `docs/AGENT_BRIEFING_HANDOFF.md` as the briefing-agent contract.

## What Must Not Be Copied

Never copy these into a template, public repo, client handoff, or new vertical:

- `.env` or `.env.backup.*`.
- Raw API keys, bot tokens, webhook URLs, Basic Auth values, or chat ids.
- `data/watch.db`, `data/operator_state.db`, `data/*.lock`, or offset files.
- `logs/`, `alerts_outbox/`, or generated backups.
- Personal notes from operator memory.
- Telegram group history or OpenClaw session transcripts.
- Any source payload that a provider's terms do not allow redistributing.

For reusable examples, use placeholders such as `<TELEGRAM_BOT_TOKEN>`,
`<TELEGRAM_CHAT_ID>`, `<REGULATIONS_API_KEY>`, and `<SEC_USER_AGENT>`.

## Clone Checklist

Use this when turning the pattern into another vertical.

1. Pick the domain boundary and name the product rule.
   - Example: "No recommendations. Public sources only."
   - Define forbidden advice/verdict/medical/legal/trading language up front.
2. Replace the domain config.
   - Watch entities, aliases, source groups, query groups, and alert rules.
   - Remove peptide-specific labels unless the new vertical is still peptide
     research.
3. Replace or rename adapters.
   - Keep official/public APIs first.
   - Keep provider keys in environment variables only.
   - Add a source-health explanation for blocked or degraded providers.
4. Update the fact model only where the new domain needs new normalized fields.
   - Keep raw snapshots and event records separate from operator memory.
   - Preserve immutable run ids and source URLs.
5. Rewrite deterministic scoring.
   - Make ordering explainable from source type, directness, freshness,
     recurrence, and configured operator state.
   - Do not let the scoring create conclusions that are not in source facts.
6. Rewrite the language gate.
   - Add the new domain's forbidden phrases.
   - Keep a fail-closed runtime command equivalent to
     `peptide-watch check-language --stdin`.
7. Rename deployment assets.
   - CLI name, systemd service names, cron scripts, dashboard title, and domains.
   - Keep secret-bearing settings in `.env` and local secret stores only.
8. Seed clean state.
   - Run migrations against a new empty fact database.
   - Create a new empty operator-memory database.
   - Do not import Seth's operator memory.
9. Run the gate before sharing.
   - Unit tests.
   - Lint.
   - Language gate over generated briefing text.
   - Secret scan over touched files.
   - Baseline health check for the deployed service.

## Public-Safe Sharing Modes

Current production should remain protected behind Basic Auth.

Recommended sharing levels:

- **Operator mode:** full cockpit plus Telegram commands. Seth/admin only.
- **Trusted read-only mode:** cockpit behind shared credentials, no mutation
  endpoints, no private operator notes unless intentionally shared.
- **Public-safe export:** static or API-derived pages with public source facts,
  source URLs, run ids, source health, and global disclaimers only. Exclude
  operator notes, chat-derived context, and ignored/promoted/watch labels if
  those labels reveal private workflow.

Do not add dashboard mutation endpoints until authentication and authorization
are explicit and tested.

## Soak Gate

Phase 6 is not complete until the live peptide system has at least one week of
stable use:

- Scheduled scans continue to run.
- Briefings post through the peptide bot without duplicate spam.
- `/status`, `/briefing`, `/why`, `/notes`, `/watch`, `/ignore`, and
  `/sourcehealth` remain useful in the HQ group.
- Known source caveats stay visible instead of hidden.
- Operator memory improves ordering and labels without inventing advice.
- No reusable docs or templates contain secrets, personal operator memory, or
  live database files.

Until that soak is complete, treat this document as the reusable packaging draft,
not as proof the product pattern is fully validated.
