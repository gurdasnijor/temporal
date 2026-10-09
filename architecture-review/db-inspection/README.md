# Inspect Temporal's PostgreSQL rows

The Zinnia `temporal` database now has eleven live, read-only views in the `temporal_onboarding` schema. In TablePlus, change the schema selector at the bottom left from `public` to `temporal_onboarding`, then open a view under **Views**. Refresh the sidebar if the schema is not listed yet. **Open `workflow_resource_map` first.** The views are defined in [install_views.sql](install_views.sql).

To understand which service owns each row and how tables relate, see the [ownership and relationship map](relationships.md). It also explains the primary keys and the absence of foreign keys.

| View | What to look for |
| --- | --- |
| `workflow_resource_map` | One grid with a current run, History branch, stored batch count, and Matching task rows |
| `current_workflows` | Namespace, workflow ID, current run, readable state/status, and next event ID |
| `execution_runs` | Mutable-state rows and whether each is the current run |
| `history_branch_owners` | Decoded namespace, workflow ID, and run ID for each history branch |
| `history_branch_batches` | Stored event batches labeled with their branch's workflow and run ID |
| `history_branches` | The branch keys used to organize history |
| `history_batches` | Each stored event batch, first event ID, transaction ID, and protobuf size |
| `matching_queues` | Queue name, namespace, workflow/activity/Nexus type, range ID, and v1/v2 storage |
| `matching_task_workflows` | Queue name plus the workflow and run IDs carried by each persisted task |
| `matching_backlog` | Persisted tasks, task IDs, and v2 fair-scheduling pass |
| `matching_user_data` | Versioned task-queue user data; this can be empty |

In `workflow_resource_map`, each row connects a run to a branch and counts the event batches physically stored there. `stored_matching_task_rows` shows rows currently in Matching's task tables, and `stored_task_queue_names` shows their queue names. A task row can remain for a completed workflow, so this count is **not** a count of runnable work. A queue can also have no stored task rows after delivery.

For detail, filter `history_branch_batches` by the map's `workflow_id` to see stored event batches. To follow a queue across runs, open `matching_queues`, then filter `matching_task_workflows` by `task_queue_name`. `history_branch_batches` shows rows physically stored on each branch; a forked run can also read events from ancestor branches.

These views show **current rows**, without a materialized-view refresh or copied data. `history_batches` corresponds to the `history_node` table in the screenshot. As a quick SQL alternative to browsing in TablePlus:

```sql
SELECT * FROM temporal_onboarding.workflow_resource_map
ORDER BY stored_matching_task_rows DESC, stored_batches_on_branch DESC LIMIT 30;

SELECT * FROM temporal_onboarding.matching_queues
ORDER BY namespace, task_queue_name LIMIT 30;

SELECT * FROM temporal_onboarding.current_workflows
ORDER BY start_time DESC NULLS LAST LIMIT 30;

SELECT * FROM temporal_onboarding.history_batches
WHERE shard_id = 2 ORDER BY first_event_id DESC LIMIT 30;

SELECT * FROM temporal_onboarding.history_branch_batches
WHERE workflow_id = '<workflow-id>' ORDER BY first_event_id LIMIT 30;

SELECT * FROM temporal_onboarding.matching_task_workflows
WHERE task_queue_name = '<task-queue-name>' LIMIT 30;
```

A queue can appear in both v1 and v2 metadata while Temporal transitions between task storage formats. On installation, this instance had 112 current workflows, 169 Matching queue metadata rows, 10 persisted Matching backlog rows, and 38,761 history batches. Those counts will change as the system runs. I also decoded one live `history_node` row: it contained events 295 (`WORKFLOW_TASK_COMPLETED`) and 296 (`WORKFLOW_EXECUTION_COMPLETED`).

The database stores indexing columns as ordinary SQL values and most Temporal objects as protobuf bytes. A small SQL function extracts the identity fields used by the new relationship views. It does not decode complete event messages or application payloads. Use [queries.sql](queries.sql) to export a particular blob, then decode that blob locally.

## A first history row

1. In TablePlus, open a SQL tab and run query 1 in [queries.sql](queries.sql). Its `tree_id_hex` and `branch_id_hex` columns make the binary IDs readable. `data_bytes` shows the batch size.
2. Run query 2 and copy **only the `history_hex` cell**, including all its text. For a row selected in query 1, add predicates such as `AND tree_id = decode('...', 'hex')`, `AND branch_id = decode('...', 'hex')`, and `AND node_id = ...` before `ORDER BY`.
3. From this repository's root, decode the copied cell:

   ```sh
   pbpaste | go run ./architecture-review/db-inspection/decode_db_blob.go -type history
   ```

   You can also save the copied text to a file and pass `-input /path/to/blob.hex`. PostgreSQL's `\x` prefix and whitespace are accepted. For base64 exports, pass `-format base64`.

A `history_node` row contains a serialized `go.temporal.io/api/history/v1.History`: an **array of history events**, not necessarily one event. `node_id` is the first event ID in that batch. The PostgreSQL plugin negates `txn_id` on write, which accounts for the negative values in the screenshot. The `data_encoding` column should read `Proto3` for this decoder.

## Start with a workflow or a Matching task queue

Query 3 finds a workflow ID in `current_executions`. Query 4 exports that run's `executions.data` and `executions.state` cells. Decode them separately:

```sh
pbpaste | go run ./architecture-review/db-inspection/decode_db_blob.go -type execution-info
pbpaste | go run ./architecture-review/db-inspection/decode_db_blob.go -type execution-state
```

Copy the appropriate cell before each command. The decoded execution info contains version histories and branch tokens that identify the history branch. `history_node` does not contain a workflow ID, so browsing random history rows is a poor way to locate a known workflow. The [Temporal UI](https://temporal.zinnia.page/) provides the logical event timeline; these queries show the physical rows.

Queries 5 and 6 show Matching metadata and task backlog in both legacy and v2 tables. A queue may have metadata with no persisted tasks when workers consume tasks promptly. Decode the `task_queue_hex` or `task_hex` cell with `-type task-queue` or `-type task`. For versioning and user data, `task_queue_user_data.data` uses `-type task-queue-user-data`.

| SQL column | Decoder type | Protobuf message |
| --- | --- | --- |
| `history_node.data` | `history` | `History` |
| `history_tree.data` | `history-tree` | `HistoryTreeInfo` |
| `executions.data` | `execution-info` | `WorkflowExecutionInfo` |
| `executions.state`, `current_executions.data` | `execution-state` | `WorkflowExecutionState` |
| `task_queues.data`, `task_queues_v2.data` | `task-queue` | `TaskQueueInfo` |
| `tasks.data`, `tasks_v2.data` | `task` | `AllocatedTaskInfo` |
| `task_queue_user_data.data` | `task-queue-user-data` | `TaskQueueUserData` |
| `namespaces.data` | `namespace` | `NamespaceDetail` |

Decoded JSON may still contain base64 payload bytes. Their contents depend on the workflow's SDK data converter and payload codec. A protobuf decoder alone cannot interpret an arbitrary application payload.

The mappings come from [the PostgreSQL schema](../../schema/postgresql/v12/temporal/schema.sql), [the persistence serializer](../../common/persistence/serialization/serializer.go), [history manager](../../common/persistence/history_manager.go), and [PostgreSQL history store](../../common/persistence/sql/sqlplugin/postgresql/events.go).

The views were installed on the Zinnia instance on 2026-10-02. To recreate them there, run [install_views.sql](install_views.sql) against its `temporal` core database. The script creates only the `temporal_onboarding` schema, its views, and a small protobuf field reader, then grants the existing `temporal` role permission to read them.
