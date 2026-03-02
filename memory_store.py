"""
Memory Store — SQLite FTS5 full-text search over CLAWS memory files.

Indexes all Markdown files under memory/ and provides:
- Full-text search with relevance ranking
- Time-decay weighting (newer files rank higher)
- Incremental re-indexing (only changed files)

Zero external dependencies — uses Python's built-in sqlite3 with FTS5.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("CLAWS.memory")

CST = timezone(timedelta(hours=8))


class MemoryStore:
    """SQLite FTS5 backed full-text search over memory/ Markdown files."""

    def __init__(self, memory_dir: Path, db_path: Optional[Path] = None):
        self.memory_dir = memory_dir
        self.db_path = db_path or (memory_dir / ".memory_index.db")
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                hash TEXT NOT NULL,
                file_date TEXT,
                indexed_at TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                path, title, content,
                tokenize='unicode61'
            );
        """)
        self._conn.commit()

    def _file_hash(self, path: Path) -> str:
        return hashlib.md5(path.read_bytes()).hexdigest()

    def _extract_date(self, path: Path) -> str:
        stem = path.stem
        if len(stem) >= 10:
            try:
                datetime.strptime(stem[:10], "%Y-%m-%d")
                return stem[:10]
            except ValueError:
                pass
        return datetime.now(CST).strftime("%Y-%m-%d")

    def _extract_title(self, content: str) -> str:
        for line in content.split("\n")[:5]:
            line = line.strip()
            if line.startswith("# "):
                return line[2:].strip()
        return ""

    def reindex(self) -> int:
        """Scan memory/ and index new or changed Markdown files. Returns count of files indexed."""
        indexed = 0
        seen_paths: set[str] = set()

        for md in self.memory_dir.rglob("*.md"):
            rel = str(md.relative_to(self.memory_dir))
            if rel.startswith("."):
                continue
            seen_paths.add(rel)

            current_hash = self._file_hash(md)
            row = self._conn.execute("SELECT hash FROM files WHERE path = ?", (rel,)).fetchone()
            if row and row[0] == current_hash:
                continue

            content = md.read_text(encoding="utf-8", errors="replace")
            title = self._extract_title(content)
            file_date = self._extract_date(md)

            if row:
                self._conn.execute("DELETE FROM memory_fts WHERE path = ?", (rel,))
                self._conn.execute(
                    "UPDATE files SET hash = ?, file_date = ?, indexed_at = ? WHERE path = ?",
                    (current_hash, file_date, datetime.now(CST).isoformat(), rel),
                )
            else:
                self._conn.execute(
                    "INSERT INTO files (path, hash, file_date, indexed_at) VALUES (?, ?, ?, ?)",
                    (rel, current_hash, file_date, datetime.now(CST).isoformat()),
                )

            self._conn.execute(
                "INSERT INTO memory_fts (path, title, content) VALUES (?, ?, ?)",
                (rel, title, content[:10000]),
            )
            indexed += 1

        existing = {r[0] for r in self._conn.execute("SELECT path FROM files").fetchall()}
        removed = existing - seen_paths
        for rel in removed:
            self._conn.execute("DELETE FROM files WHERE path = ?", (rel,))
            self._conn.execute("DELETE FROM memory_fts WHERE path = ?", (rel,))
            indexed += 1

        if indexed > 0:
            self._conn.commit()
            log.info(f"记忆索引更新: {indexed} 文件")

        return indexed

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Full-text search with time-decay weighting.

        Returns list of {path, title, snippet, file_date, score}.
        """
        if not query.strip():
            return []

        self.reindex()

        try:
            rows = self._conn.execute("""
                SELECT
                    m.path,
                    m.title,
                    snippet(memory_fts, 2, '>>>', '<<<', '...', 60) as snippet,
                    f.file_date,
                    rank
                FROM memory_fts m
                JOIN files f ON m.path = f.path
                WHERE memory_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, top_k * 3)).fetchall()
        except sqlite3.OperationalError:
            log.warning(f"FTS5 查询失败: {query}")
            return []

        now = datetime.now(CST)
        results = []
        for path, title, snippet, file_date, fts_rank in rows:
            try:
                fd = datetime.strptime(file_date, "%Y-%m-%d").replace(tzinfo=CST)
                days_ago = (now - fd).days
            except (ValueError, TypeError):
                days_ago = 30

            decay = 1.0 / (1.0 + days_ago * 0.1)
            final_score = abs(fts_rank) * decay

            results.append({
                "path": path,
                "title": title,
                "snippet": snippet,
                "file_date": file_date,
                "score": round(final_score, 4),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def format_context(self, query: str, top_k: int = 5) -> str:
        """Search and format results for injection into Agent prompts."""
        results = self.search(query, top_k)
        if not results:
            return ""

        lines = [f"[相关记忆 - 检索词: {query}]"]
        for r in results:
            lines.append(f"  [{r['file_date']}] {r['title'] or r['path']}")
            lines.append(f"    {r['snippet']}")
        return "\n".join(lines)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
