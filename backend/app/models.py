"""Relational schema. Every tenant-owned row is reachable from an Organization,
and project-scoped rows carry project_id so queries can be filtered by tenant."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


Timestamp = DateTime(timezone=True)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, nullable=False)


# --------------------------------------------------------------------------- identity & tenancy


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(30), default="starter", nullable=False)
    monthly_test_run_quota: Mapped[int] = mapped_column(Integer, default=5000, nullable=False)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class Membership(TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_membership"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # owner | admin | member | viewer

    user: Mapped[User] = relationship(back_populates="memberships")
    organization: Mapped[Organization] = relationship(back_populates="memberships")


class Invitation(TimestampMixin, Base):
    __tablename__ = "invitations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)


class UserSession(TimestampMixin, Base):
    __tablename__ = "user_sessions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(300))


class ApiToken(TimestampMixin, Base):
    """Tokens for CI/CD triggers. Scoped to one organization (optionally one project)."""

    __tablename__ = "api_tokens"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_used_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)


# --------------------------------------------------------------------------- projects & environments


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_project_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(2000))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    organization: Mapped[Organization] = relationship(back_populates="projects")
    environments: Mapped[list["Environment"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class Environment(TimestampMixin, Base):
    __tablename__ = "environments"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_environment_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_url: Mapped[Optional[str]] = mapped_column(String(2000))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    project: Mapped[Project] = relationship(back_populates="environments")
    variables: Mapped[list["EnvironmentVariable"]] = relationship(back_populates="environment", cascade="all, delete-orphan")


class EnvironmentVariable(TimestampMixin, Base):
    __tablename__ = "environment_variables"
    __table_args__ = (UniqueConstraint("environment_id", "key", name="uq_env_var_key"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    environment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("environments.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[Optional[str]] = mapped_column(Text)  # plaintext, only for non-secret values
    secret_ciphertext: Mapped[Optional[str]] = mapped_column(Text)  # Fernet token for secrets
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    environment: Mapped[Environment] = relationship(back_populates="variables")


# --------------------------------------------------------------------------- tests


class TestCase(TimestampMixin, Base):
    __tablename__ = "test_cases"
    __test__ = False
    __table_args__ = (Index("ix_test_cases_project_status", "project_id", "status"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    kind: Mapped[str] = mapped_column(String(10), default="ui", nullable=False)  # ui | api
    category: Mapped[str] = mapped_column(String(30), default="functional", nullable=False)
    priority: Mapped[str] = mapped_column(String(10), default="medium", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)  # draft | generated | ready | archived
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(100))  # discovery / endpoint / conversation id
    expectation_basis: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)  # confirmed | inferred | specified
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    validation_status: Mapped[str] = mapped_column(String(20), default="unvalidated", nullable=False)
    validation_messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, onupdate=utcnow, nullable=False)

    steps: Mapped[list["TestStep"]] = relationship(
        back_populates="test_case", cascade="all, delete-orphan", order_by="TestStep.position"
    )


class TestStep(Base):
    __tablename__ = "test_steps"
    __test__ = False
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    target: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)  # structured locator
    value: Mapped[Optional[str]] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    test_case: Mapped[TestCase] = relationship(back_populates="steps")


class TestSuite(TimestampMixin, Base):
    __tablename__ = "test_suites"
    __test__ = False
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_suite_name"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    items: Mapped[list["SuiteItem"]] = relationship(cascade="all, delete-orphan", order_by="SuiteItem.position")


class SuiteItem(Base):
    __tablename__ = "suite_items"
    __table_args__ = (UniqueConstraint("suite_id", "test_case_id", name="uq_suite_item"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    suite_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_suites.id", ondelete="CASCADE"), index=True)
    test_case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_cases.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


# --------------------------------------------------------------------------- execution


class TestExecution(TimestampMixin, Base):
    """One run of one or more test cases."""

    __tablename__ = "test_executions"
    __test__ = False
    __table_args__ = (
        Index("ix_executions_project_created", "project_id", "created_at"),
        UniqueConstraint("project_id", "idempotency_key", name="uq_execution_idempotency"),
    )
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    environment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("environments.id", ondelete="SET NULL"))
    suite_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("test_suites.id", ondelete="SET NULL"))
    triggered_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)  # manual | api | ci | assistant
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    browser: Mapped[str] = mapped_column(String(20), default="chromium", nullable=False)
    headless: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    workers: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30_000, nullable=False)
    capture_video: Mapped[str] = mapped_column(String(20), default="retain-on-failure", nullable=False)
    capture_trace: Mapped[str] = mapped_column(String(20), default="retain-on-failure", nullable=False)
    capture_screenshot: Mapped[str] = mapped_column(String(20), default="on", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)
    finished_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    flaky: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    task_id: Mapped[Optional[str]] = mapped_column(String(100))
    summary: Mapped[Optional[str]] = mapped_column(Text)

    results: Mapped[list["TestResult"]] = relationship(back_populates="execution", cascade="all, delete-orphan")


class TestResult(TimestampMixin, Base):
    __tablename__ = "test_results"
    __test__ = False
    __table_args__ = (Index("ix_results_case_created", "test_case_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_executions.id", ondelete="CASCADE"), index=True)
    test_case_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("test_cases.id", ondelete="SET NULL"))
    test_title: Mapped[str] = mapped_column(String(300), nullable=False)
    test_case_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    browser: Mapped[str] = mapped_column(String(20), default="chromium", nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)
    finished_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    retries_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_stack: Mapped[Optional[str]] = mapped_column(Text)
    failed_step_index: Mapped[Optional[int]] = mapped_column(Integer)
    step_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    generated_code: Mapped[Optional[str]] = mapped_column(Text)
    log: Mapped[Optional[str]] = mapped_column(Text)
    failure_category: Mapped[Optional[str]] = mapped_column(String(40))
    failure_confidence: Mapped[Optional[float]] = mapped_column(Float)
    failure_summary: Mapped[Optional[str]] = mapped_column(Text)
    failure_evidence: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    execution: Mapped[TestExecution] = relationship(back_populates="results")
    artifacts: Mapped[list["TestArtifact"]] = relationship(cascade="all, delete-orphan")


class TestArtifact(TimestampMixin, Base):
    __tablename__ = "test_artifacts"
    __test__ = False
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("test_executions.id", ondelete="CASCADE"), index=True)
    result_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("test_results.id", ondelete="CASCADE"), index=True)
    discovery_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("site_discoveries.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # screenshot | video | trace | api | report | dom
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class HealingSuggestion(TimestampMixin, Base):
    __tablename__ = "healing_suggestions"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("test_results.id", ondelete="CASCADE"), index=True)
    test_step_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("test_steps.id", ondelete="SET NULL"))
    original_target: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    suggested_target: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending | accepted | rejected
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)


# --------------------------------------------------------------------------- discovery & API


class SiteDiscovery(TimestampMixin, Base):
    __tablename__ = "site_discoveries"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    max_depth: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    uses_login: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    login_url: Mapped[Optional[str]] = mapped_column(String(2000))
    environment_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("environments.id", ondelete="SET NULL"))
    authorization_confirmed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    authorization_confirmed_at: Mapped[datetime] = mapped_column(Timestamp, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)
    finished_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    login_result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    skipped: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    pages: Mapped[list["DiscoveredPage"]] = relationship(cascade="all, delete-orphan", order_by="DiscoveredPage.position")


class DiscoveredPage(Base):
    __tablename__ = "discovered_pages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    discovery_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("site_discoveries.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    title: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    depth: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requires_login: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    screenshot_artifact_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    headings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    forms: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    links: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    buttons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    tables: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    text_sample: Mapped[str] = mapped_column(Text, default="", nullable=False)


class ApiCollection(TimestampMixin, Base):
    __tablename__ = "api_collections"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)  # openapi | swagger | postman | manual
    source_url: Mapped[Optional[str]] = mapped_column(String(2000))
    base_url: Mapped[Optional[str]] = mapped_column(String(2000))
    spec_version: Mapped[Optional[str]] = mapped_column(String(20))
    raw_spec: Mapped[Optional[str]] = mapped_column(Text)
    security_schemes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    endpoints: Mapped[list["ApiEndpoint"]] = relationship(cascade="all, delete-orphan", order_by="ApiEndpoint.path")


class ApiEndpoint(Base):
    __tablename__ = "api_endpoints"
    __table_args__ = (UniqueConstraint("collection_id", "method", "path", name="uq_endpoint"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    collection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("api_collections.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(1000), nullable=False)
    operation_id: Mapped[Optional[str]] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    parameters: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    request_schema: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)
    request_example: Mapped[Optional[Any]] = mapped_column(JSON)
    responses: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    security: Mapped[list[Any]] = mapped_column(JSON, default=list, nullable=False)


# --------------------------------------------------------------------------- AI


class AIGenerationJob(TimestampMixin, Base):
    __tablename__ = "ai_generation_jobs"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # website_plan | api_plan | nl_plan | failure_analysis
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    source_ref: Mapped[Optional[str]] = mapped_column(String(100))
    engine: Mapped[str] = mapped_column(String(30), nullable=False)  # deterministic | anthropic
    model: Mapped[Optional[str]] = mapped_column(String(60))
    input_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    output_tokens: Mapped[Optional[int]] = mapped_column(Integer)
    result_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    finished_at: Mapped[Optional[datetime]] = mapped_column(Timestamp)


class AssistantConversation(TimestampMixin, Base):
    __tablename__ = "assistant_conversations"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation", nullable=False)

    messages: Mapped[list["AssistantMessage"]] = relationship(cascade="all, delete-orphan", order_by="AssistantMessage.created_at")


class AssistantMessage(TimestampMixin, Base):
    __tablename__ = "assistant_messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assistant_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_org_created", "organization_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_id)
    organization_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    project_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50))
    resource_id: Mapped[Optional[str]] = mapped_column(String(100))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow, nullable=False)
