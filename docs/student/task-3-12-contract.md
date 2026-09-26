# Task 3.12 — Second fault variation contract

Your repository is the finished Project 3 system, and its runbook already covers one failure:
the bounded worker outage Task 3.6's failure lab produces. This Task tests whether that runbook
is a method or a memory. You pick one fault from a supplied catalog, run it against your stack
for its bounded window with the supplied lab, correlate what the traces, metrics, logs and
queues showed for one reading, recover and prove the platform is back at baseline, and append a
second detection-to-verification entry to the runbook, leaving the first entry as it is. You
write no application code, and you never edit the catalog, the lab, the fault controls, or the
lab file.

## What is assessed, and by whom

| Assessed | By |
|---|---|
| The pull request changes only `docs/student/runbook.md`, `submission.yaml`, and `docs/student/faults/<fault_id>-lab.json` | Automated, in this repository (`poe answers`, and `poe verify` repeats it) |
| The answer sheet has the published shape and every enumerated field holds an allowed value | Automated (same command) |
| `answers.fault_id` is one of the two catalog ids | Automated, in this repository (`poe fault-checks`) |
| The lab file for that fault exists, is as `poe fault-lab` wrote it, and reports `returned_to_baseline: true` | Automated (same command) |
| `answers.evidence` covers the four kinds and cites trace ids from your own lab file | Automated (same command) |
| `answers.recovery` holds an allowed outcome whose counts cover the lab file's readings | Automated (same command) |
| `answers.recovery.baseline` matches what `poe baseline-check` prints, and that check exits 0 | Automated, in this repository, against the running stack |
| The first runbook entry is unchanged and a second entry names your fault with its four sections | Automated (same command) |
| Your component, your detection signal, and your recovery record | Protected automated check, after you submit on the platform |
| Your second runbook entry, your notes, and your answer to Elena | Your instructor, if the Add-On evidence is referenced at the Project Defense |

## The supplied pieces

| Supplied | Where | What it does |
|---|---|---|
| The fault catalog | `infra/faults/catalog.yaml` | Exactly two faults, each with `id`, one line saying what it breaks, and `duration_seconds`: `provider_outage` and `queue_unavailable` |
| The provider fault control | `src/adapters/model/faults.py` | A flag file inside the worker container that the model provider emulator reads on every call; while `provider_outage` is set, every summary attempt fails as retryable |
| The queue fault control | `src/adapters/queue/faults.py` | A flag file inside the worker container that a wrapper around the worker's queue client reads before every call; while `queue_unavailable` is set, every call fails as the endpoint does when it is unreachable |
| The fault lab | `tests/failure/fault_lab.py`, `poe fault-lab --fault <id>` | Refuses an id not in the catalog, applies the fault for its window while submitting five readings, samples the queues, the readings and the alert, lifts the fault, waits for recovery, samples traces from Jaeger, and writes `docs/student/faults/<id>-lab.json` with a generator marker and a content digest |
| The baseline check | `tests/failure/baseline_check.py`, `poe baseline-check` | Measures the four baseline fields on its own, prints them as one JSON object, and exits 0 only at baseline |
| The supplied first entry | `docs/student/runbook.md`, repeated in `tests/fixtures/runbook-first-entry.md` | Task 3.6's settled runbook entry; the check requires the runbook to open with it, byte for byte |

## The five Steps

### Step 1 — Choose the fault and say what makes it different

Start the stack, read `infra/faults/catalog.yaml` and the existing entry in
`docs/student/runbook.md`, and choose one catalog id. Record it in `answers.fault_id` exactly as
written, and write `answers.why_different` before running anything: which component your fault
takes away and which part of the existing entry you expect not to transfer.

### Step 2 — Run the fault lab and watch the window

With three queries ready in a second terminal (both queue depths, the
`coldline_job_queue_dead_letter_depth` and `up{job="coldline-worker"}` series, and the alert
list), run `poe fault-lab --fault <id>`. Run your queries at least twice while the fault is
active and note the time of each. When the lab finishes, read
`docs/student/faults/<id>-lab.json` and do not edit it.

### Step 3 — Correlate the trace, metric, log and queue evidence

