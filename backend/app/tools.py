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
import re
import threading
import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from google.genai import Client
from pypdf import PdfReader

# Resolve the project root directory
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+")
DEFAULT_TOP_K = 3
MAX_CHUNK_CHARS = 900

# Keywords that indicate a question is about Kate's professional profile
ON_TOPIC_KEYWORDS = {
    # General portfolio/career
    "kate", "experience", "project", "skill", "background", "career", "resume", "cv", "education", "degree", "work", "job",
    # Technical skills
    "python", "java", "javascript", "sql", "machine learning", "nlp", "ai", "llm", "agent", "docker", "kubernetes", "gcp", "aws", "react", "fastapi",
    # Specific projects
    "lamabot", "babyyoda", "ticket", "classification", "linkedin", "slac",
    # Experience contexts
    "linkedin", "slac", "stanford", "georgia tech", "intern", "engineer", "senior", "lead", "manager",
    # Education
    "master", "bachelor", "phd", "graduate", "undergraduate", "certification",
    # Publications/achievements
    "paper", "publication", "award", "achievement", "contribution", "patent",
}


@dataclass
class Chunk:
    """A retrievable knowledge chunk with lightweight metadata."""

    text: str
    source: str
    category: str
    tokens: set[str]


_CHUNKS_LOCK = threading.Lock()
_CHUNKS_CACHE: list[Chunk] | None = None
_EMBED_LOCK = threading.Lock()
_EMBED_CLIENT: Client | None = None
_RETRIEVE_CACHE_LOCK = threading.Lock()
_RETRIEVE_CACHE: dict[tuple[str, str, str, int], tuple[float, list[dict]]] = {}
_RETRIEVE_CACHE_STATS = {
    "hits": 0,
    "misses": 0,
    "expired": 0,
    "sets": 0,
}
_RETRIEVE_CACHE_BY_CATEGORY: dict[str, dict[str, int]] = {}


def _new_cache_counter() -> dict[str, int]:
    return {
        "hits": 0,
        "misses": 0,
        "expired": 0,
        "sets": 0,
    }


def _normalize_cache_category(category: str) -> str:
    normalized = category.strip().lower()
    return normalized if normalized else "all"


def _get_category_cache_counter(category: str) -> dict[str, int]:
    normalized = _normalize_cache_category(category)
    counters = _RETRIEVE_CACHE_BY_CATEGORY.get(normalized)
    if counters is None:
        counters = _new_cache_counter()
        _RETRIEVE_CACHE_BY_CATEGORY[normalized] = counters
    return counters


def _increment_cache_stat(metric: str, category: str) -> None:
    _RETRIEVE_CACHE_STATS[metric] += 1
    category_counter = _get_category_cache_counter(category)
    category_counter[metric] += 1


def _counter_with_derived(counters: dict[str, int]) -> dict[str, float | int]:
    hits = int(counters.get("hits", 0))
    misses = int(counters.get("misses", 0))
    expired = int(counters.get("expired", 0))
    sets = int(counters.get("sets", 0))
    lookups = hits + misses
    hit_rate = (hits / lookups) if lookups > 0 else 0.0
    return {
        "hits": hits,
        "misses": misses,
        "expired": expired,
        "sets": sets,
        "lookups": lookups,
        "hit_rate": round(hit_rate, 4),
    }


def _tokenize(text: str) -> set[str]:
    return {t.lower() for t in TOKEN_RE.findall(text)}


def _retrieve_cache_ttl_sec() -> int:
    """Return retrieval cache TTL in seconds."""
    try:
        return max(0, int(os.getenv("RETRIEVE_CACHE_TTL_SEC", "300")))
    except ValueError:
        return 300


def _retrieve_cache_key(
    backend: str,
    category: str,
    query: str,
    top_k: int,
) -> tuple[str, str, str, int]:
    normalized_query = " ".join(query.lower().split())
    return (backend, category, normalized_query, top_k)


def _get_cached_retrieval(
    backend: str,
    category: str,
    query: str,
    top_k: int,
) -> list[dict] | None:
    """Get cached retrieval result if still valid."""
    ttl = _retrieve_cache_ttl_sec()
    if ttl <= 0:
        return None

    key = _retrieve_cache_key(backend, category, query, top_k)
    now = time.monotonic()

    with _RETRIEVE_CACHE_LOCK:
        entry = _RETRIEVE_CACHE.get(key)
        if not entry:
            _increment_cache_stat("misses", category)
            return None

        stored_at, chunks = entry
        if now - stored_at > ttl:
            _RETRIEVE_CACHE.pop(key, None)
            _increment_cache_stat("expired", category)
            _increment_cache_stat("misses", category)
            return None
        _increment_cache_stat("hits", category)
        return chunks


