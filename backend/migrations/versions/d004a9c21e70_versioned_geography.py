"""DATA-004: dated boundary versions and reproducible geography inputs.

Revision ID: d004a9c21e70
Revises: d003f93a1700
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'd004a9c21e70'
down_revision = 'd003f93a1700'
branch_labels = None
depends_on = None


def upgrade():
    # Shared extension: intentionally retained by downgrade. No geometry imports.
    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA public')
    op.alter_column('geographic_reference', 'kind', existing_type=sa.String(20), type_=sa.String(32), existing_nullable=False)
    op.drop_constraint('ck_geo_reference_kind', 'geographic_reference', type_='check')
    op.create_check_constraint('ck_geo_reference_kind', 'geographic_reference',
        "kind IN ('state','county','place','congressional_district')")
    op.create_unique_constraint('uq_geo_reference_identity', 'geographic_reference', ['id','jurisdiction_id'])
    for table, child, name in (
        ('jurisdiction_identifier','jurisdiction_id','identifier'),
        ('jurisdiction_relationship','child_id','relationship'),
    ):
        if name == 'relationship':
            op.add_column(table, sa.Column('valid_from', sa.Date()))
            op.add_column(table, sa.Column('valid_until', sa.Date()))
            op.create_check_constraint('ck_geo_relationship_distinct', table, 'parent_id <> child_id')
            op.create_check_constraint('ck_geo_relationship_dates', table,
                'valid_until IS NULL OR valid_from IS NULL OR valid_until > valid_from')
        op.add_column(table, sa.Column('validity_evidence_url', sa.Text()))
        op.create_check_constraint('ck_jurisdiction_identifier_date_evidence' if name == 'identifier'
            else 'ck_geo_relationship_date_evidence', table,
            '(valid_from IS NULL AND valid_until IS NULL) OR '
            'length(trim(validity_evidence_url)) > 0 AND validity_evidence_url IS NOT NULL')
        op.create_foreign_key(f'fk_geo_{name}_identity', table, 'geographic_reference',
            ['reference_id',child], ['id','jurisdiction_id'])
    op.create_table('jurisdiction_boundary_vintage',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('jurisdiction_id',sa.Uuid(),sa.ForeignKey('jurisdiction.id'),nullable=False),
        sa.Column('reference_id',sa.Uuid(),sa.ForeignKey('geographic_reference.id'),nullable=False),
        sa.Column('version_label',sa.String(100),nullable=False),
        sa.Column('valid_from',sa.Date(),nullable=False),
        sa.Column('valid_until',sa.Date()),
        sa.Column('evidence_url',sa.Text(),nullable=False),
        sa.Column('evidence_note',sa.Text(),nullable=False),
        sa.UniqueConstraint('jurisdiction_id','version_label',name='uq_geo_boundary_label'),
        sa.ForeignKeyConstraint(['reference_id','jurisdiction_id'],
            ['geographic_reference.id','geographic_reference.jurisdiction_id'],name='fk_geo_boundary_identity'),
        sa.CheckConstraint('valid_until IS NULL OR valid_until > valid_from',name='ck_geo_boundary_dates'),
        sa.CheckConstraint('length(trim(evidence_url)) > 0 AND length(trim(evidence_note)) > 0',name='ck_geo_boundary_evidence'),
        postgresql.ExcludeConstraint(('jurisdiction_id','='),
            (sa.func.daterange(sa.column('valid_from'),sa.column('valid_until'),'[)'),'&&'),
            name='ex_geo_boundary_overlap',using='gist',ops={'jurisdiction_id':'public.gist_uuid_ops'}))
    op.create_table('geographic_resolution_context',
        sa.Column('sha256',sa.String(64),primary_key=True),
        sa.Column('manifest',postgresql.JSONB(),nullable=False))
    op.add_column('geographic_resolution',sa.Column('context_sha256',sa.String(64),
        sa.ForeignKey('geographic_resolution_context.sha256')))
    op.create_unique_constraint('uq_geo_resolution_scope','geographic_resolution',
        ['id','observation_id','reference_release_id'])
    op.create_foreign_key('fk_geo_resolution_chain_scope','geographic_resolution','geographic_resolution',
        ['supersedes_id','observation_id','reference_release_id'],['id','observation_id','reference_release_id'])
    op.create_foreign_key('fk_geo_resolution_identity','geographic_resolution','geographic_reference',
        ['reference_id','jurisdiction_id'],['id','jurisdiction_id'])
    op.create_check_constraint('ck_geo_resolution_not_self','geographic_resolution','supersedes_id IS NULL OR supersedes_id <> id')
    op.create_check_constraint('ck_geo_resolution_status','geographic_resolution',
        "status IN ('RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS','UNRESOLVED','AMBIGUOUS',"
        "'INVALID','OUT_OF_VINTAGE','PENDING_REVIEW','NON_COUNTY_CLASSIFIED')")
    op.create_check_constraint('ck_geo_resolution_target','geographic_resolution',
        "(status IN ('RESOLVED','RESOLVED_HISTORICAL','RESOLVED_ALIAS') AND jurisdiction_id IS NOT NULL "
        "AND reference_id IS NOT NULL) OR (status NOT IN ('RESOLVED','RESOLVED_HISTORICAL',"
        "'RESOLVED_ALIAS') AND jurisdiction_id IS NULL)")
    # Protect recorded decisions and input snapshots, including all legacy roots.
    op.execute("""CREATE FUNCTION data004_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'DATA-004 history is append-only: %', TG_TABLE_NAME;
        END $$""")
    for table in ('geographic_resolution','geographic_resolution_context'):
        op.execute(f'CREATE TRIGGER data004_immutable BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION data004_immutable()')


def downgrade():
    # Empty additions are reversible. Never silently discard new geography/history.
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM jurisdiction_boundary_vintage)
          OR EXISTS (SELECT 1 FROM geographic_resolution_context)
          OR EXISTS (SELECT 1 FROM geographic_reference WHERE kind='congressional_district')
          OR EXISTS (SELECT 1 FROM jurisdiction_identifier WHERE validity_evidence_url IS NOT NULL)
          OR EXISTS (SELECT 1 FROM jurisdiction_relationship WHERE valid_from IS NOT NULL
                     OR valid_until IS NOT NULL OR validity_evidence_url IS NOT NULL)
        THEN RAISE EXCEPTION 'DATA-004 downgrade would discard recorded history'; END IF;
        END $$""")
    for table in ('geographic_resolution','geographic_resolution_context'):
        op.execute(f'DROP TRIGGER data004_immutable ON {table}')
    op.execute('DROP FUNCTION data004_immutable()')
    for name in ('ck_geo_resolution_target','ck_geo_resolution_status','ck_geo_resolution_not_self',
                 'fk_geo_resolution_identity','fk_geo_resolution_chain_scope','uq_geo_resolution_scope'):
        op.drop_constraint(name,'geographic_resolution')
    op.drop_column('geographic_resolution','context_sha256')
    op.drop_table('geographic_resolution_context')
    op.drop_table('jurisdiction_boundary_vintage')
    for table, name in (('jurisdiction_identifier','identifier'),('jurisdiction_relationship','relationship')):
        op.drop_constraint(f'fk_geo_{name}_identity',table)
        op.drop_constraint('ck_jurisdiction_identifier_date_evidence' if name == 'identifier'
                           else 'ck_geo_relationship_date_evidence',table)
        op.drop_column(table,'validity_evidence_url')
    for name in ('ck_geo_relationship_dates','ck_geo_relationship_distinct'):
        op.drop_constraint(name,'jurisdiction_relationship')
    op.drop_column('jurisdiction_relationship','valid_until')
    op.drop_column('jurisdiction_relationship','valid_from')
    op.drop_constraint('uq_geo_reference_identity','geographic_reference')
    op.drop_constraint('ck_geo_reference_kind','geographic_reference')
    op.create_check_constraint('ck_geo_reference_kind','geographic_reference',"kind IN ('state','county','place')")
    op.alter_column('geographic_reference','kind',existing_type=sa.String(32),type_=sa.String(20),existing_nullable=False)
