-- Fix ontology + graph_edges RLS policies: use app.current_org_id (TenantDb GUC),
-- not app.org_id (never set — blocked all org-scoped writes since 027/025).

DO $$
DECLARE
    tbl text;
BEGIN
    FOREACH tbl IN ARRAY ARRAY[
        'ontology_link_types',
        'ontology_object_kinds',
        'ontology_interfaces',
        'ontology_kind_interfaces',
        'ontology_entities',
        'ontology_action_types',
        'ontology_action_log',
        'memory_graph_edges'
    ]
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I_org ON %I', tbl, tbl);
        EXECUTE format(
            'CREATE POLICY %I_org ON %I '
            'USING (org_id = current_setting(''app.current_org_id'', true)::uuid) '
            'WITH CHECK (org_id = current_setting(''app.current_org_id'', true)::uuid)',
            tbl, tbl
        );
    END LOOP;
END $$;
