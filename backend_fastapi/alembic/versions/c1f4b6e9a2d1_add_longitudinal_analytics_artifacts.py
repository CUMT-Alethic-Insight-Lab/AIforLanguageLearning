"""add longitudinal analytics artifacts

Revision ID: c1f4b6e9a2d1
Revises: 4a8d7d7c2f11
Create Date: 2026-04-18 23:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "c1f4b6e9a2d1"
down_revision: Union[str, Sequence[str], None] = "4a8d7d7c2f11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("students", sa.Column("class_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True))
    op.create_index(op.f("ix_students_class_id"), "students", ["class_id"], unique=False)

    op.add_column(
        "student_daily_summaries",
        sa.Column("class_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
    )
    op.create_index(op.f("ix_student_daily_summaries_class_id"), "student_daily_summaries", ["class_id"], unique=False)

    op.create_table(
        "student_longitudinal_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("class_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("summary_kind", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("llm_summary", sa.Text(), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
        sa.Column("strength_flags", sa.JSON(), nullable=True),
        sa.Column("metric_deltas", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("source_summary_ids", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "class_id",
            "window_start",
            "window_end",
            "window_days",
            name="uq_student_longitudinal_summary_window",
        ),
    )
    op.create_index(
        op.f("ix_student_longitudinal_summaries_user_id"),
        "student_longitudinal_summaries",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_longitudinal_summaries_class_id"),
        "student_longitudinal_summaries",
        ["class_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_longitudinal_summaries_window_start"),
        "student_longitudinal_summaries",
        ["window_start"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_longitudinal_summaries_window_end"),
        "student_longitudinal_summaries",
        ["window_end"],
        unique=False,
    )

    op.create_table(
        "analytics_artifacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("artifact_type", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False),
        sa.Column("scope", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("class_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("agent_type", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=True),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("window_start", sa.Date(), nullable=True),
        sa.Column("window_end", sa.Date(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=256), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "artifact_type",
            "scope",
            "class_id",
            "user_id",
            "target_date",
            "window_start",
            "window_end",
            "agent_type",
            name="uq_analytics_artifact_scope_window",
        ),
    )
    op.create_index(op.f("ix_analytics_artifacts_artifact_type"), "analytics_artifacts", ["artifact_type"], unique=False)
    op.create_index(op.f("ix_analytics_artifacts_scope"), "analytics_artifacts", ["scope"], unique=False)
    op.create_index(op.f("ix_analytics_artifacts_user_id"), "analytics_artifacts", ["user_id"], unique=False)
    op.create_index(op.f("ix_analytics_artifacts_class_id"), "analytics_artifacts", ["class_id"], unique=False)
    op.create_index(op.f("ix_analytics_artifacts_agent_type"), "analytics_artifacts", ["agent_type"], unique=False)
    op.create_index(op.f("ix_analytics_artifacts_target_date"), "analytics_artifacts", ["target_date"], unique=False)
    op.create_index(op.f("ix_analytics_artifacts_window_start"), "analytics_artifacts", ["window_start"], unique=False)
    op.create_index(op.f("ix_analytics_artifacts_window_end"), "analytics_artifacts", ["window_end"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_analytics_artifacts_window_end"), table_name="analytics_artifacts")
    op.drop_index(op.f("ix_analytics_artifacts_window_start"), table_name="analytics_artifacts")
    op.drop_index(op.f("ix_analytics_artifacts_target_date"), table_name="analytics_artifacts")
    op.drop_index(op.f("ix_analytics_artifacts_agent_type"), table_name="analytics_artifacts")
    op.drop_index(op.f("ix_analytics_artifacts_class_id"), table_name="analytics_artifacts")
    op.drop_index(op.f("ix_analytics_artifacts_user_id"), table_name="analytics_artifacts")
    op.drop_index(op.f("ix_analytics_artifacts_scope"), table_name="analytics_artifacts")
    op.drop_index(op.f("ix_analytics_artifacts_artifact_type"), table_name="analytics_artifacts")
    op.drop_table("analytics_artifacts")

    op.drop_index(op.f("ix_student_longitudinal_summaries_window_end"), table_name="student_longitudinal_summaries")
    op.drop_index(op.f("ix_student_longitudinal_summaries_window_start"), table_name="student_longitudinal_summaries")
    op.drop_index(op.f("ix_student_longitudinal_summaries_class_id"), table_name="student_longitudinal_summaries")
    op.drop_index(op.f("ix_student_longitudinal_summaries_user_id"), table_name="student_longitudinal_summaries")
    op.drop_table("student_longitudinal_summaries")

    op.drop_index(op.f("ix_student_daily_summaries_class_id"), table_name="student_daily_summaries")
    op.drop_column("student_daily_summaries", "class_id")

    op.drop_index(op.f("ix_students_class_id"), table_name="students")
    op.drop_column("students", "class_id")
