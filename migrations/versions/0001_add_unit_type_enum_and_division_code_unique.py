"""Add unit_type enum and unique constraint for division code

Revision ID: 0001_add_unit_type_enum_and_division_code_unique
Revises: 
Create Date: 2026-01-25 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
def upgrade():
    # 1) create enum type
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'unit_type_enum') THEN
            CREATE TYPE unit_type_enum AS ENUM ('faculty','office');
        END IF;
    END$$;
    """)

    # 2) alter organization_units.unit_type to use enum (Postgres)
    op.alter_column(
        'organization_units',
        'unit_type',
        existing_type=sa.String(length=20),
        type_=postgresql.ENUM('faculty', 'office', name='unit_type_enum'),
        postgresql_using="unit_type::unit_type_enum",
        existing_nullable=False,
        existing_server_default=sa.text("'faculty'")
    )

    # 3) add unique constraint for division code within organization unit
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'uq_division_code_org'
        ) THEN
            ALTER TABLE divisions ADD CONSTRAINT uq_division_code_org UNIQUE (code, organization_unit_id);
        END IF;
    END$$;
    """)


def downgrade():
    # 1) drop unique constraint
    op.drop_constraint('uq_division_code_org', 'divisions', type_='unique')

    # 2) alter column back to String
    op.alter_column(
        'organization_units',
        'unit_type',
        existing_type=postgresql.ENUM('faculty', 'office', name='unit_type_enum'),
        type_=sa.String(length=20),
        postgresql_using="unit_type::text",
        existing_nullable=False,
        existing_server_default=sa.text("'faculty'")
    )

    # 3) drop enum type
    op.execute('DROP TYPE IF EXISTS unit_type_enum')
