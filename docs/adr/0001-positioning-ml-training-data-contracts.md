# ADR 0001 — Position DataCraft as the contract + repair layer for ML feature and training-data pipelines

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Product owner, architecture
- **Supersedes:** the "data contracts for production/warehouse data" direction proposed earlier the same day

---

## Context

DataCraft Studio today is a one-shot dataset-cleaning tool: upload a CSV, profile it,
have an LLM propose cleaning actions, let a human pick, apply, and score the result.
The stated goal is to genuinely reduce the time data scientists spend preparing data
rather than ship another generic "AI cleans your data" product.

An initial proposal was to re-centre the product on **data contracts**: make a versioned,
human-approved, machine-enforceable contract the durable artifact, run it automatically on
every new batch via CLI / CI / orchestrator adapters, and block or repair violations.

Two pieces of evidence then undermined that proposal as written.

### Evidence 1 — the differentiation was already taken

Market research (web, September 2026 — treat as directional and spot-check before it drives
anything irreversible) found:

- **AI contract authoring already ships.** Soda released Contract Autopilot in April 2026
  (profile production data, receive a populated contract with recommended checks). Great
  Expectations 1.21.0 (August 2026) shipped agent skills for LLM-driven expectation
  configuration. This leg is closing, not open.
- **Local/private inference is table stakes.** Small open-weight models run on developer
  laptops, and structured/JSON-schema output is standard. It is a checkbox, not a wedge —
  and the privacy argument is weakened further because our LLM inputs are aggregate
  profiles rather than raw rows.
- **The delivery layer is commodity.** Data Contract CLI (Entropy Data, MIT, ODCS),
  Soda Core v4, Bruin, and dbt contracts all provide versioned contracts with CLI, CI and
  orchestrator integration.
- **Auto-repair is the only genuinely open gap — and it is open for sound reasons.**
  Monte Carlo, Anomalo, Bigeye, Metaplane, GX, Soda and dbt all alert, block or quarantine;
  none repair. They do not repair because remediation requires *intent*, and mutating a
  system of record is a liability and audit problem.

Conclusion: building "contracts for warehouse data" would have produced a Great
Expectations clone with a nicer UI — precisely the outcome the project exists to avoid.

### Evidence 2 — the existing engine is already an ML preprocessing engine

The 28 functions in `execution_engine.FUNCTION_REGISTRY` are scaling, encoding,
imputation and outlier transformation. Initially read as a mismatch for a data-quality
product, this is in fact a signal about domain. That vocabulary is the *wrong* vocabulary
for validating a production ledger, and the *correct* vocabulary for preparing feature and
training data.

## Decision

Position the product as the **contract and repair layer for ML feature and training-data
pipelines**, not for production systems of record.

Under this framing:

- **Auto-repair becomes legitimate.** A training set is a derived artifact. Rewriting it is
  expected and reproducible, so the central liability objection to automatic repair
  dissolves. This turns the market's one open gap into an addressable one.
- **Leakage detection is ML-native and unclaimed.** Existing data-quality vendors are
  warehouse-generic. Leakage, target correlation and train/serve skew are ML concerns, and
  the codebase already has the scaffolding (`_run_ml_pipeline`, target-correlation
  analysis, a leakage score in need of replacement).
- **No-egress becomes a real constraint** rather than a marketing claim, because training
  data is frequently proprietary.
- **The existing engine is used where it is correct** instead of being fought.

## Alternatives considered

1. **Contracts for production/warehouse data.** Rejected — differentiation already taken,
   delivery layer commoditised, and auto-repair is liability-blocked in that domain.
2. **Stay a one-shot cleaning tool.** Rejected — the unit of value is a session, but the
   work repeats every batch. Intelligence is keyed to filenames and dies on cache eviction.
3. **Sell as a generic data-quality dashboard.** Rejected — undifferentiated, competes with
   free tooling, and does not reduce recurring labour.

## Consequences

**Positive.** The engine, profiler and checkpointing all become correctly-oriented rather
than repurposed. Auto-repair — the only open gap — becomes defensible. A clear ML-native
wedge exists that incumbents have no reason to build.

**Negative / risks.** The ML data-prep space has adjacent competition (feature stores,
Great Expectations used inside ML pipelines, no-code prep tools). We take on the burden of
proving that automated repair is *safe*, which means provenance, reversibility and dry-run
diffing are not optional features but the core of the product. We must not ship silent
mutation.

**Sequencing constraint.** Nothing above can be built on the current foundation. The
following verified defects must be fixed first, and they hold under either positioning:

| # | Defect | Evidence |
|---|---|---|
| 1 | Column-type vocabulary is three-way divergent | `data_type_detector.py:40` emits `'date'`; `TYPE_COMPATIBILITY` (`execution_engine.py:854`) only knows `'datetime'`, which the detector never emits; `_get_column_type` (`execution_engine.py:987`) is a second oracle |
| 2 | `quality_score` is dimensionally incoherent | `celery_worker.py:118-124` adds a cell rate to a row rate |
| 3 | Two divergent executors | `execute_transactionally` rolls back; `_apply_actions_to_df` (`celery_worker.py:1021`) silently swallows failures |
| 4 | Repairs are not idempotent | scaling, log, label, one-hot and outlier removal corrupt data on re-run |
| 5 | No data versioning | state keyed by filename (`celery_worker.py:90`); apply overwrites the same path |
| 6 | Validation bypasses exposed on live endpoints | `route_task` (`celery_worker.py:958`) and `perform_dataset_cleaning_task` (`:551`) mutate without validation or cache invalidation |
| 7 | Effectiveness score rewards inaction | a no-op on clean data scores ≈0.70 |
| 8 | Preview fabricates statistics client-side | `DistributionPreviewModal.jsx:350` approximates distributions from aggregate bins; mathematically invalid for nonlinear transforms |

## Immediate follow-up work (this ADR authorises items 1 and 2 only)

1. **Unify the type vocabulary** into one canonical, total module. *(done in this change)*
2. **Make `quality_score` dimensionally honest.** *(done in this change)*
3. Delete the client-side histogram simulation; replace with a backend dry-run returning
   real diffs.
4. Collapse the two executors into one; make every repair idempotent.
5. Introduce content-addressed dataset versioning to replace filename-keyed state.
6. Close the validation bypasses.
7. Replace the composite effectiveness score with a decomposed, per-check report.
8. Emit per-cell provenance (row key, column, old, new, action id, params, contract version)
   from the transactional executor — this is the substrate for both the preview and the
   repair audit trail.

Items 3-8 are **not** in scope for this change and must not be started until items 1-2 are
verified green.
