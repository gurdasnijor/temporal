-- Install in the Temporal core PostgreSQL database, not temporal_visibility.
-- These ordinary views read live data; they do not copy rows or need refreshing.
BEGIN;

CREATE SCHEMA IF NOT EXISTS temporal_onboarding;

-- Read one protobuf bytes/string field without requiring a server extension.
CREATE OR REPLACE FUNCTION temporal_onboarding.protobuf_bytes_field(payload bytea, field_number integer)
RETURNS bytea
LANGUAGE plpgsql
IMMUTABLE STRICT PARALLEL SAFE
AS $$
DECLARE
  cursor_pos integer := 0;
  payload_bytes integer := octet_length(payload);
  key_value bigint;
  field_length bigint;
  field_index bigint;
  wire_type integer;
  shift_bits integer;
  byte_value integer;
BEGIN
  IF field_number < 1 THEN
    RETURN NULL;
  END IF;

  WHILE cursor_pos < payload_bytes LOOP
    key_value := 0;
    shift_bits := 0;
    LOOP
      IF cursor_pos >= payload_bytes OR shift_bits > 63 THEN
        RETURN NULL;
      END IF;
      byte_value := get_byte(payload, cursor_pos);
      cursor_pos := cursor_pos + 1;
      key_value := key_value | ((byte_value & 127)::bigint << shift_bits);
      EXIT WHEN byte_value < 128;
      shift_bits := shift_bits + 7;
    END LOOP;

    field_index := key_value >> 3;
    wire_type := (key_value & 7)::integer;
    CASE wire_type
      WHEN 0 THEN
        LOOP
          IF cursor_pos >= payload_bytes THEN
            RETURN NULL;
          END IF;
          byte_value := get_byte(payload, cursor_pos);
          cursor_pos := cursor_pos + 1;
          EXIT WHEN byte_value < 128;
        END LOOP;
      WHEN 1 THEN
        cursor_pos := cursor_pos + 8;
      WHEN 2 THEN
        field_length := 0;
        shift_bits := 0;
        LOOP
          IF cursor_pos >= payload_bytes OR shift_bits > 63 THEN
            RETURN NULL;
          END IF;
          byte_value := get_byte(payload, cursor_pos);
          cursor_pos := cursor_pos + 1;
          field_length := field_length | ((byte_value & 127)::bigint << shift_bits);
          EXIT WHEN byte_value < 128;
          shift_bits := shift_bits + 7;
        END LOOP;
        IF field_length < 0 OR field_length > payload_bytes - cursor_pos THEN
          RETURN NULL;
        END IF;
        IF field_index = field_number THEN
          RETURN substring(payload FROM cursor_pos + 1 FOR field_length::integer);
        END IF;
        cursor_pos := cursor_pos + field_length::integer;
      WHEN 5 THEN
        cursor_pos := cursor_pos + 4;
      ELSE
        RETURN NULL;
    END CASE;
    IF cursor_pos > payload_bytes THEN
      RETURN NULL;
    END IF;
  END LOOP;
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION temporal_onboarding.protobuf_bytes_field(bytea, integer) IS
  'Read a length-delimited protobuf field for the onboarding views. Returns NULL for absent or malformed fields.';

CREATE OR REPLACE VIEW temporal_onboarding.current_workflows AS
SELECT n.name AS namespace,
       c.workflow_id,
       encode(c.run_id, 'hex') AS run_id_hex,
       c.shard_id,
       c.start_time,
       CASE c.state
         WHEN 1 THEN 'created'
         WHEN 2 THEN 'running'
         WHEN 3 THEN 'completed'
         WHEN 4 THEN 'zombie'
         WHEN 5 THEN 'void'
         WHEN 6 THEN 'corrupted'
         ELSE 'unknown (' || c.state::text || ')'
       END AS execution_state,
       CASE c.status
         WHEN 1 THEN 'running'
         WHEN 2 THEN 'completed'
         WHEN 3 THEN 'failed'
         WHEN 4 THEN 'canceled'
         WHEN 5 THEN 'terminated'
         WHEN 6 THEN 'continued as new'
         WHEN 7 THEN 'timed out'
         ELSE 'unknown (' || c.status::text || ')'
       END AS execution_status,
       e.next_event_id,
       octet_length(e.data) AS execution_info_bytes,
       octet_length(e.state) AS execution_state_bytes
FROM public.current_executions AS c
LEFT JOIN public.namespaces AS n ON n.id = c.namespace_id
LEFT JOIN public.executions AS e
  ON e.shard_id = c.shard_id
 AND e.namespace_id = c.namespace_id
 AND e.workflow_id = c.workflow_id
 AND e.run_id = c.run_id;

