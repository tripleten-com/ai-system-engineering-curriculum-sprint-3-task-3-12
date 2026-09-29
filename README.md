# Coldline Task 3.12 — Optional Task 12: Second fault variation

This checkpoint is the complete, settled Coldline platform from Task 3.7, and its runbook,
`docs/student/runbook.md`, already covers one failure: the bounded worker outage Task 3.6's
failure lab produces. This Task asks whether that runbook is a method or a memory. A supplied
catalog, `infra/faults/catalog.yaml`, offers two faults the runbook does not cover; a supplied
lab, `poe fault-lab --fault <id>`, breaks the platform with the one you choose for a bounded
window, recovers, and writes the evidence file; a supplied check, `poe baseline-check`, proves
the platform is back at baseline on its own. You correlate the trace, metric, log and queue
evidence for one reading, verify recovery by hand, record it in `submission.yaml`, and append
a second detection-to-verification entry to the runbook without changing the first. This Task
is optional and adds no code.

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/tripleten-com/ai-system-engineering-curriculum-sprint-3-task-3-12/tree/main)

## Start the system

Prerequisites are Python 3.12 and Docker with Compose v2. The supplied bootstrap supports macOS
arm64/x86-64, Windows x86-64, and Linux x86-64/aarch64, and installs pinned uv 0.11.8 under
`.tools/bin`. If your computer cannot run the stack locally, use the Codespaces button above.

On macOS and most Linux distributions the interpreter is `python3`; substitute it wherever these
commands say `python`.

```shell
python infra/scripts/bootstrap.py
./.tools/bin/uv sync --frozen
./.tools/bin/uv run --frozen poe preflight
./.tools/bin/uv run --frozen poe start
./.tools/bin/uv run --frozen poe ready
./.tools/bin/uv run --frozen poe ingest
```

PowerShell and POSIX wrappers are available under `infra/scripts/`. After uv is on `PATH`, the
shorter `uv run --frozen poe <task>` form works.

| Service | Local URL | Purpose |
|---|---|---|
| API | `http://localhost:8000` | Submit exception workflows and retrieval queries; `/version` names the build that answers |
| Grafana | `http://localhost:3000` | Use the focused diagnostics dashboard |
| Prometheus | `http://localhost:9090` | Query bounded metrics and inspect the deployed alert rule |
| Alertmanager | `http://localhost:9093` | Inspect firing and resolved alerts |
| Jaeger | `http://localhost:16686` | Inspect local traces |
| LocalStack S3/SQS | `http://localhost:4566` | Inspect the emulated object-storage and queue endpoint |

Each of these ports can be overridden by setting the matching `COLDLINE_API_HOST_PORT`,
`COLDLINE_GRAFANA_HOST_PORT`, `COLDLINE_PROMETHEUS_HOST_PORT`, `COLDLINE_ALERTMANAGER_HOST_PORT`,
`COLDLINE_JAEGER_HOST_PORT`, or `COLDLINE_LOCALSTACK_HOST_PORT` environment variable in your shell
environment or a local `.env` file (copy `.env.example`) if a default collides with something
already running on your machine. Keep the override in place for every `poe` command; the lab
and the baseline check read `COLDLINE_API_HOST_PORT`, `COLDLINE_LOCALSTACK_HOST_PORT`,
`COLDLINE_ALERTMANAGER_HOST_PORT`, and `COLDLINE_JAEGER_HOST_PORT` the same way the stack does.

PostgreSQL, Redis, worker metrics, and OTLP remain inside the Compose network. Codespaces uses the
same `compose.yaml` and keeps every forwarded port private. Redis keeps running in this Task only
for an earlier checkpoint's own contract test; no composition root reads it anymore.

## Command path

For this Task, run the supplied commands in this order:

```text
poe start
poe ready
poe ingest
poe fault-lab --fault <id>
poe baseline-check
poe verify
```

Between `poe fault-lab` and `poe verify` sit the lesson's Steps: your own samples from the
window, the correlation of one reading across Jaeger, Prometheus, the worker logs and the queue
samples, the manual recovery checks, `poe baseline-check`, the answer sheet, and the second
runbook entry.

