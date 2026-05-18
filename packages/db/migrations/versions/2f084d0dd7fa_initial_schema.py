"""initial schema

Squashed: combines the original initial schema, `add mrf_id to
hospital_payer_rates`, and `add model column to chat_requests` into one
revision. Existing dev DBs were re-stamped at this revision in-place
(no re-run) because the schema was already current.

Revision ID: 2f084d0dd7fa
Revises:
Create Date: 2026-05-17 04:13:38.995618
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision: str = '2f084d0dd7fa'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('chats',
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('attributes', sa.JSON(), nullable=True),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_date_updated', 'chats', ['date_updated'], unique=False)
    op.create_table('codes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.String(length=32), nullable=False),
    sa.Column('official_description', sa.Text(), nullable=True),
    sa.Column('most_common_description', sa.Text(), nullable=True),
    sa.Column('gemma_description', sa.Text(), nullable=True),
    sa.Column('category', sa.String(length=128), nullable=True),
    sa.Column('typical_setting', sa.String(length=32), nullable=True),
    sa.Column('source', sa.String(length=64), nullable=True),
    sa.Column('source_date', sa.Date(), nullable=True),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code', name='idx_code')
    )
    op.create_table('hospitals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ein', sa.String(length=9), nullable=True),
    sa.Column('hospital_name', sa.String(length=255), nullable=True),
    sa.Column('location_name', sa.String(length=512), nullable=False),
    sa.Column('hospital_address', sa.String(length=512), nullable=True),
    sa.Column('city', sa.String(length=128), nullable=True),
    sa.Column('state', sa.String(length=2), nullable=True),
    sa.Column('zip', sa.String(length=10), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('license_number', sa.String(length=64), nullable=True),
    sa.Column('license_state', sa.String(length=2), nullable=True),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_city', 'hospitals', ['city'], unique=False)
    op.create_index('idx_ein', 'hospitals', ['ein'], unique=False)
    op.create_index('idx_hospital_name', 'hospitals', ['hospital_name'], unique=False)
    op.create_index('idx_state', 'hospitals', ['state'], unique=False)
    op.create_index('idx_zip', 'hospitals', ['zip'], unique=False)
    op.create_table('mrfs_csv',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('mrf_url', sa.String(length=768), nullable=False),
    sa.Column('filename', sa.String(length=512), nullable=False),
    sa.Column('last_updated_on', sa.String(length=10), nullable=True),
    sa.Column('version', sa.String(length=16), nullable=True),
    sa.Column('attestation', sa.Boolean(), nullable=True),
    sa.Column('attester_name', sa.String(length=255), nullable=True),
    sa.Column('contact_name', sa.String(length=255), nullable=True),
    sa.Column('contact_email', sa.String(length=255), nullable=True),
    sa.Column('content_sha256', sa.String(length=64), nullable=True),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('content_sha256', name='idx_content_sha256')
    )
    op.create_index('idx_last_updated_on', 'mrfs_csv', ['last_updated_on'], unique=False)
    op.create_table('chat_requests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('chat_id', sa.String(length=32), nullable=False),
    sa.Column('user_message', sa.Text(), nullable=True),
    sa.Column('request', sa.JSON(), nullable=True),
    sa.Column('response', sa.JSON(), nullable=True),
    sa.Column('tool_calls', sa.JSON(), nullable=True),
    sa.Column('tool_results', mysql.MEDIUMTEXT(), nullable=True),
    sa.Column('reply_text', sa.Text(), nullable=True),
    sa.Column('input_tokens', sa.Integer(), nullable=False),
    sa.Column('output_tokens', sa.Integer(), nullable=False),
    sa.Column('thought_tokens', sa.Integer(), nullable=False),
    sa.Column('total_tokens', sa.Integer(), nullable=False),
    sa.Column('model', sa.String(length=64), nullable=False),
    sa.Column('error', sa.JSON(), nullable=True),
    sa.Column('attributes', sa.JSON(), nullable=True),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_chat_id_date_created', 'chat_requests', ['chat_id', 'date_created'], unique=False)
    op.create_table('hospital_code_charges',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('mrf_id', sa.Integer(), nullable=False),
    sa.Column('setting', sa.String(length=32), nullable=True),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('modifiers', sa.String(length=64), nullable=True),
    sa.Column('drug_unit_of_measurement', sa.String(length=32), nullable=True),
    sa.Column('drug_type_of_measurement', sa.String(length=8), nullable=True),
    sa.Column('additional_generic_notes', sa.Text(), nullable=True),
    sa.Column('gross_charge', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('discounted_cash_price', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('min_negotiated_charge', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('max_negotiated_charge', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['mrf_id'], ['mrfs_csv.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_hospital_id', 'hospital_code_charges', ['hospital_id'], unique=False)
    op.create_index('idx_mrf_id', 'hospital_code_charges', ['mrf_id'], unique=False)
    op.create_table('hospital_mrfs',
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('mrf_id', sa.Integer(), nullable=False),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['mrf_id'], ['mrfs_csv.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('hospital_id', 'mrf_id')
    )
    op.create_table('hospital_npis',
    sa.Column('hospital_id', sa.Integer(), nullable=False),
    sa.Column('npi', sa.String(length=10), nullable=False),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['hospital_id'], ['hospitals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('hospital_id', 'npi')
    )
    op.create_index('idx_npi', 'hospital_npis', ['npi'], unique=False)
    op.create_table('hospital_code_charge_codes',
    sa.Column('hospital_code_charge_id', sa.Integer(), nullable=False),
    sa.Column('code_id', sa.Integer(), nullable=False),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['code_id'], ['codes.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['hospital_code_charge_id'], ['hospital_code_charges.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('hospital_code_charge_id', 'code_id')
    )
    op.create_index('idx_code_id', 'hospital_code_charge_codes', ['code_id'], unique=False)
    op.create_table('hospital_payer_rates',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('hospital_code_charge_id', sa.Integer(), nullable=False),
    sa.Column('mrf_id', sa.Integer(), nullable=False),
    sa.Column('payer_name_raw', sa.String(length=255), nullable=False),
    sa.Column('plan_name', sa.String(length=255), nullable=True),
    sa.Column('negotiated_dollar', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('negotiated_percentage', sa.DECIMAL(precision=8, scale=4), nullable=True),
    sa.Column('negotiated_algorithm', sa.Text(), nullable=True),
    sa.Column('methodology', sa.String(length=64), nullable=True),
    sa.Column('estimated_allowed_amount', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('median_allowed_amount', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('p10_allowed_amount', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('p90_allowed_amount', sa.DECIMAL(precision=14, scale=2), nullable=True),
    sa.Column('allowed_amounts_count', sa.String(length=16), nullable=True),
    sa.Column('additional_payer_notes', sa.Text(), nullable=True),
    sa.Column('date_created', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('date_updated', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.ForeignKeyConstraint(['hospital_code_charge_id'], ['hospital_code_charges.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['mrf_id'], ['mrfs_csv.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_hospital_code_charge_id', 'hospital_payer_rates', ['hospital_code_charge_id'], unique=False)
    op.create_index('idx_payer_name_raw', 'hospital_payer_rates', ['payer_name_raw'], unique=False)
    op.create_index('idx_payer_rates_mrf_id', 'hospital_payer_rates', ['mrf_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_payer_rates_mrf_id', table_name='hospital_payer_rates')
    op.drop_index('idx_payer_name_raw', table_name='hospital_payer_rates')
    op.drop_index('idx_hospital_code_charge_id', table_name='hospital_payer_rates')
    op.drop_table('hospital_payer_rates')
    op.drop_index('idx_code_id', table_name='hospital_code_charge_codes')
    op.drop_table('hospital_code_charge_codes')
    op.drop_index('idx_npi', table_name='hospital_npis')
    op.drop_table('hospital_npis')
    op.drop_table('hospital_mrfs')
    op.drop_index('idx_mrf_id', table_name='hospital_code_charges')
    op.drop_index('idx_hospital_id', table_name='hospital_code_charges')
    op.drop_table('hospital_code_charges')
    op.drop_index('idx_chat_id_date_created', table_name='chat_requests')
    op.drop_table('chat_requests')
    op.drop_index('idx_last_updated_on', table_name='mrfs_csv')
    op.drop_table('mrfs_csv')
    op.drop_index('idx_zip', table_name='hospitals')
    op.drop_index('idx_state', table_name='hospitals')
    op.drop_index('idx_hospital_name', table_name='hospitals')
    op.drop_index('idx_ein', table_name='hospitals')
    op.drop_index('idx_city', table_name='hospitals')
    op.drop_table('hospitals')
    op.drop_table('codes')
    op.drop_index('idx_date_updated', table_name='chats')
    op.drop_table('chats')