COMMENT ON VIEW temporal_onboarding.current_workflows IS
  'Current run pointer, namespace, state/status, and the size of its mutable-state protobufs. A missing execution row means the run is no longer in executions.';

CREATE OR REPLACE VIEW temporal_onboarding.execution_runs AS
SELECT n.name AS namespace,
       e.workflow_id,
       encode(e.run_id, 'hex') AS run_id_hex,
       e.shard_id,
       c.run_id IS NOT NULL AS is_current_run,
       e.next_event_id,
       e.last_write_version,
       e.db_record_version,
       e.data_encoding AS execution_info_encoding,
       octet_length(e.data) AS execution_info_bytes,
       e.state_encoding AS execution_state_encoding,
       octet_length(e.state) AS execution_state_bytes
FROM public.executions AS e
LEFT JOIN public.namespaces AS n ON n.id = e.namespace_id
LEFT JOIN public.current_executions AS c
  ON c.shard_id = e.shard_id
 AND c.namespace_id = e.namespace_id
 AND c.workflow_id = e.workflow_id
 AND c.run_id = e.run_id;

COMMENT ON VIEW temporal_onboarding.execution_runs IS
  'One row per persisted workflow execution. next_event_id and the two protobuf sizes describe mutable state; is_current_run joins the current-run pointer.';

CREATE OR REPLACE VIEW temporal_onboarding.history_branches AS
SELECT shard_id,
       encode(tree_id, 'hex') AS tree_id_hex,
       encode(branch_id, 'hex') AS branch_id_hex,
       data_encoding,
       octet_length(data) AS branch_info_bytes
FROM public.history_tree;

COMMENT ON VIEW temporal_onboarding.history_branches IS
  'History branch metadata. A workflow execution points to a branch through version histories inside its execution-info protobuf.';

CREATE OR REPLACE VIEW temporal_onboarding.history_batches AS
SELECT shard_id,
       encode(tree_id, 'hex') AS tree_id_hex,
       encode(branch_id, 'hex') AS branch_id_hex,
       node_id AS first_event_id,
       -txn_id AS logical_txn_id,
       prev_txn_id,
       data_encoding,
       octet_length(data) AS history_bytes,
       encode(substring(data FROM 1 FOR 16), 'hex') AS protobuf_prefix_hex
FROM public.history_node;

COMMENT ON VIEW temporal_onboarding.history_batches IS
  'Each row stores a protobuf History containing one or more events. first_event_id is the node key; logical_txn_id reverses the PostgreSQL storage sign.';

CREATE OR REPLACE VIEW temporal_onboarding.matching_queues AS
SELECT 'v1'::text AS storage_version,
       n.name AS namespace,
       encode(substring(q.task_queue_id FROM 1 FOR 16), 'hex') AS namespace_id_hex,
       convert_from(substring(q.task_queue_id FROM 17 FOR octet_length(q.task_queue_id) - 17), 'UTF8') AS task_queue_name,
       CASE get_byte(q.task_queue_id, octet_length(q.task_queue_id) - 1)
         WHEN 1 THEN 'workflow'
         WHEN 2 THEN 'activity'
         WHEN 3 THEN 'nexus'
         ELSE 'unknown'
       END AS task_type,
       q.range_hash,
       encode(q.task_queue_id, 'hex') AS task_queue_id_hex,
       q.range_id,
       q.data_encoding,
       octet_length(q.data) AS metadata_bytes
FROM public.task_queues AS q
LEFT JOIN public.namespaces AS n
  ON n.id = substring(q.task_queue_id FROM 1 FOR 16)
UNION ALL
SELECT 'v2'::text AS storage_version,
       n.name AS namespace,
       encode(substring(q.task_queue_id FROM 1 FOR 16), 'hex') AS namespace_id_hex,
       convert_from(substring(q.task_queue_id FROM 17 FOR octet_length(q.task_queue_id) - 17), 'UTF8') AS task_queue_name,
       CASE get_byte(q.task_queue_id, octet_length(q.task_queue_id) - 1)
         WHEN 1 THEN 'workflow'
         WHEN 2 THEN 'activity'
         WHEN 3 THEN 'nexus'
         ELSE 'unknown'
       END AS task_type,
       q.range_hash,
       encode(q.task_queue_id, 'hex') AS task_queue_id_hex,
       q.range_id,
       q.data_encoding,
       octet_length(q.data) AS metadata_bytes
FROM public.task_queues_v2 AS q
LEFT JOIN public.namespaces AS n
  ON n.id = substring(q.task_queue_id FROM 1 FOR 16);

COMMENT ON VIEW temporal_onboarding.matching_queues IS
  'Matching queue metadata in both storage generations. task_queue_id is namespace UUID bytes + UTF-8 queue name + one task-type byte.';