| Command | Use |
|---|---|
| `poe fault-lab --fault <id>` | Run one catalog fault against the running stack: apply it inside the worker container for its `duration_seconds` while submitting five readings, lift it, wait for every reading to reach a terminal state with both queues at zero, sample traces from Jaeger, and write `docs/student/faults/<id>-lab.json` with a generator marker and a content digest. Refuses an id that is not in the catalog |
| `poe baseline-check` | Prove return to baseline on its own: read the exception ids from the committed lab files, measure whether every one is terminal, both queue depths, and the readiness status, print the four fields as one JSON object, and exit 0 only at baseline |
| `poe answers` | The static half of this Task's own check: the answer sheet's format and the diff from your merge base against the permitted files |
| `poe fault-checks` | The assessed checks: the lab file for your chosen fault is as the lab wrote it and reports baseline, your evidence cites its trace ids, your counts cover its readings, the first runbook entry is unchanged and a second one names your fault with its four sections, and `poe baseline-check` passes against the running stack and matches the baseline fields you recorded |
| `poe fault-runbook-contract` | `poe answers` and `poe fault-checks` together; the check `poe verify` runs for this Task. It does not rerun the fault |
| `poe verify` | The public student verification path: it starts the stack, ingests the corpus, runs `poe fault-runbook-contract`, then the smoke tests, the end-to-end workflow, and the supplied student tests |
| `poe redrive` | Task 3.3's redrive, and the command Step 4 names: move every dead-lettered message back to the main queue, wait for each to complete, then deliver the most recently sent one once more and confirm its completed record is unchanged; older ones are listed under `also_redriven` |
| `poe queue-contract`, `poe slo-contract`, `poe gate-contract`, `poe fidelity-check` | The inherited Task 3.3 through 3.6 checks over the settled checkpoint; still runnable, not part of this Task's verify path. Task 3.6's one-entry runbook structure check is retired here, because the finished runbook holds two entries |
| `poe contract` | Check interfaces, boundaries, submissions, and repository structure |
| `poe smoke` | Check the initialized running platform |
| `poe e2e` | Run the external API-to-worker workflow |
| `poe student-tests` | Run the supplied tests under `tests/student/`; this Task permits no additions there |
| `poe dev-failure-lab` | Task 3.6's failure lab, the fault the first runbook entry was written from; still runnable, not this Task's fault |
| `poe trigger-alert-load`, `poe verify-alert-recovery`, `poe inject-failure` | Inherited exercises from Tasks 3.3 and 3.4, still runnable; not part of this Task |
| `poe restart` | Restart the existing API and worker containers **without rebuilding** |
| `poe stop` | Remove containers and the network, keeping named volumes |
| `poe reset` | Remove containers, the network, and local named volumes |

For Task 3.12, `poe verify` starts the stack, ingests the supplied corpus, runs `poe answers`,
runs the fault checks over the lab file you committed and the runbook you extended (one of them
runs `poe baseline-check` against the stack), then the smoke tests and the end-to-end exception
workflow, and the supplied student tests. The inherited Task 3.3 through 3.6 checks are not in
this path; they remain runnable on their own.

## The catalog, the lab, and the baseline check

`infra/faults/catalog.yaml` lists exactly two faults, each with an `id`, one line saying what it
breaks, and its `duration_seconds`:

- `provider_outage`: the model provider emulator returns errors for the window. Inside the worker
  container, `src/adapters/model/faults.py` sets a flag the emulator reads on every call; while it
  is set, every summary attempt fails as retryable, the resilient wrapper spends its attempt
  budget, and the worker returns the delivery for the transport to redeliver after the queue's
  30 s visibility timeout.
- `queue_unavailable`: the LocalStack SQS endpoint is unreachable from the worker for the window.
  Inside the worker container, `src/adapters/queue/faults.py` wraps the worker's queue client so
  every call fails as the endpoint does when it does not answer; the API, the initializer, and
  the host-side queue tools still reach LocalStack, so readings the API accepts wait on the queue
  with no consumer able to receive them.

Both controls are flag files under `/tmp` in the worker container, set and cleared with
`docker compose exec`. `poe fault-lab` runs them for you, lifts any fault an interrupted run left
behind before it starts, and lifts the fault it applied in a `finally` block, so a run you
interrupt never leaves the emulator broken. You never run the controls by hand in this Task, and
you never edit the catalog, the lab, or the controls to make a different failure happen.

The lab file names the fault and its window, lists the readings it submitted with the state each
showed while the fault was active and the terminal state it reached, the queue and dead-letter
depth samples inside the window and during recovery, the Jaeger trace ids it sampled, the alert
state it saw inside the window and after recovery, how many messages it redrove, the four
baseline fields, and `returned_to_baseline`. The check recomputes the digest, so a file edited by
hand fails; rerun instead. `poe baseline-check` prints the same four baseline fields from its own
measurement: copy those into `answers.recovery.baseline`, not the lab file's block.

## Folder map