def _set_cached_retrieval(
    backend: str,
    category: str,
    query: str,
    top_k: int,
    chunks: list[dict],
) -> None:
    """Store retrieval result in cache for short-lived reuse."""
    ttl = _retrieve_cache_ttl_sec()
    if ttl <= 0:
        return

    key = _retrieve_cache_key(backend, category, query, top_k)
    with _RETRIEVE_CACHE_LOCK:
        _RETRIEVE_CACHE[key] = (time.monotonic(), chunks)
        _increment_cache_stat("sets", category)


def get_retrieval_cache_stats() -> dict[str, float | int]:
    """Return aggregate retrieval-cache counters since process start."""
    with _RETRIEVE_CACHE_LOCK:
        total = _counter_with_derived(_RETRIEVE_CACHE_STATS)
        by_category = {
            category: _counter_with_derived(counters)
            for category, counters in _RETRIEVE_CACHE_BY_CATEGORY.items()
        }

    total["by_category"] = by_category
    return total


def _split_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split markdown text into medium-sized chunks for retrieval."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return []

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current.strip())
                current = ""
            for i in range(0, len(paragraph), max_chars):
                piece = paragraph[i : i + max_chars].strip()
                if piece:
                    chunks.append(piece)
            continue

        if not current:
            current = paragraph
            continue

        candidate = f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current.strip())
            current = paragraph

    if current:
        chunks.append(current.strip())
    return chunks


def _read_source_content(source_path: Path) -> str:
    """Read knowledge source content from markdown or PDF files."""
    if source_path.suffix.lower() == ".pdf":
        reader = PdfReader(str(source_path))
        pages: list[str] = []
        for page in reader.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
        return "\n\n".join(pages)

    return source_path.read_text(encoding="utf-8")


def _categorize_profile_asset(source_path: Path) -> str:
    """Infer retrieval category for top-level knowledge PDF assets."""
    name = source_path.stem.lower()
    if "skill" in name:
        return "skills"
    if "profile" in name or "linkedin" in name:
        return "skills"
    if "project" in name:
        return "projects"
    return "resume"


def _to_vector_literal(values: list[float]) -> str:
    """Convert embedding values into pgvector literal format."""
    return "[" + ",".join(f"{v:.8f}" for v in values) + "]"


def _chunk_rows() -> list[dict]:
    """Build canonical chunk rows for retrieval/indexing."""
    rows: list[dict] = []
    for category, source_path in _knowledge_sources():
        if not source_path.exists():
            continue
        try:
            content = _read_source_content(source_path)
        except Exception:
            continue

        pieces = _split_text(content)
        for index, piece in enumerate(pieces):
            source = str(source_path.relative_to(BASE_DIR))
            content_hash = hashlib.sha256(piece.encode("utf-8")).hexdigest()
            rows.append(
                {
                    "source": source,
                    "category": category,
                    "chunk_index": index,
                    "text": piece,
                    "content_hash": content_hash,
                }
            )
    return rows


def _get_embedding_client() -> Client:
    """Create and cache a Google GenAI client for embedding generation."""
    global _EMBED_CLIENT
    with _EMBED_LOCK:
        if _EMBED_CLIENT is not None:
            return _EMBED_CLIENT

        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

        try:
            if project:
                _EMBED_CLIENT = Client(
                    vertexai=True,
                    project=project,
                    location=location,
                )
            else:
                # Falls back to Gemini API key flow if configured.
                _EMBED_CLIENT = Client()
        except Exception as e:
            raise RuntimeError(f"Failed to initialize embedding client: {e}") from e

        return _EMBED_CLIENT


def _embed_text(text: str) -> list[float]:
    """Generate embedding vector for a text chunk/query."""
    model = os.getenv("RAG_EMBEDDING_MODEL", "text-embedding-004")
    client = _get_embedding_client()
    response = client.models.embed_content(model=model, contents=text)
    if not response.embeddings:
        raise RuntimeError("Embedding response did not include vectors")
    values = response.embeddings[0].values
    if not values:
        raise RuntimeError("Embedding values are empty")
    return list(values)