CREATE OR REPLACE VIEW temporal_onboarding.matching_backlog AS
SELECT 'v1'::text AS storage_version,
       n.name AS namespace,
       encode(substring(t.task_queue_id FROM 1 FOR 16), 'hex') AS namespace_id_hex,
       t.range_hash,
       encode(t.task_queue_id, 'hex') AS task_queue_id_hex,
       NULL::bigint AS task_pass,
       t.task_id,
       t.data_encoding,
       octet_length(t.data) AS task_bytes
FROM public.tasks AS t
LEFT JOIN public.namespaces AS n
  ON n.id = substring(t.task_queue_id FROM 1 FOR 16)
UNION ALL
SELECT 'v2'::text AS storage_version,
       n.name AS namespace,
       encode(substring(t.task_queue_id FROM 1 FOR 16), 'hex') AS namespace_id_hex,
       t.range_hash,
       encode(t.task_queue_id, 'hex') AS task_queue_id_hex,
       t.pass AS task_pass,
       t.task_id,
       t.data_encoding,
       octet_length(t.data) AS task_bytes
FROM public.tasks_v2 AS t
LEFT JOIN public.namespaces AS n
  ON n.id = substring(t.task_queue_id FROM 1 FOR 16);

COMMENT ON VIEW temporal_onboarding.matching_backlog IS
  'Persisted Matching tasks in both storage generations. v2 task IDs may include an encoded subqueue suffix. Empty backlog can mean tasks were already delivered.';

CREATE OR REPLACE VIEW temporal_onboarding.matching_user_data AS
SELECT n.name AS namespace,
       u.task_queue_name,
       u.version,
       u.data_encoding,
       octet_length(u.data) AS user_data_bytes
FROM public.task_queue_user_data AS u
LEFT JOIN public.namespaces AS n ON n.id = u.namespace_id;

COMMENT ON VIEW temporal_onboarding.matching_user_data IS
  'Versioned task-queue user data, including worker-versioning state inside the protobuf blob.';

CREATE OR REPLACE VIEW temporal_onboarding.history_branch_owners AS
SELECT n.name AS namespace,
       owner.namespace_id,
       owner.workflow_id,
       owner.run_id,
       t.shard_id,
       encode(t.tree_id, 'hex') AS tree_id_hex,
       encode(t.branch_id, 'hex') AS branch_id_hex,
       e.run_id IS NOT NULL AS run_still_in_executions,
       t.data_encoding,
       octet_length(t.data) AS branch_info_bytes
FROM public.history_tree AS t
CROSS JOIN LATERAL (
  SELECT convert_from(temporal_onboarding.protobuf_bytes_field(t.data, 3), 'UTF8') AS info
) AS raw_owner
CROSS JOIN LATERAL (
  SELECT strpos(raw_owner.info, ':') AS first_colon,
         char_length(raw_owner.info) - strpos(reverse(raw_owner.info), ':') + 1 AS last_colon
) AS delimiters
CROSS JOIN LATERAL (
  SELECT CASE WHEN delimiters.first_colon > 0 AND delimiters.last_colon > delimiters.first_colon
              THEN substring(raw_owner.info FROM 1 FOR delimiters.first_colon - 1) END AS namespace_id,
         CASE WHEN delimiters.first_colon > 0 AND delimiters.last_colon > delimiters.first_colon
              THEN substring(raw_owner.info FROM delimiters.first_colon + 1
                             FOR delimiters.last_colon - delimiters.first_colon - 1) END AS workflow_id,
         CASE WHEN delimiters.first_colon > 0 AND delimiters.last_colon > delimiters.first_colon
              THEN substring(raw_owner.info FROM delimiters.last_colon + 1) END AS run_id
) AS owner
LEFT JOIN public.namespaces AS n
  ON encode(n.id, 'hex') = lower(replace(owner.namespace_id, '-', ''))
LEFT JOIN public.executions AS e
  ON e.shard_id = t.shard_id
 AND e.namespace_id = n.id
 AND e.workflow_id = owner.workflow_id
 AND encode(e.run_id, 'hex') = lower(replace(owner.run_id, '-', ''));

COMMENT ON VIEW temporal_onboarding.history_branch_owners IS
  'Decodes history_tree.info to show the namespace/workflow/run associated with a branch. This is debugging metadata, not a database FK or a complete fork-aware event history.';

CREATE OR REPLACE VIEW temporal_onboarding.history_branch_batches AS
WITH owners AS MATERIALIZED (
  SELECT namespace, namespace_id, workflow_id, run_id, shard_id,
         decode(tree_id_hex, 'hex') AS tree_id,
         decode(branch_id_hex, 'hex') AS branch_id
  FROM temporal_onboarding.history_branch_owners
)
SELECT o.namespace,
       o.workflow_id,
       o.run_id,
       h.shard_id,
       encode(h.tree_id, 'hex') AS tree_id_hex,
       encode(h.branch_id, 'hex') AS branch_id_hex,
       h.node_id AS first_event_id,
       -h.txn_id AS logical_txn_id,
       h.data_encoding,
       octet_length(h.data) AS history_bytes
