\pset tuples_only on
\pset format unaligned
SELECT json_build_object(
  'cost_params', (
    SELECT json_object_agg(name, json_build_object('value', setting, 'unit', unit))
    FROM pg_settings
    WHERE name IN ('seq_page_cost','random_page_cost','cpu_tuple_cost',
                   'cpu_index_tuple_cost','cpu_operator_cost',
                   'work_mem','effective_cache_size')),
  'tables', (
    SELECT json_agg(json_build_object(
      'table', c.relname,
      'reltuples', c.reltuples,
      'relpages', c.relpages,
      'columns', (
        SELECT json_agg(json_build_object(
          'column', s.attname,
          'null_frac', s.null_frac,
          'n_distinct', s.n_distinct,
          'avg_width', s.avg_width,
          'most_common_vals', s.most_common_vals::text,
          'most_common_freqs', s.most_common_freqs,
          'histogram_bounds', s.histogram_bounds::text))
        FROM pg_stats s
        WHERE s.schemaname = 'public' AND s.tablename = c.relname)))
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r')
);