def _ensure_pgvector_schema(conn: psycopg.Connection, table: str, dim: int) -> None:
    """Ensure extension, table, and indexes for pgvector retrieval exist."""
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                category TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding VECTOR({dim}) NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(source, chunk_index)
            )
            """
        )
        cur.execute(
            f"CREATE INDEX IF NOT EXISTS {table}_category_idx ON {table} (category)"
        )
        try:
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS {table}_embedding_idx
                ON {table}
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
                """
            )
        except Exception:
            # ivfflat may fail in some managed environments; seq scan remains valid.
            pass
    conn.commit()


def _sync_pgvector_index(conn: psycopg.Connection, table: str, dim: int) -> None:
    """Sync markdown chunks into pgvector table using hash-based upserts."""
    _ensure_pgvector_schema(conn, table, dim)
    rows = _chunk_rows()

    existing: dict[tuple[str, int], tuple[str, str]] = {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT source, chunk_index, content_hash, category FROM {table}")
        for source, chunk_index, content_hash, category in cur.fetchall():
            existing[(source, int(chunk_index))] = (content_hash, category)

    active_keys: set[tuple[str, int]] = set()
    with conn.cursor() as cur:
        for row in rows:
            key = (row["source"], row["chunk_index"])
            active_keys.add(key)

            existing_item = existing.get(key)
            if existing_item and existing_item[0] == row["content_hash"] and existing_item[1] == row["category"]:
                continue

            embedding = _embed_text(row["text"])
            if len(embedding) != dim:
                raise RuntimeError(
                    "Embedding dimension mismatch. "
                    f"Expected {dim}, got {len(embedding)}."
                )
            vector_literal = _to_vector_literal(embedding)

            cur.execute(
                f"""
                INSERT INTO {table} (
                    source,
                    category,
                    chunk_index,
                    content,
                    content_hash,
                    embedding,
                    updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s::vector, NOW())
                ON CONFLICT (source, chunk_index)
                DO UPDATE SET
                    category = EXCLUDED.category,
                    content = EXCLUDED.content,
                    content_hash = EXCLUDED.content_hash,
                    embedding = EXCLUDED.embedding,
                    updated_at = NOW()
                """,
                (
                    row["source"],
                    row["category"],
                    row["chunk_index"],
                    row["text"],
                    row["content_hash"],
                    vector_literal,
                ),
            )

        if active_keys:
            cur.execute(f"SELECT source, chunk_index FROM {table}")
            all_keys = {(r[0], int(r[1])) for r in cur.fetchall()}
            stale = all_keys - active_keys
            if stale:
                cur.executemany(
                    f"DELETE FROM {table} WHERE source = %s AND chunk_index = %s",
                    [(s, i) for s, i in stale],
                )

    conn.commit()


def index_pgvector_documents(force: bool = False) -> dict:
    """Synchronize knowledge documents into pgvector index.

    Intended to run during app startup so request-time retrieval remains read-only.

    Args:
        force: Reserved for future full-reindex behavior.

    Returns:
        Dict with sync status and basic counts.
    """
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        return {
            "status": "skipped",
            "reason": "PGVECTOR_DSN is not set",
        }

    table = os.getenv("PGVECTOR_TABLE", "knowledge_chunks")
    dim = int(os.getenv("PGVECTOR_EMBEDDING_DIM", "768"))

    with psycopg.connect(dsn) as conn:
        _sync_pgvector_index(conn, table, dim)
        with conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {table}")
            total_chunks = int(cur.fetchone()[0])

    return {
        "status": "success",
        "table": table,
        "total_chunks": total_chunks,
        "force": force,
    }


def _knowledge_sources() -> list[tuple[str, Path]]:
    """Return all source files and retrieval categories."""
    knowledge_dir = Path(BASE_DIR) / "knowledge"
    projects_dir = knowledge_dir / "projects"

    sources: list[tuple[str, Path]] = [
        ("resume", knowledge_dir / "resume.md"),
        ("resume", knowledge_dir / "aboutme.md"),
        ("skills", knowledge_dir / "skills.md"),
    ]

    if projects_dir.exists():
        for project_file in sorted(projects_dir.glob("*.md")):
            sources.append(("projects", project_file))

    # Optional profile assets (for example, LinkedIn profile exports) can be
    # dropped into knowledge/ as PDFs and will be indexed automatically.
    for profile_asset in sorted(knowledge_dir.glob("*.pdf")):
        sources.append((_categorize_profile_asset(profile_asset), profile_asset))

    return sources


def _build_local_index() -> list[Chunk]:
    chunks: list[Chunk] = []
    for row in _chunk_rows():
        chunks.append(
            Chunk(
                text=row["text"],
                source=row["source"],
                category=row["category"],
                tokens=_tokenize(row["text"]),
            )
        )
    return chunks


def _get_local_index() -> list[Chunk]:
    global _CHUNKS_CACHE
    with _CHUNKS_LOCK:
        if _CHUNKS_CACHE is None:
            _CHUNKS_CACHE = _build_local_index()
        return _CHUNKS_CACHE


def _retrieve_local(query: str, category: str, top_k: int) -> list[dict]:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    query_lower = query.lower()
    scored: list[tuple[float, Chunk]] = []
    
    for chunk in _get_local_index():
        if category and chunk.category != category:
            continue
        
        # Token overlap score
        overlap = len(query_tokens & chunk.tokens)
        max_overlap = max(len(query_tokens), len(chunk.tokens))
        
        if overlap == 0:
            # Check for substring matches as fallback
            chunk_lower = chunk.text.lower()
            if query_lower not in chunk_lower:
                # Try individual tokens as substrings
                token_substrings = sum(1 for t in query_tokens if t in chunk_lower)
                if token_substrings == 0:
                    continue  # No match at all
                overlap = token_substrings * 0.5  # Penalize substring matches
            else:
                overlap = len(query_tokens) * 0.8  # Bonus for full substring match
        
        # Calculate final score (Jaccard-like + bonuses)
        score = overlap / max_overlap if max_overlap > 0 else 0.0
        scored.append((score, chunk))
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)
    result = []
    for score, chunk in scored[:top_k]:
        result.append(
            {
                "text": chunk.text,
                "source": chunk.source,
                "category": chunk.category,
                "score": round(score, 4),
            }
        )
    return result


