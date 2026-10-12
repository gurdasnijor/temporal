# Temporal Matching architecture review

Generated from the local `temporal` and `saas-temporal` checkouts on 2026-10-02. Open the SVGs for zoomable diagrams; PNGs are included for quick preview. Every diagram also has an editable Graphviz `.dot` source.

## Start here

| Question | Diagram |
| --- | --- |
| Where are the code and Go module boundaries? | [Repository layout](repo-layout.svg) |
| Which processes and transports are involved? | [Runtime boundaries](runtime-boundaries.svg) |
| How is a workflow task created and stored? | [Workflow task flow](workflow-task-flow.svg) |
| How does a worker receive a task? | [Worker poll flow](worker-poll-flow.svg) |
| Where does SaaS Matching persist today, and where would Walker connect? | [SaaS Matching storage gap](saas-matching-storage-gap.svg) |
| Which OSS subsystems import one another? | [OSS subsystem imports](oss-subsystem-imports.svg) |
| What does the Matching package directly import? | [Matching direct imports](oss-matching-direct-imports.svg) |
| Which SaaS storage packages import one another? | [SaaS storage imports](saas-storage-imports.svg) |
| What did a real request do on the running Zinnia instance? | [Interactive sequence and waterfall](zinnia-poll-timeline.html), [Mermaid sequence](zinnia-poll-sequence.md), [span tree](zinnia-poll-trace.svg) |
| How can I inspect actual PostgreSQL rows and decode protobuf blobs? | [Database inspection guide](db-inspection/README.md) and [read-only SQL](db-inspection/queries.sql) |
| Which database rows belong to History or Matching, and how are they associated? | [Ownership and relationship map](db-inspection/relationships.md) |

Import arrows mean **compile-time Go package imports**, never network requests. Numbers on aggregate arrows count package-level direct imports. Runtime arrows show a representative workflow task path, not every possible service API or deployment topology. Dashed Walker edges are proposed integration points; they do not run today.

The SaaS graph spans two Go modules: `saas-temporal/go.mod` and `saas-temporal/walker/go.mod`. `walker` is a storage system; moving Matching persistence to it is separate from moving the Matching service process.

## Files worth opening next

- [Matching Fx registrations](matching-fx-registration.md) lists the constructors and hooks from `service/matching/fx.go`. Fx registration is an in-process dependency boundary.
- Existing project diagrams: [high-level architecture](../docs/_assets/temporal-high-level.svg), [Matching context](../docs/_assets/matching-context.svg), and [workflow lifecycle sequences](../docs/architecture/workflow-lifecycle.md).
- [Matching service README](../service/matching/README.md) explains task queue ownership and partition forwarding.

## Evidence for the runtime arrows

| Relationship | Source |
| --- | --- |
| SDK to Frontend gRPC; Frontend, History, Matching responsibilities | `docs/architecture/README.md`; `service/frontend/service.go`; `service/history/service.go`; `service/matching/service.go` |
| Frontend HTTP API and Nexus HTTP handlers | `service/frontend/fx.go` |
| Frontend long poll to Matching | `service/frontend/workflow_handler.go:1072-1128` |
| Matching task add and poll handlers | `service/matching/handler.go:176-286`; `service/matching/matching_engine.go:586-717` |
| Matching task start callback to History | `service/matching/matching_engine.go:3529-3570` |
| Task backlog persistence | `service/matching/task_writer.go:141`; `service/matching/db.go:520-563,700-747` |
| Workflow creation, durable transfer task, async add to Matching | `docs/architecture/workflow-lifecycle.md:15-40` |
| SaaS Matching store selection | `saas-temporal/cds/export/cds/factory.go:418-435` |
| Cassandra Matching store implementation | `saas-temporal/cds/storage/cassandra/multi_cass_store_provider.go:198-215` |
| Walker Matching store provider is unimplemented | `saas-temporal/cds/storage/walkerstores/multi_walker_store_provider.go:181-190` |
| Walker datanode client uses gRPC | `saas-temporal/walker/datanode/client/datanode_client.go:31-45` |

## Rebuild

From the OSS repository root:

```sh
python3 architecture-review/generate.py
```

The script uses only Python's standard library, `go list -json`, and Graphviz `dot`. It enumerated 159 OSS and 9 SaaS packages; see [generation stats](generation-stats.json). Each diagram is provided as SVG, PNG, and DOT.

## Live Zinnia trace

The running Zinnia Temporal server exports OTLP gRPC spans to an OTEL collector, which writes them to ClickHouse. Its deployment configuration is in `BodyIQ/zinnia-apps/deploy/zinnia-apps/compose.yaml` and `observability/otel-collector.yaml`. The authenticated [CH-UI](https://ch-ui.zinnia.page/) exposes the `otel.otel_traces` table for read-only queries.

The [interactive timeline](zinnia-poll-timeline.html) is a 10-span execution from 2026-10-02. It shows Frontend receiving `PollWorkflowTaskQueue`, calling Matching, Matching forwarding the poll to another Matching hop, then calling History for mutable state and workflow history. History records a `persistence.ExecutionStore/ReadHistoryBranch` span. [Span data](zinnia-poll-trace.json) includes parent IDs, timestamps, duration, and status, but no workflow payloads. Re-render it with `python3 architecture-review/render_live_trace.py`.

To locate another recent cross-service trace in CH-UI:

```sql
SELECT TraceId, count() AS spans, groupUniqArray(ServiceName) AS services,
       max(Timestamp) AS latest
FROM otel.otel_traces
WHERE Timestamp >= now() - INTERVAL 30 MINUTE
  AND ServiceName IN ('io.temporal.frontend', 'io.temporal.matching', 'io.temporal.history')
GROUP BY TraceId
HAVING has(services, 'io.temporal.matching')
   AND has(services, 'io.temporal.history')
ORDER BY latest DESC
LIMIT 5;
```

Then inspect one `TraceId` with:

```sql
SELECT Timestamp, ServiceName, SpanName, SpanKind, SpanId, ParentSpanId,
       round(Duration / 1000000, 2) AS duration_ms, StatusCode
FROM otel.otel_traces
WHERE TraceId = '9451a4b0a7d279de16b07f8d07c8b3e5'
ORDER BY Timestamp ASC
LIMIT 100;
```

The Zinnia deployment runs OSS Temporal 1.32.0 with PostgreSQL. This trace is evidence for its live OSS call path, not the SaaS Walker implementation. A workflow history in the Temporal UI is a different record: it shows durable workflow events but not each inter-service RPC or persistence span. The trace starts at the Frontend server span because the external worker was not traced as part of this trace.
