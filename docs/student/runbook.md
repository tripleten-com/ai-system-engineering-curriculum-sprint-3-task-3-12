<!--
Coldline - Task 3.12
Supplied checkpoint: the settled Task 6 recovery runbook, carried into the Task 3.12
checkpoint exactly as Task 3.7 supplied it. In this Task the file is student-editable in
one direction only: append a second entry, for the catalog fault you ran, below the first
entry, and change nothing above it. tests/fixtures/runbook-first-entry.md repeats this
supplied text, and poe fault-runbook-contract requires the file to open with it, byte for
byte (line endings aside), so an edit anywhere in the first entry, this comment included,
fails the check. The blob quoted under Verification shows the shape and the values a
`poe dev-failure-lab` run produces on the supplied stack; treat it as representative, not
as the archived record of one run.
-->
# Recovery runbook — bounded worker outage (Coldline exception pipeline)

Scope: the `coldline-exception-jobs` queue and its consumer, the `worker` service, in the
Compose stack. Trigger: `poe dev-failure-lab`, which stops the worker for ten seconds, submits
five out-of-range readings, and restarts the worker. This runbook is the detection-to-verification
pass for that scenario, written from one run against the live stack.

## Detection

- **Signal.** The main queue's `ApproximateNumberOfMessages` climbed from 0 to 5 while the worker
  was stopped, with `ApproximateNumberOfMessagesNotVisible` at 0 and the dead-letter queue at 0.
  Growing depth with nothing in flight is the signature of an absent consumer. That reading came
  from *outside* the worker — the same host-side `ApproximateNumberOfMessages` query on the queue
  that `poe dev-failure-lab` prints as it runs — which is the only place it was available at all.
- **Where it showed — and where it could not.** No Prometheus series showed this backlog, because
  the only thing that publishes queue depth is the worker that was stopped.
  `coldline_job_queue_stream_length` and `coldline_job_queue_dead_letter_depth` did not go high;
  they stopped, leaving a scrape gap for the whole outage, and the Grafana diagnostics dashboard's
  queue-depth panel held its last value flat while the real depth grew. The Prometheus-side signals
  were therefore the absence itself: that scrape gap, and `up{job="coldline-worker"} == 0` for
  exactly the length of the outage. Looking for a rising depth line here would have found nothing;
  the silence is the first thing to notice.
- **What did not fire.** `ColdlineDeadLetterQueueBacklog` stayed inactive in Alertmanager. It
  watches `coldline_job_queue_dead_letter_depth > 0`, and nothing was dead-lettered: SQS only
  redrives a message after `maxReceiveCount` *actual* receives, and a stopped consumer never
  receives. A silent worker is invisible to that alert by design; the alert covers poison
  messages, not consumer absence.
- **User-visible symptom.** Every submitted reading answered `202 Accepted` and sat at state
  `QUEUED` on `GET /api/v1/exceptions/{id}` for the whole outage. The API was healthy; the
  workflow simply stopped making progress.

## Diagnosis

- **Consumer outage, not dependency outage.** The API kept writing `RECEIVED -> QUEUED` and
  publishing to SQS, so PostgreSQL and LocalStack were both up. `docker compose ps` showed
  `worker` as `exited`. A dependency outage would have shown the reverse: the worker running
  and either crash-looping or leaving messages in flight, and the API failing to persist.
- **Not a poison message.** Zero dead-letter depth and every record still `QUEUED` (never
  `PROCESSING`) ruled out a message the worker kept failing on. A poison message shows as
  `PROCESSING` records, growing `ApproximateReceiveCount`, and eventually dead-letter arrival.
- **Bounded, not growing.** Five readings, no producer still submitting, so the backlog was the
  whole blast radius. Nothing needed to be shed or paused.

## Recovery

- **Action.** Start the consumer: `docker compose start worker` (the lab does this itself;
  by hand it is `poe worker-start`). No message was touched, redriven, or purged.
- **Why it was safe to do without duplicating work.** Each message is the same durable
  exception identity the API persisted as `QUEUED` before publishing; the worker's
  `WorkerApplication.process` moves `QUEUED -> PROCESSING -> COMPLETED` and acknowledges only
  after terminal persistence, and treats a delivery for an already-terminal identity as a safe
  replay. Restarting the consumer therefore cannot summarise a shipment twice, whatever
  redelivery SQS does in the meantime.