def _retrieve_pgvector(query: str, category: str, top_k: int) -> list[dict]:
    """Retrieve chunks using real pgvector cosine similarity search."""
    dsn = os.getenv("PGVECTOR_DSN")
    if not dsn:
        return _retrieve_local(query, category, top_k)

    table = os.getenv("PGVECTOR_TABLE", "knowledge_chunks")
    dim = int(os.getenv("PGVECTOR_EMBEDDING_DIM", "768"))

    try:
        with psycopg.connect(dsn) as conn:
            # Query-time retrieval is read-only. Index sync should happen during
            # startup via index_pgvector_documents().

            query_embedding = _embed_text(query)
            if len(query_embedding) != dim:
                raise RuntimeError(
                    "Query embedding dimension mismatch. "
                    f"Expected {dim}, got {len(query_embedding)}."
                )
            vector_literal = _to_vector_literal(query_embedding)

            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        source,
                        category,
                        content,
                        (1 - (embedding <=> %s::vector)) AS score
                    FROM {table}
                    WHERE category = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vector_literal, category, vector_literal, top_k),
                )
                rows = cur.fetchall()

            return [
                {
                    "text": content,
                    "source": source,
                    "category": row_category,
                    "score": round(float(score), 4),
                }
                for source, row_category, content, score in rows
            ]
    except Exception:
        # Keep assistant available even if vector infra is misconfigured.
        return _retrieve_local(query, category, top_k)


def _retrieve_vertex(query: str, category: str, top_k: int) -> list[dict]:
    """Retrieve chunks using Vertex AI Vector Search.

    This function currently falls back to local retrieval unless Vertex index
    resources are configured.
    """
    # TODO: Implement true Vertex Vector Search retrieval with index endpoint.
    # Expected env/config:
    # - VERTEX_VECTOR_INDEX_ENDPOINT
    # - VERTEX_VECTOR_DEPLOYED_INDEX_ID
    # - GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION
    _ = query, category, top_k
    return _retrieve_local(query, category, top_k)


