#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""持久化层：文件为工作区，数据库为持久层。

设计取舍
--------
现有代码（含 4 个脚本）全程按文件读写，共 21 处 IO。全部改成数据库代价大、
风险高，而且脚本要在本地命令行直接跑。所以采用「文件 + 数据库」双层：

  - 写入：先落文件（现有逻辑不变），再同步到数据库
  - 启动：从数据库把文件材料化（materialize）回去，解决容器重启丢数据
  - 读取：仍然读文件，不改变任何现有路径

数据库不可用时整体降级为纯文件模式，只记一条日志，不影响功能 ——
与 kb-cleaning-workbench 的做法一致。

驱动自适应：生产用 MySQL（pymysql），本地没有 MySQL 时用 SQLite 同库同表验证逻辑。

表全部加 gw_ 前缀，与 kb_cleaning 库中原有的 workspace* 表隔离。
"""
import json
import os
import sqlite3
import threading
from pathlib import Path

try:
    import pymysql
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False


class DBUnavailable(Exception):
    """数据库未配置或连不上。调用方据此降级为纯文件模式。"""


SCHEMA_MYSQL = [
    """CREATE TABLE IF NOT EXISTS gw_client (
        slug VARCHAR(64) PRIMARY KEY,
        name VARCHAR(512) NOT NULL DEFAULT '',
        short_name VARCHAR(255) NOT NULL DEFAULT '',
        created_at VARCHAR(32) NOT NULL DEFAULT '',
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS gw_client_asset (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        slug VARCHAR(64) NOT NULL,
        kind VARCHAR(32) NOT NULL,
        name VARCHAR(512) NOT NULL DEFAULT '',
        content LONGBLOB NOT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_slug_kind_name (slug, kind, name),
        KEY idx_slug (slug)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS gw_batch (
        batch_id VARCHAR(64) PRIMARY KEY,
        slug VARCHAR(64) NOT NULL,
        label VARCHAR(512) NOT NULL DEFAULT '',
        article_count INT NOT NULL DEFAULT 0,
        rules_version VARCHAR(64) NOT NULL DEFAULT '',
        rules_count INT NOT NULL DEFAULT 0,
        violate INT NOT NULL DEFAULT 0,
        hard_violate INT NOT NULL DEFAULT 0,
        unclear INT NOT NULL DEFAULT 0,
        pass_rate DOUBLE NOT NULL DEFAULT 0,
        created_at VARCHAR(32) NOT NULL DEFAULT '',
        KEY idx_slug_created (slug, created_at)
    ) CHARACTER SET utf8mb4""",
    """CREATE TABLE IF NOT EXISTS gw_batch_asset (
        id BIGINT PRIMARY KEY AUTO_INCREMENT,
        batch_id VARCHAR(64) NOT NULL,
        kind VARCHAR(32) NOT NULL,
        content LONGBLOB NOT NULL,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        UNIQUE KEY uk_batch_kind (batch_id, kind),
        KEY idx_batch (batch_id)
    ) CHARACTER SET utf8mb4""",
]

SCHEMA_SQLITE = [
    """CREATE TABLE IF NOT EXISTS gw_client (
        slug TEXT PRIMARY KEY, name TEXT DEFAULT '', short_name TEXT DEFAULT '',
        created_at TEXT DEFAULT '', updated_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS gw_client_asset (
        id INTEGER PRIMARY KEY AUTOINCREMENT, slug TEXT NOT NULL, kind TEXT NOT NULL,
        name TEXT DEFAULT '', content BLOB NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(slug, kind, name))""",
    """CREATE TABLE IF NOT EXISTS gw_batch (
        batch_id TEXT PRIMARY KEY, slug TEXT NOT NULL, label TEXT DEFAULT '',
        article_count INTEGER DEFAULT 0, rules_version TEXT DEFAULT '', rules_count INTEGER DEFAULT 0,
        violate INTEGER DEFAULT 0, hard_violate INTEGER DEFAULT 0, unclear INTEGER DEFAULT 0,
        pass_rate REAL DEFAULT 0, created_at TEXT DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS gw_batch_asset (
        id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, kind TEXT NOT NULL,
        content BLOB NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(batch_id, kind))""",
]


def settings():
    """从环境变量读连接配置。未配置返回 None（纯文件模式）。"""
    host = (os.environ.get("GW_DB_HOST") or "").strip()
    if not host:
        # 兼容 Ship 容器内的常见变量名
        for key in ("MYSQL_HOST", "DB_HOST"):
            host = (os.environ.get(key) or "").strip()
            if host:
                break
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("GW_DB_PORT") or os.environ.get("MYSQL_PORT") or 3306),
        "user": (os.environ.get("GW_DB_USER") or os.environ.get("MYSQL_USER") or "").strip(),
        "password": os.environ.get("GW_DB_PASSWORD") or os.environ.get("MYSQL_PASSWORD") or "",
        "database": (os.environ.get("GW_DB_NAME") or os.environ.get("MYSQL_DATABASE")
                     or "ship_u133_kb_cleaning").strip(),
    }


class Store:
    """统一读写接口。MySQL 与 SQLite 两种后端，SQL 方言差异在这里吸收。"""

    def __init__(self, cfg=None, sqlite_path=None):
        self.cfg = cfg or settings()
        self.sqlite_path = sqlite_path
        self.backend = ""
        self._lock = threading.Lock()
        self._conn = None
        self.detail = ""

    # ---------- 连接 ----------
    def connect(self):
        if self._conn is not None:
            # 复用前先探活，避免拿着一个已断的 socket 反复失败
            if self.backend == "mysql":
                try:
                    self._conn.ping(reconnect=True)
                    return self._conn
                except Exception:
                    self._reset()
            else:
                return self._conn
        if self.cfg and HAS_PYMYSQL:
            try:
                self._conn = pymysql.connect(
                    host=self.cfg["host"], port=self.cfg["port"],
                    user=self.cfg["user"], password=self.cfg["password"],
                    database=self.cfg["database"], charset="utf8mb4",
                    autocommit=True, connect_timeout=8,
                )
                self.backend = "mysql"
                self._init_schema(SCHEMA_MYSQL)
                self.detail = f"MySQL {self.cfg['host']}:{self.cfg['port']}/{self.cfg['database']}"
                return self._conn
            except Exception as e:
                self._conn = None
                raise DBUnavailable(f"{type(e).__name__}: {str(e)[:160]}")

        if not self.sqlite_path:
            raise DBUnavailable("未配置数据库（设置 GW_DB_HOST 等环境变量）")

        self._conn = sqlite3.connect(str(self.sqlite_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.backend = "sqlite"
        self._init_schema(SCHEMA_SQLITE)
        self.detail = f"SQLite {self.sqlite_path}"
        return self._conn

    def _init_schema(self, statements):
        cur = self._conn.cursor()
        for sql in statements:
            cur.execute(sql)
        self._conn.commit()

    def status(self):
        try:
            self.connect()
            return True, self.detail
        except DBUnavailable as e:
            return False, str(e)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"

    def _reset(self):
        """丢弃当前连接，下次 connect() 重建。"""
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None

    def _exec(self, sql, args=(), retry=True):
        """执行 SQL。

        MySQL 连接在空闲后被服务端断开很常见（默认 wait_timeout 8 小时，
        但网关也可能提前掐断）。缓存的连接一旦失效，后续全部静默失败，
        所以这里检测到连接类错误就重连一次。
        """
        with self._lock:
            conn = self.connect()
            try:
                cur = conn.cursor()
                cur.execute(sql, args)
                rows = cur.fetchall() if cur.description else []
                if self.backend == "sqlite":
                    conn.commit()
                return rows
            except Exception as e:
                # 2006 lost connection / 2013 gone away / 0 InterfaceError
                name = type(e).__name__
                code = getattr(e, "args", [None])[0] if e.args else None
                connection_broken = (
                    name in ("InterfaceError", "OperationalError") or code in (0, 2006, 2013)
                )
                self._reset()
                if retry and connection_broken:
                    return self._exec(sql, args, retry=False)
                raise

    def _upsert(self, table, keys, values, update_cols):
        """跨方言 upsert：先 UPDATE，无影响行再 INSERT。

        keys 已在 values 里，所以 INSERT 的列直接取 values.keys()，
        不能再拼 keys —— 否则 MySQL 会报 "Column specified twice"。
        """
        mark = "?" if self.backend == "sqlite" else "%s"
        where = " AND ".join(f"{k}={mark}" for k in keys)
        key_args = [values[k] for k in keys]
        set_clause = ", ".join(f"{c}={mark}" for c in update_cols)

        self._exec(f"UPDATE {table} SET {set_clause} WHERE {where}",
                   [values[c] for c in update_cols] + key_args)

        cur = self._conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", key_args)
        row = cur.fetchone()
        if (row[0] if row else 0):
            return

        cols = list(values.keys())
        ph = ",".join(mark for _ in cols)
        self._exec(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({ph})",
                   [values[c] for c in cols])

    # ---------- 客户 ----------
    def save_client(self, slug, name, short, created_at=""):
        self._upsert("gw_client", ["slug"],
                     {"slug": slug, "name": name, "short_name": short,
                      "created_at": created_at},
                     ["name", "short_name"])

    def save_client_asset(self, slug, kind, name, content):
        """kind: raw（原始上传）/ doc（转出文本）/ draft / rules"""
        if isinstance(content, str):
            content = content.encode("utf-8")
        self._upsert("gw_client_asset", ["slug", "kind", "name"],
                     {"slug": slug, "kind": kind, "name": name, "content": content},
                     ["content"])

    def delete_client_asset_kind(self, slug, kind):
        self._exec("DELETE FROM gw_client_asset WHERE slug=" +
                   ("?" if self.backend == "sqlite" else "%s") + " AND kind=" +
                   ("?" if self.backend == "sqlite" else "%s"), (slug, kind))

    # ---------- 批次 ----------
    def save_batch(self, slug, batch_id, meta, assets):
        self._upsert("gw_batch", ["batch_id"], {
            "batch_id": batch_id, "slug": slug,
            "label": meta.get("label", ""),
            "article_count": int(meta.get("article_count") or 0),
            "rules_version": meta.get("rules_version", ""),
            "rules_count": int(meta.get("rules_count") or 0),
            "violate": int(meta.get("violate") or 0),
            "hard_violate": int(meta.get("hard_violate") or 0),
            "unclear": int(meta.get("unclear") or 0),
            "pass_rate": float(meta.get("pass_rate") or 0),
            "created_at": meta.get("created_at", ""),
        }, ["label", "article_count", "rules_version", "rules_count",
            "violate", "hard_violate", "unclear", "pass_rate"])
        for kind, content in (assets or {}).items():
            if isinstance(content, str):
                content = content.encode("utf-8")
            self._upsert("gw_batch_asset", ["batch_id", "kind"],
                         {"batch_id": batch_id, "kind": kind, "content": content},
                         ["content"])

    def list_batches(self, slug):
        ph = "?" if self.backend == "sqlite" else "%s"
        rows = self._exec(
            f"SELECT batch_id,label,article_count,rules_version,rules_count,"
            f"violate,hard_violate,unclear,pass_rate,created_at "
            f"FROM gw_batch WHERE slug={ph} ORDER BY created_at DESC", (slug,))
        out = []
        for r in rows:
            d = dict(r) if isinstance(r, dict) or hasattr(r, "keys") else {
                "batch_id": r[0], "label": r[1], "article_count": r[2],
                "rules_version": r[3], "rules_count": r[4], "violate": r[5],
                "hard_violate": r[6], "unclear": r[7], "pass_rate": r[8],
                "created_at": r[9]}
            d["id"] = d.get("batch_id")
            out.append(d)
        return out

    def get_batch_assets(self, batch_id):
        ph = "?" if self.backend == "sqlite" else "%s"
        rows = self._exec(f"SELECT kind,content FROM gw_batch_asset WHERE batch_id={ph}",
                          (batch_id,))
        return {r[0]: r[1] for r in rows}

    def list_clients(self):
        rows = self._exec("SELECT slug,name,short_name,created_at FROM gw_client")
        return [{"slug": r[0], "name": r[1], "short_name": r[2], "created_at": r[3]}
                for r in rows]

    def client_assets(self, slug):
        ph = "?" if self.backend == "sqlite" else "%s"
        rows = self._exec(
            f"SELECT kind,name,content FROM gw_client_asset WHERE slug={ph}", (slug,))
        return [{"kind": r[0], "name": r[1], "content": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# 文件 ⇄ 数据库 同步
# ---------------------------------------------------------------------------
KIND_BY_PATH = [
    ("_raw", "raw"), ("_docs", "doc"),
]


def _kind_for(rel):
    parts = set(rel.parts)
    if "_raw" in parts:
        return "raw"
    if "_docs" in parts:
        return "doc"
    if rel.name.endswith("rules.yaml"):
        return "rules"
    if rel.name.endswith("_draft.json"):
        return "draft"
    if rel.name == "_client.json":
        return "client"
    return "other"


def sync_client_to_db(store, cdir, slug):
    """把单个客户目录同步进数据库。失败不抛，由调用方决定是否记录。"""
    files = []
    for sub in ("_raw", "_docs"):
        d = cdir / sub
        if d.exists():
            for p in sorted(d.iterdir()):
                if p.is_file() and not p.name.startswith("."):
                    files.append(p)
    for name in ("rules.yaml", "_draft.json", "_client.json"):
        p = cdir / name
        if p.exists():
            files.append(p)

    meta = {}
    mp = cdir / "_client.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    store.save_client(slug, meta.get("name", ""), meta.get("short", ""),
                      meta.get("uploaded_at", ""))

    for p in files:
        rel = p.relative_to(cdir)
        kind = _kind_for(rel)
        try:
            store.save_client_asset(slug, kind, str(rel), p.read_bytes())
        except Exception as e:
            return False, f"{p.name}: {type(e).__name__}: {e}"
    return True, f"{len(files)} 个文件"


def sync_batch_to_db(store, bdir, slug):
    mf = bdir / "meta.json"
    if not mf.exists():
        return False, "缺 meta.json"
    meta = json.loads(mf.read_text(encoding="utf-8"))
    assets = {}
    for name, kind in (("articles.json", "articles"),
                       ("report.json", "report"),
                       ("rules_snapshot.yaml", "rules_snapshot"),
                       ("judge_results.json", "judge_results"),
                       ("meta.json", "meta")):
        p = bdir / name
        if p.exists():
            assets[kind] = p.read_bytes()
    store.save_batch(slug, bdir.name, meta, assets)
    return True, f"{len(assets)} 个文件"


def materialize_all(store, clients_root):
    """启动时把数据库里的记录写回文件系统。返回 (客户数, 批次数, 错误列表)。"""
    n_clients = n_batches = 0
    errors = []
    for c in store.list_clients():
        slug = c["slug"]
        cdir = clients_root / slug
        cdir.mkdir(parents=True, exist_ok=True)
        try:
            (cdir / "_client.json").write_text(json.dumps({
                "slug": slug, "name": c["name"], "short": c["short_name"],
                "uploaded_at": c["created_at"],
            }, ensure_ascii=False, indent=1), encoding="utf-8")

            for a in store.client_assets(slug):
                dest = cdir / a["name"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(a["content"])
            n_clients += 1
        except Exception as e:
            errors.append(f"{slug}: {type(e).__name__}: {e}")
            continue

        try:
            for b in store.list_batches(slug):
                bdir = cdir / "batches" / b["batch_id"]
                bdir.mkdir(parents=True, exist_ok=True)
                fmts = {"articles.json", "report.json", "rules_snapshot.yaml",
                        "judge_results.json", "meta.json"}
                for kind, content in store.get_batch_assets(b["batch_id"]).items():
                    name = {"articles": "articles.json", "report": "report.json",
                            "rules_snapshot": "rules_snapshot.yaml",
                            "judge_results": "judge_results.json",
                            "meta": "meta.json"}.get(kind)
                    if name in fmts:
                        (bdir / name).write_bytes(content)
                n_batches += 1
        except Exception as e:
            errors.append(f"{slug}/batches: {type(e).__name__}: {e}")
    return n_clients, n_batches, errors