- **If messages had reached the dead-letter queue.** Only possible for a message that was
  mid-receive when the container stopped and later expired back onto the queue with its receive
  count spent. Recovery is then the Task 3.3 path: receive from `coldline-exception-jobs-dlq`,
  send the same body to `coldline-exception-jobs`, delete from the DLQ (`poe redrive`, or the
  lab's own defensive redrive). The redriven message carries the same exception identity, so
  the same idempotency argument holds.
- **What I would not do.** Not restart PostgreSQL or LocalStack (they were healthy; a restart
  would lose the non-persisted LocalStack queue contents), and not purge the queue (that turns a
  delayed workflow into a lost one).

## Verification

- **Records.** All five exception ids reached `COMPLETED`; none `FAILED`; each carries a
  summary. Re-fetching them a second time returned identical records.
- **Queue.** `ApproximateNumberOfMessages` and `ApproximateNumberOfMessagesNotVisible` on the
  main queue back to 0; dead-letter depth 0; zero messages redriven.
- **Telemetry.** `up{job="coldline-worker"}` returned to 1 and the scrape gap closed:
  `coldline_job_queue_stream_length` resumed reporting and read 0. The alert stayed inactive
  throughout, which is the correct outcome for this fault.
- **Evidence.** The lab's evidence blob, of this shape and with these values on the supplied
  stack:

```json
{
  "fault": "consumer_outage",
  "target_service": "worker",
  "worker_stopped_seconds": 10.0,
  "exception_ids": ["<five exception ids>"],
  "queue_depth_while_stopped": 5,
  "dead_letter_depth_while_stopped": 0,
  "redriven_messages": 0,
  "states": {"<each exception id>": "COMPLETED"},
  "final_queue_depth": 0,
  "final_dead_letter_depth": 0,
  "recovery_seconds": 8.1,
  "outcome": "recovered"
}
```

- **Exit.** `poe dev-failure-lab` exited 0. The incident is over when the records are terminal,
  both depths are zero, and the depth gauge is reporting again — not when the worker container
  merely shows `running`.

# Recovery runbook — bounded model provider outage (catalog fault `provider_outage`)

Scope: the model provider behind the `ModelProvider` port — the deterministic emulator the
`worker` service calls inside its own container — in the Compose stack. The `worker` process, the
API, PostgreSQL and LocalStack SQS all stay healthy; only the summarisation call fails. Trigger:
`poe fault-lab --fault provider_outage`, which sets the supplied provider fault flag inside the
worker container for the catalog's 20 s, submits five out-of-range readings one a second while it
is set, lifts the flag, and waits for recovery. This runbook is the detection-to-verification pass
for that scenario, written from one run against the live stack: window `2026-09-30T02:41:51.412Z`
to `2026-09-30T02:42:14.704Z`, recovered at `02:42:32.938Z`.

## Detection

- **Signal, and how long it took.** The first evidence anywhere was a worker log line, 0.16 s
  after the fault was applied: `processed exception_id=exc-d50f684e-abe9-5ad8-84fa-db8373ee4414
  disposition=RETRY` at `2026-09-30T02:41:51.571214+00:00`, with
  `trace_id=f59f9727dfdb5badf54fa94578344f05`. `disposition=RETRY` means the worker handed the
  delivery back instead of acknowledging it. Read it with
  `docker compose --profile observability --profile localstack logs worker --since <window start>`.
  One caution: it is logged at **INFO**, not WARNING or ERROR, so an on-call engineer who filters
  the worker log by level sees nothing. Filter by `disposition=` instead.
- **Where it showed second.** `coldline_job_queue_pending_messages`, the worker's in-flight gauge,
  left 0 at the first scrape after the failures and read 2 at `02:41:55Z`, 4 at `02:42:00Z` and 5
  from `02:42:05Z` to `02:42:20Z` — about four seconds behind the log line, and only because the
  worker was still up to publish it.
- **What did not show it — and why.** The first entry's detection query, the host-side
  `ApproximateNumberOfMessages` on `coldline-exception-jobs`, stayed at **0** for the entire
  window, and so did `coldline_job_queue_stream_length`. There was no waiting backlog: the worker
  received every message, so the five readings were *in flight*
  (`ApproximateNumberOfMessagesNotVisible` 0 → 5), invisible to the depth query. Reading the first
  entry's Detection literally would have produced "the queue is empty, nothing is wrong".
  `up{job="coldline-worker"}` stayed 1 at every scrape with no gap, so the first entry's second
  signal was absent too. `ColdlineDeadLetterQueueBacklog` stayed inactive — Alertmanager listed no
  alerts at all — because `coldline_job_queue_dead_letter_depth` never left 0: two deliveries per
  message is well inside the redrive policy. As in the first entry, the alert covers poison
  messages, not this.
- **User-visible symptom.** Every reading answered `202 Accepted` and then sat at state `QUEUED`
  on `GET /api/v1/exceptions/{id}` for roughly thirty seconds — *not* `PROCESSING`. The worker
  moves the record back out of `PROCESSING` when it returns the delivery, so a failing dependency
  looks exactly like a slow queue from the API side. A clinic waiting for a summary sees a delay,
  the same symptom the first entry describes, from a completely different cause.

## Diagnosis

- **Dependency outage, not consumer outage.** The trace decides it. Trace
  `f59f9727dfdb5badf54fa94578344f05` (Jaeger, service `coldline-worker`, tag
  `coldline.exception_id=exc-d50f684e-abe9-5ad8-84fa-db8373ee4414`) holds a
  `coldline.process_exception` span with `coldline.delivery_count=1` at `02:41:51.449Z` — so the
  worker *did* receive the message, which the first entry's stopped consumer never could. Inside
  it, two `model_provider.summarize` spans, both `otel.status_code=ERROR` with
  `coldline.provider_fault=provider_outage` and a `RetryableProviderError` event, 8.1 ms then
  0.7 ms: the resilient wrapper spent its whole attempt budget in a tenth of a second. The
  `postgres.exceptions.*` and `job_queue.publish` spans in the same trace are clean. The failing
  component is the model provider; nothing else is broken.
- **Not the other catalog fault.** `queue_unavailable` would break the worker's own SQS client, so
  there would be **no** `coldline.process_exception` span and no `processed exception_id=...`
  log line per reading at all, and the readings would pile up as *visible* backlog
  (`ApproximateNumberOfMessages` rising) with nothing in flight. Here the opposite held:
  `queue_depth=0` with `in_flight=5`, one processed line per reading, and a span that names the
  provider.
- **The joins.** Metric `coldline_job_queue_pending_messages` 0 → 5 → 0 over
  `02:41:50Z`–`02:42:35Z`; log line `02:41:51.571214+00:00 processed
  exception_id=exc-d50f684e-abe9-5ad8-84fa-db8373ee4414 disposition=RETRY`; queue sample
  `2026-09-30T02:42:00.341+00:00 queue_depth=0 in_flight=5 dead_letter_depth=0`; trace
  `f59f9727dfdb5badf54fa94578344f05`. The `trace_id` on the log line is the trace id, and
  `coldline.exception_id` on the span is the id in the log message and in the lab's `readings`.
- **Bounded, not growing.** Five readings, one producer that stopped at the end of the window, the
  in-flight count capped at 5, the dead-letter queue at 0 throughout. The blast radius was the
  five summaries, delayed by one visibility timeout each; nothing needed shedding or pausing. Had
  the provider stayed down past the redrive policy's receive budget, the messages *would* have
  dead-lettered and `ColdlineDeadLetterQueueBacklog` would finally have fired — that is the signal
  to watch for if this fault lasts.

## Recovery

- **What lifted the fault.** The lab cleared the provider flag inside the worker container at
  `02:42:14.704Z` (`docker compose exec worker python -m adapters.model.faults lift`, run by the
  lab, never by hand in this Task). Nothing was restarted, and no message was touched. In a real
  provider outage the equivalent is the provider recovering or a failover; there is no local
  action that fixes it, which is the point — this fault is waited out, not repaired.
- **Then nothing, deliberately.** SQS returns each unacknowledged message after the queue's 30 s
  visibility timeout, and the worker summarises it on the second delivery. The whole recovery is
  one redelivery cycle: 18.2 s after the lift, every record was terminal.
- **The manual verification pass, in order.** For every exception id in
  `docs/student/faults/provider_outage-lab.json`:

  1. `curl "http://localhost:${COLDLINE_API_HOST_PORT:-8000}/api/v1/exceptions/<id>"` — read
     `state` and, if `FAILED`, `failure_reason`.
  2. Both queue depths: `ApproximateNumberOfMessages` and `ApproximateNumberOfMessagesNotVisible`
     on `coldline-exception-jobs`, and `ApproximateNumberOfMessages` on
     `coldline-exception-jobs-dlq`.
  3. Only if the dead-letter depth is above 0: `./.tools/bin/uv run --frozen poe redrive`, then
     repeat 1 and 2. **On this run the dead-letter depth was 0, so this step was skipped and
     `redriven_count` is 0.** Running a redrive against an empty dead-letter queue proves nothing
     and is not a step to perform "just in case".
  4. `curl "http://localhost:${COLDLINE_ALERTMANAGER_HOST_PORT:-9093}/api/v2/alerts"` — confirm
     `ColdlineDeadLetterQueueBacklog` is not active.
  5. `./.tools/bin/uv run --frozen poe baseline-check`.

- **Why the actions are safe to repeat.** Steps 1, 2, 4 and 5 are reads. A redrive is safe for the
  same reason the first entry gives: the redriven message carries the same durable exception
  identity, and the worker treats a delivery for an already-terminal record as a safe replay, so
  no shipment is summarised twice however many times the message is delivered.
- **What I would not do.** Not restart the `worker` container: it was healthy, and a restart drops
  its in-flight receipt handles, so every message would have to wait out another full visibility
  timeout before anyone could work on it — it *lengthens* the incident. Not restart PostgreSQL or
  LocalStack (both healthy; restarting LocalStack loses the non-persisted queue contents). Not
  purge the queue. Not redrive an empty dead-letter queue.

## Verification

- **Records.** All five exception ids fetched by hand from
  `GET /api/v1/exceptions/{id}`: 5 `COMPLETED`, 0 `FAILED`, no `failure_reason`, each carrying a
  summary. Terminal timestamps `02:42:22.822Z` through `02:42:32.930Z`, roughly 31 s after each
  reading was submitted — one visibility timeout, as expected.
- **Queue.** `coldline-exception-jobs`: `ApproximateNumberOfMessages` 0 and
  `ApproximateNumberOfMessagesNotVisible` 0. `coldline-exception-jobs-dlq`: 0. Zero messages
  redriven.
- **Alert.** Alertmanager listed **no** alerts at all, so `ColdlineDeadLetterQueueBacklog` is
  `absent` — inactive throughout, which is the correct outcome for a fault that never dead-lettered
  anything.
- **Telemetry.** `coldline_job_queue_pending_messages` back to 0 from `02:42:35Z`;
  `coldline_job_queue_stream_length` and `coldline_job_queue_dead_letter_depth` flat 0 the whole
  time; `up{job="coldline-worker"}` 1 at every scrape, no gap to close.
- **Baseline.** The `baseline` block `poe fault-lab` wrote:

```json
{
  "all_readings_terminal": true,
  "dead_letter_depth": 0,
  "queue_depth": 0,
  "readiness_status": 200
}
```

  `poe baseline-check`, run separately afterwards, exited 0 and printed exactly the same four
  fields, so the lab's own measurement and the independent check agree.

- **Exit.** `poe fault-lab --fault provider_outage` exited 0 with `returned_to_baseline: true`.
  The incident is over when every record is terminal **and** carries a summary, both depths are
  zero, and the alert is not active — not when the provider answers again. A `FAILED` record would
  be terminal too, so baseline alone never proves the summaries arrived; on this run none failed.
- **What this run does not prove.** This fault is a flag file the emulated provider reads inside
  one container. It shows how *this* platform detects, diagnoses, recovers from and verifies a
  failing model provider, and that the recovery is one visibility timeout long. It says nothing
  about how a hosted provider fails, how often, how long its outages last, or what a real network
  partition does.
