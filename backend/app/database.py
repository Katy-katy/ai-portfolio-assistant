# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# Resolve the database path (pointing to database/portfolio.db)
AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.abspath(os.path.join(AGENT_DIR, ".."))
DB_DIR = os.path.join(BASE_DIR, "database")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "portfolio.db")

DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}"

if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String, ForeignKey("user_sessions.session_id"), nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=True)
    intent = Column(String, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    cache_hits = Column(Integer, nullable=True)
    cache_misses = Column(Integer, nullable=True)
    cache_expired = Column(Integer, nullable=True)
    cache_sets = Column(Integer, nullable=True)
    cache_lookups = Column(Integer, nullable=True)
    cache_hit_rate = Column(Float, nullable=True)
    cache_by_category = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String, nullable=False)
    output = Column(Text, nullable=True)
    tools_called = Column(String, nullable=True)
    tokens_used = Column(Integer, nullable=True)
    cache_hits = Column(Integer, nullable=True)
    cache_misses = Column(Integer, nullable=True)
    cache_expired = Column(Integer, nullable=True)
    cache_sets = Column(Integer, nullable=True)
    cache_lookups = Column(Integer, nullable=True)
    cache_hit_rate = Column(Float, nullable=True)
    cache_by_category = Column(Text, nullable=True)

class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comments = Column(Text, nullable=True)


def _ensure_column_if_missing(table_name: str, column_name: str, column_sql: str) -> None:
    """Add a column to an existing table if it does not exist yet."""
    inspector = inspect(engine)
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    if column_name in existing:
        return

    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"))


def _ensure_cache_metrics_schema() -> None:
    """Ensure cache metric columns exist for existing installations."""
    additions = {
        "questions": [
            ("cache_hits", "INTEGER"),
            ("cache_misses", "INTEGER"),
            ("cache_expired", "INTEGER"),
            ("cache_sets", "INTEGER"),
            ("cache_lookups", "INTEGER"),
            ("cache_hit_rate", "FLOAT"),
            ("cache_by_category", "TEXT"),
        ],
        "agent_runs": [
            ("cache_hits", "INTEGER"),
            ("cache_misses", "INTEGER"),
            ("cache_expired", "INTEGER"),
            ("cache_sets", "INTEGER"),
            ("cache_lookups", "INTEGER"),
            ("cache_hit_rate", "FLOAT"),
            ("cache_by_category", "TEXT"),
        ],
    }

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table_name, columns in additions.items():
        if table_name not in tables:
            continue
        for column_name, column_sql in columns:
            _ensure_column_if_missing(table_name, column_name, column_sql)

def init_db():
    Base.metadata.create_all(bind=engine)
    _ensure_cache_metrics_schema()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
