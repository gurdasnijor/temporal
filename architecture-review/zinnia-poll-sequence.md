# Zinnia poll: observed activity sequence

Trace `9451a4b0a7d279de16b07f8d07c8b3e5`, captured 2026-10-02. The service call sequence below is derived from the [10 recorded spans](zinnia-poll-trace.json). Matching hop 1 and hop 2 are RPC hops; the spans alone do not establish whether they ran on distinct hosts.

```mermaid
sequenceDiagram
    participant F as Frontend
    participant M1 as Matching hop 1
    participant M2 as Matching hop 2
    participant H as History
    participant P as Persistence interface
    Note over F: Inbound PollWorkflowTaskQueue<br/>external caller span absent
    F->>M1: PollWorkflowTaskQueue (+1 ms)
    M1->>M2: PollWorkflowTaskQueue (+3 ms)
    Note over F,M2: Long poll active for about 21.4 s
    M2->>H: GetMutableState (+21,407 ms; 3.11 ms)
    H-->>M2: Return
    M2->>H: GetWorkflowExecutionHistory (+21,411 ms; 16.84 ms)
    H->>P: ReadHistoryBranch (+21,412 ms; 3.75 ms)
    P-->>H: Return
    H-->>M2: Return
```

The [interactive timeline](zinnia-poll-timeline.html) shows both this sequence and a time-scaled span waterfall. The persistence span ends at Temporal's `ExecutionStore` boundary; this trace does not show the PostgreSQL driver call.
