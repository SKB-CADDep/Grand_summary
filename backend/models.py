from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ObjectItem(Base):
    __tablename__ = "objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    station: Mapped[str | None] = mapped_column(String(255), nullable=True)
    turbine: Mapped[str | None] = mapped_column(String(255), nullable=True)
    cylinder: Mapped[str | None] = mapped_column(String(64), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workbooks: Mapped[list["Workbook"]] = relationship(back_populates="object")


class Workbook(Base):
    __tablename__ = "workbooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    object_id: Mapped[str] = mapped_column(ForeignKey("objects.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    extra_columns_json: Mapped[str] = mapped_column(Text, default="[]")
    extra_parameters_json: Mapped[str] = mapped_column(Text, default="[]")
    parameter_overrides_json: Mapped[str] = mapped_column(Text, default="{}")
    deleted_parameters_json: Mapped[str] = mapped_column(Text, default="[]")

    object: Mapped[ObjectItem] = relationship(back_populates="workbooks")
    cells: Mapped[list["Cell"]] = relationship(back_populates="workbook", cascade="all, delete-orphan")
    versions: Mapped[list["Version"]] = relationship(back_populates="workbook", cascade="all, delete-orphan")


class Cell(Base):
    __tablename__ = "cells"
    __table_args__ = (UniqueConstraint("workbook_id", "parameter_key", "column_key", name="uq_cell"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workbook_id: Mapped[str] = mapped_column(ForeignKey("workbooks.id"), nullable=False, index=True)
    parameter_key: Mapped[str] = mapped_column(String(32), nullable=False)
    column_key: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    draft_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="empty")
    hyperlink: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    workbook: Mapped[Workbook] = relationship(back_populates="cells")
    changes: Mapped[list["CellChange"]] = relationship(back_populates="cell", cascade="all, delete-orphan")


class CellChange(Base):
    __tablename__ = "cell_changes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    cell_id: Mapped[str] = mapped_column(ForeignKey("cells.id"), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str] = mapped_column(Text, nullable=False)

    cell: Mapped[Cell] = relationship(back_populates="changes")


class Version(Base):
    __tablename__ = "versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workbook_id: Mapped[str] = mapped_column(ForeignKey("workbooks.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)

    workbook: Mapped[Workbook] = relationship(back_populates="versions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    workbook_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    object_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parameter_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    column_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recipient: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    author: Mapped[str] = mapped_column(String(128), nullable=False)
    workbook_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parameter_key: Mapped[str] = mapped_column(String(32), nullable=False)
    column_key: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