For at least one reading the lab submitted, find its trace in Jaeger, the metric series that
changed during the window, the worker or API log line carrying its id, and the queue sample
covering it. Record each under `answers.evidence` by the id, query, or line that lets someone
else find it, then `answers.first_affected_component`, `answers.detection_signal`, and
`answers.detection_signal_note`.

### Step 4 — Recover, verify by hand, and prove baseline

Fetch every exception id in your lab file, count the `COMPLETED` and `FAILED` records and read
each failure reason, query both queue depths, redrive with `poe redrive` if the dead-letter
queue is not at zero, read the alert list, and run `poe baseline-check`. Record it all under
`answers.recovery`, copying the baseline fields from the check's output.

### Step 5 — Write the second runbook entry

Append a second top-level entry to `docs/student/runbook.md` naming the fault and its catalog id,
with the sections Detection, Diagnosis, Recovery and Verification, and leave the first entry
exactly as it was. Write `answers.notes`, then run `poe fault-runbook-contract`.

## Commands

```shell
poe fault-lab --fault <id>   # run one catalog fault; writes docs/student/faults/<id>-lab.json
poe baseline-check           # prove baseline on its own; prints the four baseline fields
poe answers                  # the static half: answer format and the permitted-path boundary
poe fault-checks             # the assessed checks over the lab file, the runbook, and the answers
poe fault-runbook-contract   # both halves together; the check poe verify runs for this Task
poe verify                   # the full public path
```

Start the stack per `README.md` first. `poe fault-lab` refuses an id that is not in the
catalog, refuses a stack whose `/health/ready` is not 200, lifts any fault an interrupted run
left behind, and lifts the fault it applied in a `finally` block. It takes about a minute for
either fault: the window is the catalog's `duration_seconds`, and the run then waits for every
reading to settle and for Jaeger to have exported the sampled traces. `poe baseline-check` reads
the exception ids from every lab file under `docs/student/faults/`, samples the platform once a
second for a short settle window, prints the last sample, and exits 0 only when it is baseline.
Keep any host-port override in place for every command.

## What the lab file reports

Every field below is written by `poe fault-lab`, and the check reads it as written:

| Field | Meaning |
|---|---|
| `fault`, `duration_seconds` | The catalog id that ran and its window |
| `timeline` | When the fault was applied and lifted, the window's length, and when the platform recovered |
| `readings` | Each submitted reading: its exception id, the state its record showed while the fault was active, its terminal state, its failure reason if any, and when it became terminal |
| `queue_samples` | Both depths and the main queue's in-flight count, sampled every two seconds inside the window (`phase: window`) and during recovery (`phase: recovery`) |
| `trace_ids`, `traces` | The 32-character Jaeger trace ids the lab sampled, one per reading it could find, with the exception id and link for each |
| `alert` | What Alertmanager listed for `ColdlineDeadLetterQueueBacklog` inside the window and after recovery: its state, or `absent` |
| `redriven_count` | How many dead-lettered messages the lab moved back during recovery |
| `baseline` | The four baseline fields as the lab measured them at the end |
| `returned_to_baseline` | Whether every reading is terminal, both queues are at zero, and readiness is 200 |
| `generator`, `digest` | The generator marker and a SHA-256 content digest over the rest of the file |

## What the checks verify

Each row of the lesson's Check-list maps to one check:

| Check-list row | Check | What it looks at |
|---|---|---|
| `answers.fault_id` is one of the two ids in `infra/faults/catalog.yaml` | `test_fault_id_is_one_of_the_catalog_ids` (and the schema) | The recorded id equals one catalog id, character for character |
| `answers.why_different` is non-empty and at most 400 characters | `test_why_different_names_a_difference_within_its_limit` (and the schema) | Present and within the limit; what it says is for the defense |
| `docs/student/faults/<fault_id>-lab.json` exists, is unedited, and reports `returned_to_baseline: true` | `test_lab_file_for_the_chosen_fault_is_unedited_and_returned_to_baseline` | The file parses, carries the generator marker, names your fault, lists readings with terminal states, at least one depth sample inside the window, at least one trace id, the alert and baseline blocks, reports `returned_to_baseline: true`, and its digest recomputes over its content; no lab file for the other fault is committed |
| `answers.evidence` has at least one entry under each kind, each with a non-empty `reference` and `observation`, and every `trace` reference appears in the lab file's `trace_ids` | `test_evidence_covers_the_four_kinds_and_cites_the_lab_files_trace_ids` (and the schema) | The four lists, their entries, and each trace reference against your lab file |
| `answers.first_affected_component` and `answers.detection_signal` use their allowed values, and `answers.detection_signal_note` is at most 300 characters | `test_first_affected_component_and_detection_signal_use_allowed_values` (and the schema) | The two enumerations and the note's limit; the values themselves are compared with the protected answer key after you submit |
| `answers.recovery.outcome` is allowed, and `completed_count` plus `failed_count` equals the number of readings in the lab file | `test_recovery_outcome_is_allowed_and_the_counts_cover_the_lab_files_readings` (and the schema) | The outcome, the two counts against your lab file's readings, `recovered` only with a zero `failed_count`, the failure reasons list, the redriven count, and the alert state |
| `answers.recovery.baseline` fields match the output of `poe baseline-check`, and `poe baseline-check` exits 0 | `test_recorded_baseline_matches_a_passing_baseline_check` | Runs the baseline check exactly as `poe` does against the running stack, requires exit 0, and compares its four printed fields with the four you recorded |
| The first entry is unchanged | `test_first_runbook_entry_is_unchanged` | `docs/student/runbook.md` opens with `tests/fixtures/runbook-first-entry.md`, byte for byte, line endings aside |
| ... and a second entry for `answers.fault_id` has Detection, Diagnosis, Recovery and Verification | `test_second_runbook_entry_names_the_fault_with_its_four_sections` | The second top-level heading names your catalog id, and the four level-two headings follow it once each, in order, each with a line of its own; lines inside fenced code blocks are never headings |
| `answers.notes` is non-empty and at most 600 characters | `test_notes_answers_elena_within_its_limit` (and the schema) | Present and within the limit; what it says is for the defense |
| The pull request modifies only the three permitted files | `tests/contract/submission_validation.py` (`poe answers`) and `test_submission_change_stays_within_the_permitted_diff` | The diff from the merge base with `main` against the allowlist, with no directory prefix exempted |

One more check in the same module is marked `runtime` and assesses nothing of yours:
`test_supplied_fault_controls_report_no_active_fault_in_the_worker` asks both fault controls,
inside the worker container, which fault is active and expects `none`, so a fault left behind by
an interrupted run is named before the smoke and end-to-end checks meet it. `poe contract` skips
this whole module because it is marked `assessed`; `poe fault-checks`,
`poe fault-runbook-contract`, and `poe verify` run it. A fresh checkout fails every check that
reads your fault choice, your lab file, your evidence, your recovery record, your second entry,
or your notes, and the baseline comparison, because the lab run and the answers are this Task's
work; the first-entry check and the fault-control check pass on it.

## Student-editable paths

- `docs/student/runbook.md`, by appending below the supplied first entry
- `submission.yaml`
- `docs/student/faults/<fault_id>-lab.json`, written by `poe fault-lab` only

That is the whole list. The catalog, the lab, the baseline check, both fault controls, the worker
composition, `compose.yaml`, the alert rule, the transport adapters, every test, and both
workflows stay as supplied. A lab file you edit by hand fails the digest check; a result you
disagree with is a reason to rerun, never to retype. Commit the lab file for the one fault you
chose, not both. Before you push, run `git status` and `git diff --stat` against your merge base:
if anything besides the three files changed, the public check reports the boundary violation
rather than your work.

## What this local run does not prove

Both catalog faults are emulations inside one container: a flag the emulated provider reads, and
a wrapper that makes the worker's own queue client fail. Your run proves how this platform
detects, diagnoses, recovers from, and verifies each of them, and how long a person watching
would have taken to notice. It proves nothing about how a hosted model provider or managed SQS
fails, how often, or what a real network partition does to a consumer. Say so in your second
entry and in `answers.notes`.
