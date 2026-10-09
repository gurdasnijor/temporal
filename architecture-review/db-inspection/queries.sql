-- Run one SELECT at a time in TablePlus. These queries do not modify the database.

-- 1. Browse stored history batches. The screenshot shows shard 2; change it as needed.
-- node_id is the first event ID in a batch. PostgreSQL stores txn_id negated.
SELECT shard_id,
       encode(tree_id, 'hex') AS tree_id_hex,
       encode(branch_id, 'hex') AS branch_id_hex,
       node_id,
       -txn_id AS logical_txn_id,
       prev_txn_id,
       data_encoding,
       octet_length(data) AS data_bytes
FROM history_node
WHERE shard_id = 2
ORDER BY node_id DESC
LIMIT 25;

-- 2. Export one complete history blob as text. Copy history_hex into the decoder.
-- Add tree_id/branch_id/node_id predicates from query 1 to target a specific batch.
SELECT shard_id,
       encode(tree_id, 'hex') AS tree_id_hex,
       encode(branch_id, 'hex') AS branch_id_hex,
       node_id,
       encode(data, 'hex') AS history_hex
FROM history_node
WHERE shard_id = 2
ORDER BY node_id DESC
LIMIT 1;

-- 3. Find workflow IDs and their current run IDs.
SELECT n.name AS namespace,
       c.workflow_id,
       encode(c.run_id, 'hex') AS run_id_hex,
       c.shard_id,
       c.state,
       c.status,
       c.start_time
FROM current_executions AS c
JOIN namespaces AS n ON n.id = c.namespace_id
ORDER BY c.start_time DESC NULLS LAST
LIMIT 25;

-- 4. Select a particular workflow's mutable state blobs.
-- Replace the workflow ID before running; add a run_id filter for a specific run.
SELECT n.name AS namespace,
       e.workflow_id,
       encode(e.run_id, 'hex') AS run_id_hex,
       e.shard_id,
       e.next_event_id,
       e.data_encoding,
       e.state_encoding,
       encode(e.data, 'hex') AS execution_info_hex,
       encode(e.state, 'hex') AS execution_state_hex
FROM executions AS e
JOIN namespaces AS n ON n.id = e.namespace_id
WHERE e.workflow_id = '<workflow-id>'
LIMIT 10;

-- 5. Browse persisted Matching task queue metadata, both legacy and v2 tables.
SELECT 'task_queues' AS source,
       range_hash,
       encode(task_queue_id, 'hex') AS task_queue_id_hex,
       range_id,
       data_encoding,
       octet_length(data) AS data_bytes,
       encode(data, 'hex') AS task_queue_hex
FROM task_queues
ORDER BY range_hash
LIMIT 10;

SELECT 'task_queues_v2' AS source,
       range_hash,
       encode(task_queue_id, 'hex') AS task_queue_id_hex,
       range_id,
       data_encoding,
       octet_length(data) AS data_bytes,
       encode(data, 'hex') AS task_queue_hex
FROM task_queues_v2
ORDER BY range_hash
LIMIT 10;

-- 6. Browse persisted Matching backlog. Tasks can be absent after delivery.
SELECT 'tasks_v2' AS source,
       range_hash,
       encode(task_queue_id, 'hex') AS task_queue_id_hex,
       pass,
       task_id,
       data_encoding,
       encode(data, 'hex') AS task_hex
FROM tasks_v2
ORDER BY range_hash, pass, task_id
LIMIT 10;

SELECT 'tasks' AS source,
       range_hash,
       encode(task_queue_id, 'hex') AS task_queue_id_hex,
       task_id,
       data_encoding,
       encode(data, 'hex') AS task_hex
FROM tasks
ORDER BY range_hash, task_id
LIMIT 10;
