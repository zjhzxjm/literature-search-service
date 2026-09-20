# Collaboration

This repository develops a reusable PubMed retrieval service. Read the relevant
owner code, tests, and docs/roadmap.md before changing contracts.

## GitHub ownership

- Milestones own delivery goals and acceptance. Issues own scoped work, decisions,
  dependencies, and evidence. PRs own code review; do not duplicate full issue logs
  into the roadmap. Keep stable contracts and operator guidance in the repository.
- dev is the integration branch. Use one task branch and PR per coherent change.
  Initial repository bootstrap is committed directly to dev; subsequent work uses PRs.
- johnmuin is the execution assistant. Only an open issue explicitly assigned
  to johnmuin with `Execution gate: READY` authorizes work. A later owner HOLD wins.
  Unassigned issues and milestone checklists are not execution instructions.
- Work on one assigned issue at a time unless the owner explicitly permits parallel work.
  Do not independently merge PRs, publish releases, deploy, run full builds, or make
  production/data changes. Report a blocker when scope or frozen inputs are unclear.
- Prefer small tasks with base branch, scope, dependencies, acceptance commands,
  allowed side effects, and stop conditions. Add `Closes #N` only when all acceptance
  conditions are met; use `Refs #N` for partial work.

## Verification and data

- Run `.venv/bin/python -m pytest -q` for the current local test suite. The ES test
  requires a disposable writable ES instance and is otherwise skipped.
- Preserve source records, excluded records, text versions and PMID mapping evidence.
  Original scores/ranks retain backend semantics; configured ColBERT must not silently fall back.
- No corpus, models, index files, private host paths, credentials, raw run logs or
  vendored environment/package copies in Git. Do not clean up referenced experiments.
- Do not add CI, workflows or automatic paid/remote experiments as part of ordinary
  tasks; propose them separately. Local mocked tests are not real-backend acceptance.
- Material storage, truncation, update, deployment or resource decisions require
  owner agreement. The owner selected the existing full baseline indexes as the
  first full-corpus version; preserve their current encoding/truncation settings.
  This selection does not establish HTTP, downstream or production acceptance.
  First-version delivery must not wait for a rebuild. In parallel, the owner has
  requested truncation repair and a new baseline by johnmuin under issue #7;
  freeze the encoding contract and resource plan, then validate a bounded sample
  before the full run. Preserve the old assets; service cutover is a separate step.