FROM owners AS o
JOIN public.history_node AS h
  ON h.shard_id = o.shard_id
 AND h.tree_id = o.tree_id
 AND h.branch_id = o.branch_id;

COMMENT ON VIEW temporal_onboarding.history_branch_batches IS
  'History batches labeled with the owning branch metadata workflow/run. A forked run can also read ancestor branches; this view shows only rows physically on each branch.';

CREATE OR REPLACE VIEW temporal_onboarding.matching_task_workflows AS
WITH stored_tasks AS (
  SELECT 'v1'::text AS storage_version, range_hash, task_queue_id,
         NULL::bigint AS task_pass, task_id, data, data_encoding
  FROM public.tasks
  UNION ALL
  SELECT 'v2'::text AS storage_version, range_hash, task_queue_id,
         pass AS task_pass, task_id, data, data_encoding
  FROM public.tasks_v2
)
SELECT t.storage_version,
       n.name AS namespace,
       convert_from(temporal_onboarding.protobuf_bytes_field(task_info.data, 2), 'UTF8') AS workflow_id,
       convert_from(temporal_onboarding.protobuf_bytes_field(task_info.data, 3), 'UTF8') AS run_id,
       t.range_hash,
       encode(t.task_queue_id, 'hex') AS task_queue_id_hex,
       t.task_pass,
       t.task_id,
       t.data_encoding,
       octet_length(t.data) AS task_bytes,
       q.task_queue_name,
       q.task_type
FROM stored_tasks AS t
CROSS JOIN LATERAL (
  SELECT temporal_onboarding.protobuf_bytes_field(t.data, 1) AS data
) AS task_info
LEFT JOIN public.namespaces AS n
  ON n.id = substring(t.task_queue_id FROM 1 FOR 16)
LEFT JOIN temporal_onboarding.matching_queues AS q
  ON q.storage_version = t.storage_version
 AND q.range_hash = t.range_hash
 AND q.task_queue_id_hex = encode(t.task_queue_id, 'hex');

COMMENT ON VIEW temporal_onboarding.matching_task_workflows IS
  'Decodes workflow and run IDs from persisted Matching task protobufs. Queue name/type are available when the task key exactly matches queue metadata; v2 subqueues may not. Delivered tasks disappear from these tables.';

DROP VIEW IF EXISTS temporal_onboarding.workflow_resource_map;

CREATE VIEW temporal_onboarding.workflow_resource_map AS
SELECT c.namespace,
       c.workflow_id,
       c.run_id_hex,
       c.shard_id,
       c.execution_status,
       c.next_event_id,
       b.tree_id_hex,
       b.branch_id_hex,
       COALESCE(batch_stats.stored_batches_on_branch, 0) AS stored_batches_on_branch,
       task_stats.stored_matching_task_rows,
       task_stats.stored_task_queue_names
FROM temporal_onboarding.current_workflows AS c
LEFT JOIN temporal_onboarding.history_branch_owners AS b
  ON b.namespace = c.namespace
 AND b.workflow_id = c.workflow_id
 AND lower(replace(b.run_id, '-', '')) = c.run_id_hex
LEFT JOIN LATERAL (
  SELECT count(*) AS stored_batches_on_branch
  FROM public.history_node AS h
  WHERE h.shard_id = b.shard_id
    AND h.tree_id = decode(b.tree_id_hex, 'hex')
    AND h.branch_id = decode(b.branch_id_hex, 'hex')
) AS batch_stats ON true
LEFT JOIN LATERAL (
  SELECT count(*) AS stored_matching_task_rows,
         string_agg(DISTINCT t.task_queue_name, ', ' ORDER BY t.task_queue_name) AS stored_task_queue_names
  FROM temporal_onboarding.matching_task_workflows AS t
  WHERE t.namespace = c.namespace
    AND t.workflow_id = c.workflow_id
    AND lower(replace(t.run_id, '-', '')) = c.run_id_hex
) AS task_stats ON true;

COMMENT ON VIEW temporal_onboarding.workflow_resource_map IS
  'One grid linking each current run to its History branch and physically stored batches, plus stored Matching task rows. Stored tasks may remain for completed runs; forked runs can read ancestor batches.';

GRANT USAGE ON SCHEMA temporal_onboarding TO temporal;
GRANT SELECT ON ALL TABLES IN SCHEMA temporal_onboarding TO temporal;
GRANT EXECUTE ON FUNCTION temporal_onboarding.protobuf_bytes_field(bytea, integer) TO temporal;

COMMIT;