```text
repository root/
├── docs/                Student guidance, public contracts, and fidelity notes
│   ├── contracts/       Machine-readable public contracts
│   ├── fidelity/        Local-runtime boundary notes, including the settled JobQueue record
│   ├── architecture/    Supplied vector engine technical profiles, in prose
│   ├── retrieval/       Supplied retrieval pipeline reference
│   └── student/         This Task's contract, the runbook you extend, and faults/ for the lab file
├── config/              Retrieval configuration, settled and supplied from Sprint 2
├── infra/               Local setup and runtime configuration
│   ├── containers/      The API and worker Dockerfiles, with the build identity arguments
│   ├── faults/          The supplied fault catalog
│   ├── observability/   Prometheus, Alertmanager, and Grafana configuration
│   ├── release/         The supplied Task 3.1 release manifest, unchanged
│   ├── corpus/          Supplied synthetic corpus, query set, and designated investigation
│   ├── judge/           Supplied cached judge evidence and its provenance record
│   ├── profiles/        Supplied engine and emulator profiles, and their provenance record
│   └── postgres/        Database initialization and the migration baseline stamp
├── loadtest/            Supplied traffic profile and provider-latency harness
├── migrations/          Alembic environment, revision template, and revisions
├── src/
│   ├── api/             HTTP application code, the retrieval and document paths, composition
│   ├── worker/          Background application code, including the dead-letter depth poller
│   ├── domain/          Shared domain code, contracts, the failure taxonomy, service and repository contracts
│   ├── ports/           Application interfaces
│   └── adapters/        Technology-specific implementations, including both supplied fault controls
└── tests/
    ├── unit/            Isolated behavior checks
    ├── benchmark/       Supplied evaluation harness, metrics, and adoption policy
    ├── contract/        Interface, retrieval, and repository checks, and this Task's fault checks
    ├── diagnostics/     Supplied stage inspector
    ├── doubles/         Supplied deterministic test doubles
    ├── failure/         Supplied exercise scripts from Tasks 3.3, 3.4, and 3.6, and this Task's lab and baseline check
    ├── fixtures/        The blank answer sheet and the supplied first runbook entry, as the checks compare them
    ├── student/         Supplied student tests; no additions in this Task
    ├── smoke/           Running-platform checks
    └── e2e/             Supplied workflow tools and checks
```

## Overview

Use the Optional Task 12 lesson (Task 3.12 in this repository) to decide what to do. This README
covers local setup and repository orientation.

1. `README.md` — local setup, commands, and permitted changes.
2. [`docs/student/task-3-12-contract.md`](docs/student/task-3-12-contract.md) — what this Task
   assesses and who assesses it, the five Steps, the commands, the mapping from the lesson's
   Check-list to each check, and the permitted paths.
3. [`infra/faults/catalog.yaml`](infra/faults/catalog.yaml) — the two faults, with their windows.
4. [`docs/student/runbook.md`](docs/student/runbook.md) — the supplied first entry, which stays
   as it is; your second entry goes below it.
5. [`docs/fidelity/JobQueue.md`](docs/fidelity/JobQueue.md) — what LocalStack SQS does not prove;
   the limits the queue fault sits inside.

The application source lives in five flat packages:

| Package | Responsibility |
|---|---|
| `api` | HTTP delivery, API use cases, the retrieval workflow, versioned routes, configuration, and composition |
| `worker` | Background processing, retries, the dead-letter depth poller, configuration, and composition |
| `domain` | Provider-neutral contracts, state rules, identity, redaction, embedding, chunking, fusion, access constraints, failure classification, service and repository contracts |
| `ports` | Exactly five visible application interfaces |
| `adapters` | PostgreSQL, pgvector retrieval, LocalStack SQS/DLQ, S3-compatible object storage, deterministic model, the resilient model-provider wrapper, logs, traces, and both fault controls |

`src/api/bootstrap.py` and `src/worker/bootstrap.py` compose each process from its settings and
adapters. Process settings live in `src/api/config.py` and `src/worker/config.py`. The worker's
composition is where both fault controls are attached; nothing else in the composition changed.

## The five ports

Find the available interfaces in `src/ports/`. A port describes an application capability; an
adapter provides it using a concrete technology.

| Port | General responsibility |
|---|---|
| `ModelProvider` | Call an AI model service |
| `Retriever` | Look up relevant context or documents |
| `ObjectStore` | Store large binary objects or files |
| `JobQueue` | Publish and consume background work |
| `SecretProvider` | Read API keys and credentials |

LocalStack SQS, with a bound dead-letter queue, still carries `JobQueue`, unchanged from Task 3.3.
The dead-letter depth poller reads the dead-letter queue's own attribute directly, alongside
`JobQueue` rather than through it; see [JobQueue fidelity](docs/fidelity/JobQueue.md).

## Test levels