def retrieve_context(query: str, category: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Retrieve top relevant context chunks for a query and category.

    Args:
        query: User question to retrieve against.
        category: One of "skills", "resume", or "projects".
        top_k: Number of chunks to return.

    Returns:
        Dict with retrieved chunks and merged context text.
    """
    normalized_category = category.strip().lower()
    if normalized_category not in {"skills", "resume", "projects"}:
        return {
            "status": "error",
            "message": "category must be one of: skills, resume, projects",
        }

    if not query.strip():
        return {"status": "error", "message": "query cannot be empty"}

    top_k = max(1, min(int(top_k or DEFAULT_TOP_K), 10))

    backend = os.getenv("RAG_BACKEND", "local").strip().lower()
    if backend not in {"local", "pgvector", "vertex"}:
        backend = "local"

    if backend == "pgvector":
        cached_chunks = _get_cached_retrieval(
            backend=backend,
            category=normalized_category,
            query=query,
            top_k=top_k,
        )
        if cached_chunks is not None:
            chunks = cached_chunks
        else:
            chunks = _retrieve_pgvector(query, normalized_category, top_k)
            _set_cached_retrieval(
                backend=backend,
                category=normalized_category,
                query=query,
                top_k=top_k,
                chunks=chunks,
            )
    elif backend == "vertex":
        chunks = _retrieve_vertex(query, normalized_category, top_k)
    else:
        chunks = _retrieve_local(query, normalized_category, top_k)

    if not chunks:
        return {
            "status": "success",
            "backend": backend,
            "chunks": [],
            "context": "",
            "message": "No relevant chunks found.",
        }

    context = "\n\n".join(
        [
            (
                f"[source: {chunk['source']} | category: {chunk['category']} | "
                f"score: {chunk['score']}]\n{chunk['text']}"
            )
            for chunk in chunks
        ]
    )
    return {
        "status": "success",
        "backend": backend,
        "chunks": chunks,
        "context": context,
    }


def retrieve_skills_context(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Retrieve skill-related chunks relevant to the user question."""
    return retrieve_context(query=query, category="skills", top_k=top_k)


def retrieve_resume_context(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Retrieve resume/background-related chunks relevant to the user question."""
    return retrieve_context(query=query, category="resume", top_k=top_k)


def retrieve_project_context(query: str, top_k: int = DEFAULT_TOP_K) -> dict:
    """Retrieve project-related chunks relevant to the user question."""
    return retrieve_context(query=query, category="projects", top_k=top_k)

def is_question_on_topic(question: str) -> bool:
    """Check if a question is about Kate's professional experience.

    Args:
        question: The user's question.

    Returns:
        True if the question appears to be about Kate's professional profile.
    """
    question_lower = question.lower()
    # Check for on-topic keywords
    for keyword in ON_TOPIC_KEYWORDS:
        if keyword in question_lower:
            return True
    # If no keywords found, consider it off-topic
    return False


def get_skills() -> dict:
    """Gets Kate's core technical skills and competencies.

    Returns:
        A dict containing the technical skills classified by category.
    """
    path = os.path.join(BASE_DIR, "knowledge", "skills.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read skills: {str(e)}"}

def get_aboutme() -> dict:
    """Gets background information about Kate.

    Returns:
        A dict containing Kate's professional summary.
    """
    path = os.path.join(BASE_DIR, "knowledge", "aboutme.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read aboutme: {str(e)}"}

def get_resume() -> dict:
    """Gets Kate's full professional resume including experience, education, publications, and certifications.

    Returns:
        A dict containing Kate's complete resume text.
    """
    path = os.path.join(BASE_DIR, "knowledge", "resume.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read resume: {str(e)}"}

def get_projects_list() -> dict:
    """Gets a list of projects Kate has worked on.

    Returns:
        A dict containing a list of project names.
    """
    projects_dir = os.path.join(BASE_DIR, "knowledge", "projects")
    try:
        if not os.path.exists(projects_dir):
            return {"status": "success", "projects": []}
        projects = [f.replace(".md", "") for f in os.listdir(projects_dir) if f.endswith(".md")]
        return {"status": "success", "projects": projects}
    except Exception as e:
        return {"status": "error", "message": f"Could not list projects: {str(e)}"}

def get_project_details(project_name: str) -> dict:
    """Gets detailed information about a specific project including role, problem, contributions, and technologies used.

    Args:
        project_name: The name of the project (e.g. 'lamabot', 'babyyoda', 'ticketclassification').

    Returns:
        A dict containing the details of the project.
    """
    # Normalize project name
    name = project_name.lower().strip().replace(" ", "")
    path = os.path.join(BASE_DIR, "knowledge", "projects", f"{name}.md")
    try:
        if not os.path.exists(path):
            return {"status": "error", "message": f"Project '{project_name}' not found."}
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"status": "success", "content": content}
    except Exception as e:
        return {"status": "error", "message": f"Could not read project details: {str(e)}"}