| Level | Requires Compose | Main question |
|---|---:|---|
| Unit | No | Does one responsibility behave correctly, including failures? |
| Contract | Some | Do interfaces, schemas, paths, and dependency rules stay compatible? |
| Smoke | Yes | Did the complete local platform initialize and become observable? |
| E2E | Yes | Can an external client complete the supplied workflow? |

Contract checks marked `runtime` need the running stack, and checks marked `assessed` read your
work. `poe contract` skips both; `poe fault-checks` runs this Task's own module, whose static
checks need only the committed files and whose two runtime checks need the stack. A fresh Task
3.12 checkout fails the static checks that read your fault choice, your lab file, your evidence,
your recovery record, your second entry, and your notes, and the runtime baseline check, because
the lab run and the answers are this Task's work; the first-entry check and the fault-control
check pass, because the supplied runbook is unchanged and no fault is applied.

## Submission checks

Run `poe verify` locally before opening your student pull request. Public GitHub CI repeats
the student checks, running `poe answers` first so a boundary violation fails fast, then
`poe start`, `poe ingest`, and `poe verify`. The component and signal you recorded and your
recovery record are compared with a protected answer key after you submit on the platform; the
public checks confirm their format, their allowed values, and their agreement with your own lab
file and the running stack. Follow the Task lesson's submission policy: this Task is optional and
gates nothing.

## Task boundary

Task 3.12 asks you to run one catalog fault, correlate its evidence, recover to a proven
baseline, fill the answer sheet, and append a second runbook entry. The only student-editable
paths are:

- `docs/student/runbook.md`, by appending below the supplied first entry
- `submission.yaml`
- `docs/student/faults/<fault_id>-lab.json`, written by `poe fault-lab` and committed unedited

Keep the catalog (`infra/faults/catalog.yaml`), the lab and the baseline check under
`tests/failure/`, both fault controls under `src/adapters/`, the worker composition,
`compose.yaml`, `infra/observability/alerts.yml`, the transport adapters, every test file, and
both workflows exactly as supplied; do not edit any of them to make a different failure happen
or to make a Step pass. Commit the lab file for the one fault you chose, not both. The public
check compares the diff from your merge base against the permitted files and reports any other
change as a boundary violation; the fault checks then compare the lab file's digest with its
content and the runbook's opening bytes with the supplied first entry.

### Student walkthrough

See **Optional Task 12: Second fault variation** in your course platform for the full
walkthrough. In outline: read `docs/student/task-3-12-contract.md`, start the stack, read the
catalog and the existing runbook entry, choose one fault and record why it differs, open a second
terminal with your three queries ready, run `poe fault-lab --fault <id>` and sample the window
yourself, correlate one reading through Jaeger, Prometheus, the worker logs and the queue
samples, fetch every exception id by hand, run `poe baseline-check` and copy its fields, append
the second runbook entry, fill `submission.yaml`, check `git diff --stat` shows only the three
permitted files, run `poe verify`, open your pull request and submit on the platform.

## Operational limits

This local system does not authenticate users, terminate TLS, or manage production secrets.
The Compose PostgreSQL password and the LocalStack access keys are local-only non-secret
credentials. Never place real credentials, personal data, or production records in this
repository.

Alertmanager here is configured with a "default" receiver that has no notification integration:
alerts are queryable through its own API but never sent anywhere real. Never add a webhook, email,
Slack, or paid integration; Sprints 1-4 are emulator-only and never call a hosted endpoint.

Both catalog faults are emulations inside one container: a flag the emulated provider reads, and
a wrapper that makes the worker's own queue client fail. They prove how this platform detects,
diagnoses, recovers from, and verifies each failure; they prove nothing about how a hosted model
provider or managed SQS fails, how often, or what a real network partition looks like. See
[JobQueue fidelity](docs/fidelity/JobQueue.md) for what LocalStack SQS does not prove.

Named volumes preserve local PostgreSQL, Redis, Prometheus, Alertmanager, Grafana, and Jaeger state
across `poe stop`. LocalStack object and queue contents are deliberately not persisted; the
initializer re-uploads the supplied corpus artifacts and re-provisions the queue on every start.
The `poe reset` command deletes the named volumes. This topology makes no backup, replication,
high-availability, disaster-recovery, capacity, latency-SLO, or availability claim beyond the one
alert Task 3.4 configures, the one CI gate Task 3.5 wires to it, and the bounded recoveries the
failure labs demonstrate.

See [JobQueue fidelity](docs/fidelity/JobQueue.md),
[ModelProvider fidelity](docs/fidelity/ModelProvider.md),
[ObjectStore fidelity](docs/fidelity/ObjectStore.md), and
[Retriever fidelity](docs/fidelity/Retriever.md) for the active adapter boundaries. The
[local runtime evidence](docs/fidelity/local-runtime.md) records the current measurement and its
qualification limits.
