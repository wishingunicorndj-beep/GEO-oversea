#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GEO 定制工作流服务：客户资料上传 → 规则抽取 → 工作流生成。

启动：
  python3 server.py                    # 默认 http://127.0.0.1:8901
  python3 server.py --port 8901

接口：
  GET  /api/status                    服务状态与配置检查
  GET  /api/clients                   已处理客户列表
  POST /api/upload                    上传客户资料（multipart）
  POST /api/extract                   对已上传资料跑规则抽取
  GET  /api/rules/<slug>              读取规则包（评审页数据）
  POST /api/rules/<slug>/save         保存评审结果（勾选保留/取消）
  POST /api/build/<slug>              生成定制工作流 yml
  GET  /api/download/<slug>/<kind>    下载 yml 或 rules.yaml

安全约束（沿用知识库清洗工作台的做法）：
  - 只监听本机；Host 头校验；同源 Origin 校验
  - 上传大小上限；文件名白名单扩展名；落盘路径强制在 clients/ 内
  - 不回显任何密钥
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

import db as dblayer

BASE = Path(__file__).resolve().parent
SCRIPTS = BASE / "scripts"
CLIENTS = BASE / "clients"
OUTPUT = BASE / "output"
REPORT = BASE / "report"

MAX_BODY = 200 * 1024 * 1024          # 单次上传上限 200MB
ALLOWED_EXT = {".docx", ".xlsx", ".txt", ".md", ".csv", ".pdf"}
# 模型配置：容器里用环境变量，本地开发读本机文件
MODEL_CONFIG = Path.home() / "Documents/GitHub/kb-cleaning-workbench/nano.local.json"
CONFIG_CANDIDATES = [
    BASE / "nano.local.json",
    MODEL_CONFIG,
]
CHROME_PATHS = [
    os.environ.get("GEO_CHROME", ""),
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

SLUG_RE = re.compile(r"^[a-z0-9_]{2,40}$")

# 抽取与评估都要跑模型，耗时 3-8 分钟且吃 CPU。同一时间只允许一个重任务，
# 否则多人同时上传会互相拖慢甚至把容器压死。
# 抽取与评估都要跑模型，耗时 3-8 分钟。网关 60 秒就断，所以必须异步：
# 接口立即返回 task_id，前端轮询 /api/task/<id>。同一时间只跑一个重任务。
HEAVY_TASK = threading.Lock()
HEAVY_INFO = {"kind": "", "slug": "", "started": ""}

TASKS = {}
TASKS_LOCK = threading.Lock()
TASK_TTL = 3600  # 任务记录保留 1 小时


def new_task(kind, slug):
    tid = f"{datetime.now().strftime('%H%M%S')}-{abs(hash((kind, slug, datetime.now()))) % 10000:04d}"
    with TASKS_LOCK:
        # 清理过期任务
        cutoff = time.time() - TASK_TTL
        for k in [k for k, v in TASKS.items() if v.get("_ts", 0) < cutoff]:
            TASKS.pop(k, None)
        TASKS[tid] = {
            "id": tid, "kind": kind, "slug": slug,
            "status": "running", "step": "准备中", "progress": 5,
            "log": "", "error": "", "result": None,
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "_ts": time.time(),
        }
    return tid


def update_task(tid, **kw):
    with TASKS_LOCK:
        if tid in TASKS:
            TASKS[tid].update(kw)
            TASKS[tid]["_ts"] = time.time()


def get_task(tid):
    with TASKS_LOCK:
        t = TASKS.get(tid)
        return dict(t) if t else None


def run_task(tid, fn):
    """在后台线程执行，把结果写回任务状态。"""
    def worker():
        try:
            update_task(tid, step="执行中", progress=15)
            result = fn(tid)
            update_task(tid, status="done", progress=100, step="完成", result=result)
        except Exception as e:
            import traceback
            update_task(tid, status="failed", step="失败",
                        error=f"{type(e).__name__}: {e}",
                        log=traceback.format_exc()[-2000:])
        finally:
            HEAVY_INFO.update({"kind": "", "slug": "", "started": ""})
            if HEAVY_TASK.locked():
                try:
                    HEAVY_TASK.release()
                except RuntimeError:
                    pass
    t = threading.Thread(target=worker, daemon=True)
    t.start()

# 持久层：文件为工作区，数据库为持久层。未配置数据库时降级为纯文件模式。
_store = None


def store():
    global _store
    if _store is None:
        _store = dblayer.Store(sqlite_path=BASE / "workspace.db"
                               if not dblayer.settings() else None)
    return _store


DB_LAST_ERROR = {"at": "", "error": ""}


def persist(fn, *args, **kwargs):
    """数据库同步：失败不回滚主流程，但必须留下痕迹。

    之前这里只 print，而容器日志被网关探活的噪音淹没，导致「写库一直失败」
    无人察觉 —— 重启后数据全丢才发现。现在把错误记进 DB_LAST_ERROR，
    由 /api/status 暴露出来。
    """
    try:
        r = fn(*args, **kwargs)
        DB_LAST_ERROR["error"] = ""
        return r
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        DB_LAST_ERROR.update({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "error": msg})
        print(f"[db] 同步失败: {msg}", flush=True)
        return None


class FormPart:
    """模拟 cgi.FieldStorage 的最小接口，只暴露本服务用到的部分。

    value：普通字段解码成 str；文件字段为 None。
    file ：统一返回可 read() 的字节流。
    """
    def __init__(self, name, filename, data):
        self.name = name
        self.filename = filename
        self._data = data
        if filename is None:
            self.value = data.decode("utf-8", "replace")
        else:
            self.value = None

    @property
    def file(self):
        return _BytesFile(self._data)


class _BytesFile:
    def __init__(self, data):
        self._buf = data
        self._pos = 0

    def read(self, n=-1):
        if n is None or n < 0:
            out = self._buf[self._pos:]
            self._pos = len(self._buf)
            return out
        out = self._buf[self._pos:self._pos + n]
        self._pos += len(out)
        return out


class Form(dict):
    """multipart/form-data 解析结果。

    自实现的原因：cgi 模块在 3.13 已移除，不能长期依赖。
    只支持本服务用得到的部分：普通字段 + 文件字段，不处理嵌套。
    """

    def getvalue(self, key, default=None):
        v = self.get(key)
        if v is None:
            return default
        if isinstance(v, list):
            return default
        return v.value if v.value is not None else default

    def getall(self, key):
        v = self.get(key)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]


def parse_multipart(handler, content_type):
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return Form()

    m = re.search(r'boundary="?([^";]+)"?', content_type)
    if not m:
        raise ValueError("缺少 multipart boundary")
    boundary = m.group(1).encode()

    body = handler.rfile.read(length)
    delim = b"--" + boundary
    form = Form()

    for chunk in body.split(delim):
        if not chunk or chunk in (b"--\r\n", b"--", b"\r\n"):
            continue
        chunk = chunk.lstrip(b"\r\n")
        if chunk.startswith(b"--"):
            break
        head_end = chunk.find(b"\r\n\r\n")
        if head_end < 0:
            continue
        raw_headers = chunk[:head_end].decode("utf-8", "replace")
        data = chunk[head_end + 4:]
        if data.endswith(b"\r\n"):
            data = data[:-2]

        name = filename = None
        am = re.search(r'name="([^"]*)"', raw_headers)
        if am:
            name = am.group(1)
        fm = re.search(r'filename="([^"]*)"', raw_headers)
        if fm:
            filename = fm.group(1)
        if not name:
            continue

        part = FormPart(name, filename, data)
        if name in form:
            prev = form[name]
            form[name] = (prev if isinstance(prev, list) else [prev]) + [part]
        else:
            form[name] = part
    return form


# 纯文本粘贴的分篇标记：既接受 markdown 标题，也接受显式分隔行。
_ARTICLE_SPLIT = re.compile(
    r"^(?:#{1,3}\s+.+|={3,}|-{3,}|\*{3,})\s*$", re.M)


def articles_from_plain_text(text):
    """把「标题 + 正文」的纯文本切成 [{title, content}]。

    支持三种写法，混用也能识别：
      1. 每篇首行是标题，空行后接正文；篇与篇之间用 --- 或 === 分隔
      2. Markdown 标题行（## 标题）开始新的一篇
      3. 多个标题块之间靠空行自然分隔
    返回空列表表示没识别出可用内容。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    def flush(chunks, buf):
        if "\n".join(buf).strip():
            chunks.append("\n".join(buf))
        return []

    # 一级/二级 Markdown 标题天然是篇边界；纯分隔行（--- === ***）也是边界
    chunks, buf = [], []
    for line in text.split("\n"):
        s = line.strip()
        if re.fullmatch(r"[=\-*]{3,}", s):
            buf = flush(chunks, buf)
            continue
        if re.match(r"^#{1,2}\s+\S", s):
            buf = flush(chunks, buf)
        buf.append(line)
    flush(chunks, buf)

    articles = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            continue

        head = lines[0].strip()
        head = re.sub(r"^#{1,6}\s*", "", head).strip().strip("*_").strip()
        rest = "\n".join(lines[1:]).strip()

        looks_like_title = (
            rest
            and 0 < len(head) <= 80
            and "\n" not in head
            and not head.startswith(("http", "<"))
        )
        if looks_like_title:
            articles.append({"title": head, "content": rest})
        else:
            articles.append({"title": "", "content": chunk})

    return [a for a in articles if a["content"].strip()]


def json_out(handler, code, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def safe_slug(s):
    return bool(s and SLUG_RE.match(s))


def client_dir(slug):
    d = (CLIENTS / slug).resolve()
    if CLIENTS.resolve() not in d.parents and d != CLIENTS.resolve():
        raise ValueError("非法客户标识")
    return d


def list_batches(cdir):
    """列出该客户的全部批次，按时间倒序。"""
    bdir = cdir / "batches"
    if not bdir.exists():
        return []
    items = []
    for p in sorted(bdir.iterdir(), reverse=True):
        if not p.is_dir():
            continue
        mf = p / "meta.json"
        if not mf.exists():
            continue
        try:
            meta = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append({**meta, "id": p.name, "has_report": (p / "report.json").exists()})
    return items


def find_chrome():
    for p in CHROME_PATHS:
        if p and os.path.exists(p):
            return p
    from shutil import which
    return which("google-chrome") or which("chromium") or which("chromium-browser") or ""


def html_to_pdf(html_path, pdf_path, timeout=90):
    """用无头 Chrome 把 HTML 转成 PDF。失败返回 (False, 原因)。"""
    chrome = find_chrome()
    if not chrome:
        return False, "未找到 Chrome/Chromium，无法生成 PDF"
    cmd = [chrome, "--headless", "--disable-gpu", "--no-sandbox",
           "--disable-dev-shm-usage", "--no-pdf-header-footer",
           f"--print-to-pdf={pdf_path}", "--virtual-time-budget=5000",
           Path(html_path).resolve().as_uri()]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if not Path(pdf_path).exists() or Path(pdf_path).stat().st_size < 1024:
            return False, (r.stderr or "")[-400:]
        return True, ""
    except subprocess.TimeoutExpired:
        return False, f"PDF 生成超时（{timeout}s）"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def new_batch_id():
    """批次 id：时间戳，可排序且不重复。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")



def run_script(args, timeout=1200):
    """执行脚本，返回 (ok, stdout+stderr)。"""
    try:
        r = subprocess.run([sys.executable] + [str(a) for a in args],
                           capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out[-6000:]
    except subprocess.TimeoutExpired:
        return False, f"执行超时（{timeout}s）"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def read_manifest(cdir):
    p = cdir / "_docs" / "_manifest.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def rules_to_page(cdir, slug):
    """把 rules.yaml 转成评审页需要的 JSON。"""
    import yaml
    sys.path.insert(0, str(SCRIPTS))
    try:
        import rule_schema as rs
    finally:
        sys.path.pop(0)

    rp = cdir / "rules.yaml"
    if not rp.exists():
        return None
    d = yaml.safe_load(rp.read_text(encoding="utf-8"))

    label = {"identity": "实体称谓", "fact": "事实口径", "prohibition": "禁止事项",
             "stance": "自我定位", "scope": "业务边界", "voice": "口吻体裁",
             "structure": "文章结构", "citation": "数据引用", "delivery": "交付流程"}
    order = ["prohibition", "identity", "fact", "citation", "scope", "structure", "voice", "stance", "delivery"]
    pol = {"must": "必须", "must_not": "不得", "may": "允许", "prefer": "建议"}
    enf = {"code": "代码可判", "llm": "模型判定", "human": "人工流程"}

    rules, dismissed = [], []
    for r in d.get("rules") or []:
        item = dict(r)
        item["category_label"] = label.get(r.get("category"), r.get("category"))
        item["polarity_label"] = pol.get(r.get("polarity"), r.get("polarity"))
        item["enforcement_label"] = enf.get(r.get("enforcement"), r.get("enforcement"))
        item["is_manual"] = r.get("origin") == "manual"
        (dismissed if r.get("status") == "dismissed" else rules).append(item)
    rules.sort(key=lambda x: (order.index(x["category"]) if x.get("category") in order else 99, x.get("id", "")))
    dismissed.sort(key=lambda x: x.get("id", ""))

    used = set((d.get("meta", {}).get("extraction", {}) or {}).get("source_files") or [])
    man = read_manifest(cdir)
    sources = [{"name": m["source_file"], "chars": m["chars"]} for m in man if m["source_file"] in used]
    excluded = [m["source_file"] for m in man if used and m["source_file"] not in used]

    conflicts = d.get("conflicts") or []
    return {
        "client": {"name": d["meta"].get("client_name"), "short": d["meta"].get("client_short"),
                   "version": d["meta"].get("version"), "note": d["meta"].get("note", ""),
                   "is_draft": "draft" in str(d["meta"].get("version") or "")},
        "stats": d.get("stats") or {},
        "source_files": sources,
        "excluded_files": excluded,
        "extraction": d["meta"].get("extraction") or {},
        "rules": rules,
        "dismissed_rules": dismissed,
        "conflicts": conflicts,
        "conflicts_pending": len(rs.pending_conflicts(d)),
        "conflicts_active": len(rs.active_conflicts(d)),
        "not_rules": d.get("not_rules") or [],
        "slug": slug,
        "next_rule_id": rs.next_rule_id(d.get("rules") or [], slug),
    }


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPORT), **kwargs)

    # ---------------- 安全 ----------------
    def host_allowed(self):
        host = self.headers.get("Host", "")
        # 本机访问始终允许
        if host in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"):
            return True
        # 部署到内网域名/K8s 网关时，用 GEO_ALLOWED_HOSTS 放行（逗号分隔）
        allowed = os.environ.get("GEO_ALLOWED_HOSTS", "")
        if allowed:
            hosts = [h.strip() for h in allowed.split(",") if h.strip()]
            if "*" in hosts or host in hosts:
                return True
            # 允许匹配 Host 的主机名部分（忽略端口）
            hostname = host.split(":")[0]
            if hostname in hosts:
                return True
        return False

    def origin_allowed(self):
        origin = self.headers.get("Origin", "")
        if not origin:
            return True
        return urlparse(origin).netloc == self.headers.get("Host", "")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin and urlparse(origin).netloc == self.headers.get("Host", ""):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass  # 安静模式，避免刷屏

    def guard(self):
        if not self.host_allowed():
            json_out(self, 403, {"error": "Host 不被允许"})
            return False
        if not self.origin_allowed():
            json_out(self, 403, {"error": "跨站请求被拒绝"})
            return False
        return True

    def read_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > 4 * 1024 * 1024:
            raise ValueError("请求体为空或过大")
        return json.loads(self.rfile.read(size))

    # ---------------- GET ----------------
    def do_GET(self):
        if not self.guard():
            return
        path = unquote(urlparse(self.path).path)

        if path == "/api/status":
            # 环境变量齐全也算配置好 —— 容器部署只给环境变量，没有配置文件
            env_ok = all(os.environ.get(k) for k in
                         ("AI_PARSE_BASE_URL", "AI_PARSE_AUTHORIZATION", "AI_PARSE_MODEL"))
            cfg_ok = MODEL_CONFIG.exists() or env_ok or (BASE / "nano.local.json").exists()
            db_ok, db_detail = store().status()
            return json_out(self, 200, {
                "ok": True,
                "model_config": str(MODEL_CONFIG) if cfg_ok else None,
                "model_config_ok": cfg_ok,
                "db_ok": db_ok,
                "db_detail": db_detail,
                "db_last_error": DB_LAST_ERROR["error"],
                "db_last_error_at": DB_LAST_ERROR["at"],
                "clients": len([p for p in CLIENTS.iterdir() if p.is_dir() and not p.name.startswith("_")]) if CLIENTS.exists() else 0,
            })

        m = re.match(r"^/api/task/([0-9]{6}-[0-9]{4})$", path)
        if m:
            t = get_task(m.group(1))
            if not t:
                return json_out(self, 404, {"error": "任务不存在或已过期"})
            return json_out(self, 200, t)

        if path == "/api/task":
            return json_out(self, 200, {
                "busy": HEAVY_TASK.locked(),
                **HEAVY_INFO,
            })

        if path == "/api/diag":
            # 诊断用：直接读数据库，绕开文件系统
            out = {"db_ok": False, "detail": "", "clients": [], "batches": {},
                   "client_assets": {}, "error": ""}
            try:
                st = store()
                ok, detail = st.status()
                out["db_ok"], out["detail"] = ok, detail
                if ok:
                    out["clients"] = st.list_clients()
                    for c in out["clients"]:
                        slug_c = c["slug"]
                        out["batches"][slug_c] = st.list_batches(slug_c)
                        out["client_assets"][slug_c] = [
                            a["name"] for a in st.client_assets(slug_c)]
            except Exception as e:
                out["error"] = f"{type(e).__name__}: {e}"
            return json_out(self, 200, out)

        if path == "/api/clients":
            items = []
            if CLIENTS.exists():
                for p in sorted(CLIENTS.iterdir()):
                    if not p.is_dir() or p.name.startswith("_"):
                        continue
                    rp = p / "rules.yaml"
                    rule_count = 0
                    rule_version = ""
                    if rp.exists():
                        try:
                            import yaml
                            doc = yaml.safe_load(rp.read_text(encoding="utf-8")) or {}
                            sys.path.insert(0, str(SCRIPTS))
                            try:
                                import rule_schema as rs
                            finally:
                                sys.path.pop(0)
                            rule_count = len(rs.active_rules(doc))
                            rule_version = (doc.get("meta") or {}).get("version", "")
                        except Exception:
                            pass
                    batches = 0
                    bdir = p / "batches"
                    if bdir.exists():
                        batches = len([x for x in bdir.iterdir() if x.is_dir()])
                    items.append({
                        "slug": p.name,
                        "has_docs": (p / "_docs" / "_manifest.json").exists(),
                        "has_draft": (p / "_draft.json").exists(),
                        "has_rules": rp.exists(),
                        "rule_count": rule_count,
                        "rule_version": rule_version,
                        "batch_count": batches,
                        "updated": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
            return json_out(self, 200, {"items": items})

        m = re.match(r"^/api/batches/([a-z0-9_]+)$", path)
        if m:
            slug = m.group(1)
            try:
                cdir = client_dir(slug)
            except ValueError as e:
                return json_out(self, 400, {"error": str(e)})
            return json_out(self, 200, {"items": list_batches(cdir)})

        m = re.match(r"^/api/batch/([a-z0-9_]+)/([A-Za-z0-9_\-]+)$", path)
        if m:
            slug, bid = m.group(1), m.group(2)
            try:
                cdir = client_dir(slug)
            except ValueError as e:
                return json_out(self, 400, {"error": str(e)})
            bdir = cdir / "batches" / bid
            if not bdir.is_dir():
                return json_out(self, 404, {"error": "批次不存在"})
            rep = bdir / "report.json"
            if not rep.exists():
                return json_out(self, 404, {"error": "该批次还没有报告"})
            return json_out(self, 200, json.loads(rep.read_text(encoding="utf-8")))

        m = re.match(r"^/api/rules/([a-z0-9_]+)$", path)
        if m:
            slug = m.group(1)
            try:
                data = rules_to_page(client_dir(slug), slug)
            except Exception as e:
                return json_out(self, 400, {"error": str(e)})
            if data is None:
                return json_out(self, 404, {"error": "该客户还没有规则包"})
            return json_out(self, 200, data)

        m = re.match(r"^/api/board/([a-z0-9_]+)/([A-Za-z0-9_\-]+)$", path)
        if m:
            slug, bid = m.group(1), m.group(2)
            try:
                cdir = client_dir(slug)
            except ValueError as e:
                return json_out(self, 400, {"error": str(e)})
            bdir = cdir / "batches" / bid
            if not (bdir / "report.json").exists():
                return json_out(self, 404, {"error": "该批次还没有报告"})
            query = urlparse(self.path).query or ""
            want_pdf = "format=pdf" in query

            out = bdir / "board.html"
            ok, log = run_script([SCRIPTS / "export_board.py", bdir, "--out", out], timeout=120)
            if not ok:
                return json_out(self, 500, {"error": "看板生成失败", "detail": log})

            from urllib.parse import quote
            if want_pdf:
                pdf = bdir / "board.pdf"
                # 每次都重新生成，避免规则或数据变更后拿到旧文件
                if pdf.exists():
                    pdf.unlink()
                okp, why = html_to_pdf(out, pdf)
                if not okp:
                    return json_out(self, 500, {"error": "PDF 生成失败", "detail": why})
                data = pdf.read_bytes()
                ctype = "application/pdf"
                name = f"{slug}_{bid}_看板.pdf"
                ascii_name = f"{slug}_{bid}_board.pdf"
            else:
                data = out.read_bytes()
                ctype = "text/html; charset=utf-8"
                name = f"{slug}_{bid}_看板.html"
                ascii_name = f"{slug}_{bid}_board.html"

            self.send_response(200)
            self.send_header("Content-Type", ctype)
            if "inline=1" in query:
                self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(name)}")
            else:
                self.send_header("Content-Disposition",
                                 f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        m = re.match(r"^/api/download/([a-z0-9_]+)/(rules|rules-html|workflow)$", path)
        if m:
            slug, kind = m.group(1), m.group(2)
            try:
                cdir = client_dir(slug)
            except ValueError as e:
                return json_out(self, 400, {"error": str(e)})

            if kind == "rules-html":
                # 业务确认用的规则单：按「不能/必须/允许/建议」分组，附冲突与出处
                rp = cdir / "rules.yaml"
                if not rp.exists():
                    return json_out(self, 404, {"error": "规则包不存在"})
                out_html = cdir / "rules_export.html"
                ok_e, log_e = run_script(
                    [SCRIPTS / "export_rules_html.py", rp, "--out", out_html], timeout=120)
                if not ok_e:
                    return json_out(self, 500, {"error": "规则单生成失败", "detail": log_e})
                data = out_html.read_bytes()
                import yaml as _yaml
                _short = (_yaml.safe_load(rp.read_text(encoding="utf-8")) or {}).get("meta", {}).get("client_short", slug)
                from urllib.parse import quote
                fname = f"{_short}_写作规则确认单.html"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                if "inline=1" in (urlparse(self.path).query or ""):
                    self.send_header("Content-Disposition", f"inline; filename*=UTF-8''{quote(fname)}")
                else:
                    self.send_header("Content-Disposition",
                                     f"attachment; filename=\"rules.html\"; filename*=UTF-8''{quote(fname)}")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return

            if kind == "rules":
                f = cdir / "rules.yaml"
            else:
                import yaml
                if not (cdir / "rules.yaml").exists():
                    return json_out(self, 404, {"error": "规则包不存在"})
                short = yaml.safe_load((cdir / "rules.yaml").read_text(encoding="utf-8")).get("meta", {}).get("client_short")
                f = OUTPUT / f"{short}生文.yml"
            if not f.exists():
                return json_out(self, 404, {"error": "文件不存在"})
            data = f.read_bytes()
            # HTTP 头只能用 latin-1；中文文件名须用 RFC 5987 的 filename* 形式
            from urllib.parse import quote
            ascii_name = f"{f.stem.encode('ascii', 'ignore').decode() or 'file'}{f.suffix}"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header(
                "Content-Disposition",
                f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(f.name)}",
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path.startswith("/api/"):
            return json_out(self, 404, {"error": "接口不存在"})

        return super().do_GET()

    # ---------------- POST ----------------
    def do_POST(self):
        if not self.guard():
            return
        path = unquote(urlparse(self.path).path)

        if path == "/api/upload":
            return self.api_upload()
        if path == "/api/extract":
            return self.api_extract()
        if path == "/api/evaluate":
            return self.api_evaluate()
        m = re.match(r"^/api/rules/([a-z0-9_]+)/save$", path)
        if m:
            return self.api_save_rules(m.group(1))
        m = re.match(r"^/api/rules/([a-z0-9_]+)/rule$", path)
        if m:
            return self.api_rule_upsert(m.group(1))
        m = re.match(r"^/api/rules/([a-z0-9_]+)/rule/([A-Za-z0-9_\-]+)/dismiss$", path)
        if m:
            return self.api_rule_dismiss(m.group(1), m.group(2))
        m = re.match(r"^/api/rules/([a-z0-9_]+)/rule/([A-Za-z0-9_\-]+)/restore$", path)
        if m:
            return self.api_rule_restore(m.group(1), m.group(2))
        m = re.match(r"^/api/rules/([a-z0-9_]+)/conflicts$", path)
        if m:
            return self.api_conflicts_save(m.group(1))
        m = re.match(r"^/api/rules/([a-z0-9_]+)/promote$", path)
        if m:
            return self.api_rules_promote(m.group(1))
        m = re.match(r"^/api/build/([a-z0-9_]+)$", path)
        if m:
            return self.api_build(m.group(1))
        return json_out(self, 404, {"error": "接口不存在"})

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # ---------------- 业务 ----------------
    def api_upload(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return json_out(self, 400, {"error": "请用 multipart/form-data 上传"})
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > MAX_BODY:
            return json_out(self, 400, {"error": "上传内容为空或超过 200MB"})

        try:
            form = parse_multipart(self, ctype)
        except ValueError as e:
            return json_out(self, 400, {"error": f"表单解析失败：{e}"})

        slug = (form.getvalue("slug") or "").strip().lower()
        name = (form.getvalue("name") or "").strip()
        short = (form.getvalue("short") or "").strip()
        if not safe_slug(slug):
            return json_out(self, 400, {"error": "客户标识只能用小写字母、数字、下划线，2-40 位"})
        if not name or not short:
            return json_out(self, 400, {"error": "客户全称与简称必填"})

        try:
            cdir = client_dir(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})

        raw_dir = cdir / "_raw"
        raw_dir.mkdir(parents=True, exist_ok=True)

        files = form["files"] if "files" in form else []
        if not isinstance(files, list):
            files = [files]

        saved, skipped = [], []
        for item in files:
            if not getattr(item, "filename", None):
                continue
            fname = os.path.basename(item.filename)
            ext = Path(fname).suffix.lower()
            if ext not in ALLOWED_EXT:
                skipped.append({"file": fname, "why": f"不支持 {ext}"})
                continue
            dest = raw_dir / fname
            data = item.file.read()
            if len(data) > 50 * 1024 * 1024:
                skipped.append({"file": fname, "why": "单文件超过 50MB"})
                continue
            dest.write_bytes(data)
            saved.append({"file": fname, "size": len(data)})

        if not saved:
            return json_out(self, 400, {"error": "没有可用的文件", "skipped": skipped})

        meta_path = cdir / "_client.json"
        meta_path.write_text(json.dumps(
            {"slug": slug, "name": name, "short": short,
             "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M")},
            ensure_ascii=False, indent=1), encoding="utf-8")

        persist(dblayer.sync_client_to_db, store(), cdir, slug)

        return json_out(self, 200, {"ok": True, "slug": slug, "saved": saved, "skipped": skipped})

    def api_extract(self):
        try:
            body = self.read_json()
        except Exception as e:
            return json_out(self, 400, {"error": str(e)})

        slug = (body.get("slug") or "").strip().lower()
        if not safe_slug(slug):
            return json_out(self, 400, {"error": "非法客户标识"})
        exclude = body.get("exclude") or []
        exclude = [str(x) for x in exclude if re.match(r"^[0-9]{2}_$", str(x))]

        try:
            cdir = client_dir(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})
        meta_path = cdir / "_client.json"
        if not meta_path.exists():
            return json_out(self, 400, {"error": "该客户还没有上传资料"})
        client = json.loads(meta_path.read_text(encoding="utf-8"))
        cfg = Path(MODEL_CONFIG)
        has_env = all(os.environ.get(k) for k in
                      ("AI_PARSE_BASE_URL", "AI_PARSE_AUTHORIZATION", "AI_PARSE_MODEL"))
        if not cfg.exists() and not has_env and not (BASE / "nano.local.json").exists():
            return json_out(self, 500, {"error": "模型未配置：请设置 AI_PARSE_BASE_URL / "
                                                 "AI_PARSE_AUTHORIZATION / AI_PARSE_MODEL 环境变量"})

        if not HEAVY_TASK.acquire(blocking=False):
            return json_out(self, 409, {
                "error": f"已有任务在执行（{HEAVY_INFO.get('kind')} · {HEAVY_INFO.get('slug')}），请稍后重试",
                "busy": True, **HEAVY_INFO,
            })
        HEAVY_INFO.update({"kind": "规则抽取", "slug": slug,
                           "started": datetime.now().strftime("%H:%M:%S")})

        tid = new_task("规则抽取", slug)

        def job(t_id):
            return self._do_extract(t_id, cdir, slug, exclude, client)

        run_task(tid, job)
        # 立即返回，前端轮询 /api/task/<id>
        return json_out(self, 202, {"ok": True, "task_id": tid, "status": "running",
                                    "poll": f"/api/task/{tid}"})

    def _do_extract(self, tid, cdir, slug, exclude, client):

        # 1. 转文本
        update_task(tid, step="资料转文本", progress=20)
        ok, out = run_script([SCRIPTS / "extract_client_docs.py", cdir / "_raw", "--out", cdir / "_docs"], timeout=300)
        if not ok:
            raise RuntimeError("资料转文本失败：" + out[-800:])

        # 2. 模型抽取
        update_task(tid, step="模型抽取规则（约 3-6 分钟）", progress=35)
        cmd = [SCRIPTS / "extract_rules.py", cdir / "_docs", "--out", cdir / "_draft.json"]
        if exclude:
            cmd += ["--exclude", *exclude]
        ok, out = run_script(cmd, timeout=1800)
        if not ok:
            raise RuntimeError("规则抽取失败：" + out[-800:])
        update_task(tid, step="生成规则包", progress=80, log=out[-1500:])

        # 3. 转规则包
        ok, out2 = run_script([SCRIPTS / "draft_to_rules.py", cdir / "_draft.json",
                               "--slug", slug, "--client-name", client["name"],
                               "--client-short", client["short"], "--out", cdir / "rules.yaml"], timeout=300)
        if not ok:
            raise RuntimeError("规则包生成失败：" + out2[-800:])

        persist(dblayer.sync_client_to_db, store(), cdir, slug)

        cnt = 0
        try:
            import yaml as _y
            cnt = len((_y.safe_load((cdir / "rules.yaml").read_text(encoding="utf-8")) or {}).get("rules") or [])
        except Exception:
            pass
        return {"slug": slug, "rule_count": cnt, "log": out[-1500:] + "\n" + out2[-800:]}

    # ---------------- 规则包写操作 ----------------
    def _rules_ctx(self, slug):
        """读取规则包并返回 (cdir, doc, yaml)。不存在时抛 ValueError。"""
        import yaml
        try:
            cdir = client_dir(slug)
        except ValueError as e:
            raise ValueError(str(e))
        rp = cdir / "rules.yaml"
        if not rp.exists():
            raise ValueError("规则包不存在")
        doc = yaml.safe_load(rp.read_text(encoding="utf-8")) or {}
        return cdir, doc, yaml

    def _write_rules(self, cdir, doc, slug, note=""):
        """落盘 + 重算统计 + 同步数据库 + 重建评估器。

        重建评估器是必须的：评估器内嵌了规则副本，不重建的话
        新加/改过的规则在验收时完全不会生效。
        """
        sys.path.insert(0, str(SCRIPTS))
        try:
            import rule_schema as rs
        finally:
            sys.path.pop(0)

        import yaml
        rs.recompute_stats(doc)
        import os as _os
        cdir = Path(cdir)
        tmp = cdir / "rules.yaml.tmp"
        tmp.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=4000),
                       encoding="utf-8")
        _os.replace(tmp, cdir / "rules.yaml")

        ev = cdir / "evaluate.py"
        ok, out = run_script([SCRIPTS / "build_client_evaluator.py", cdir / "rules.yaml",
                              "--out", ev], timeout=120)
        persist(dblayer.sync_client_to_db, store(), cdir, slug)
        return ok, out

    def _rule_error(self, errs):
        return json_out(self, 400, {"error": "；".join(errs), "errors": errs})

    def api_save_rules(self, slug):
        """批量设置保留/移除。移除走软删除：规则留在 yaml 里但不再注入与判定。"""
        try:
            body = self.read_json()
        except Exception as e:
            return json_out(self, 400, {"error": str(e)})
        try:
            cdir, doc, yaml = self._rules_ctx(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})

        kept = body.get("kept")
        if not isinstance(kept, dict):
            return json_out(self, 400, {"error": "缺少 kept 映射"})

        removed, restored = [], []
        for r in doc.get("rules") or []:
            rid = r.get("id")
            if rid not in kept:
                continue
            if kept[rid]:
                if r.get("status") == "dismissed":
                    r.pop("status", None)
                    r.pop("dismissed_at", None)
                    restored.append(rid)
            else:
                if r.get("status") != "dismissed":
                    r["status"] = "dismissed"
                    r["dismissed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                    removed.append(rid)

        doc.setdefault("meta", {})["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        ok, out = self._write_rules(cdir, doc, slug)
        if not ok:
            return json_out(self, 500, {"error": "规则已保存，但评估器重建失败", "detail": out[-800:]})
        return json_out(self, 200, {"ok": True, "removed": removed, "restored": restored})

    def api_rule_upsert(self, slug):
        """新增或编辑一条规则。人工录入只允许模型判定类（enforcement=llm）。"""
        try:
            body = self.read_json()
        except Exception as e:
            return json_out(self, 400, {"error": str(e)})
        try:
            cdir, doc, yaml = self._rules_ctx(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})

        sys.path.insert(0, str(SCRIPTS))
        try:
            import rule_schema as rs
        finally:
            sys.path.pop(0)

        raw = body.get("rule") or {}
        mode = body.get("mode") or "create"
        rules = doc.get("rules") or []

        rule = {
            "id": (raw.get("id") or "").strip(),
            "category": (raw.get("category") or "").strip(),
            "polarity": (raw.get("polarity") or "").strip(),
            "severity": (raw.get("severity") or "").strip(),
            "scope": raw.get("scope") or ["title", "body"],
            "statement": (raw.get("statement") or "").strip(),
            "scope_note": (raw.get("scope_note") or "").strip(),
            "enforcement": "llm",          # 人工录入固定为模型判定，避免填了 detect 却判不出来
            "origin": "manual",
            "evidence": "人工录入",
            "source_file": "人工录入",
        }
        for k in ("condition", "alternative", "status"):
            if raw.get(k):
                rule[k] = raw[k].strip() if isinstance(raw[k], str) else raw[k]
        exs = [e for e in (raw.get("examples") or [])
               if isinstance(e, dict) and (e.get("wrong") or e.get("right"))]
        if exs:
            rule["examples"] = exs

        if mode == "create":
            candidate = rs.next_rule_id(rules, slug)
            if not rule["id"] or rule["id"] in {r.get("id") for r in rules}:
                rule["id"] = candidate
            others = {r.get("id") for r in rules}
            errs = rs.validate_rule(rule, all_ids=others, for_manual_input=True)
            if errs:
                return self._rule_error(errs)
            rules.append(rule)
        else:
            target = next((r for r in rules if r.get("id") == rule["id"]), None)
            if not target:
                return json_out(self, 404, {"error": f"规则 {rule['id']} 不存在"})
            others = {r.get("id") for r in rules if r.get("id") != rule["id"]}
            errs = rs.validate_rule(rule, all_ids=others, for_manual_input=True)
            if errs:
                return self._rule_error(errs)
            # 保留不可在界面编辑的字段
            for k in ("status", "dismissed_at", "detect", "needs_source"):
                if k in target and k not in rule:
                    rule[k] = target[k]
            if target.get("origin") != "manual":
                rule["origin"] = "extracted"
            idx = rules.index(target)
            rules[idx] = rule

        doc["rules"] = rules
        doc.setdefault("meta", {})["edited_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        ok, out = self._write_rules(cdir, doc, slug)
        if not ok:
            return json_out(self, 500, {"error": "规则已保存，但评估器重建失败", "detail": out[-800:]})
        return json_out(self, 200, {"ok": True, "rule": rule,
                                    "next_rule_id": rs.next_rule_id(rules, slug)})

    def api_rule_dismiss(self, slug, rid):
        """软删除一条规则：保留记录，标记 dismissed，不再注入与判定。"""
        try:
            cdir, doc, yaml = self._rules_ctx(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})
        target = next((r for r in (doc.get("rules") or []) if r.get("id") == rid), None)
        if not target:
            return json_out(self, 404, {"error": f"规则 {rid} 不存在"})
        target["status"] = "dismissed"
        target["dismissed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        ok, out = self._write_rules(cdir, doc, slug)
        if not ok:
            return json_out(self, 500, {"error": "规则已保存，但评估器重建失败", "detail": out[-800:]})
        return json_out(self, 200, {"ok": True, "id": rid})

    def api_rule_restore(self, slug, rid):
        """恢复一条软删除的规则。"""
        try:
            cdir, doc, yaml = self._rules_ctx(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})
        target = next((r for r in (doc.get("rules") or []) if r.get("id") == rid), None)
        if not target:
            return json_out(self, 404, {"error": f"规则 {rid} 不存在"})
        target.pop("status", None)
        target.pop("dismissed_at", None)
        ok, out = self._write_rules(cdir, doc, slug)
        if not ok:
            return json_out(self, 500, {"error": "规则已保存，但评估器重建失败", "detail": out[-800:]})
        return json_out(self, 200, {"ok": True, "id": rid})

    def api_conflicts_save(self, slug):
        """保存冲突裁决。人工选口径后可直接应用到某条规则的指定字段。"""
        try:
            body = self.read_json()
        except Exception as e:
            return json_out(self, 400, {"error": str(e)})
        try:
            cdir, doc, yaml = self._rules_ctx(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})

        sys.path.insert(0, str(SCRIPTS))
        try:
            import rule_schema as rs
        finally:
            sys.path.pop(0)

        incoming = body.get("conflicts")
        if not isinstance(incoming, list):
            return json_out(self, 400, {"error": "缺少 conflicts 数组"})

        # 以 topic 为主键合并：前端只提交改动过的项，未提交的保持原样
        current = doc.get("conflicts") or []
        by_topic = {c.get("topic"): c for c in current}
        applied = []
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        for inc in incoming:
            topic = inc.get("topic")
            if topic not in by_topic:
                continue
            item = by_topic[topic]
            res = dict(inc.get("resolution") or {})
            decision = res.get("decision")
            if decision not in (None, "accept_a", "accept_b", "custom", "dismissed"):
                return json_out(self, 400, {"error": f"「{topic}」的裁决取值非法：{decision}"})
            if decision == "custom" and not str(res.get("custom_text") or "").strip():
                return json_out(self, 400, {"error": f"「{topic}」选择自定义口径时，必须填写内容"})
            if decision:
                res["resolved_at"] = res.get("resolved_at") or now
                item["resolution"] = res

            # 可选的「应用到规则」：裁决不会自动改规则，必须显式指定目标与字段
            apply = inc.get("apply") or {}
            rid, field = apply.get("rule_id"), apply.get("field")
            if rid and field and decision in ("accept_a", "accept_b", "custom"):
                if field not in ("statement", "condition", "scope_note"):
                    return json_out(self, 400, {"error": f"不能写入字段 {field}"})
                target = next((r for r in (doc.get("rules") or []) if r.get("id") == rid), None)
                if not target:
                    return json_out(self, 404, {"error": f"规则 {rid} 不存在"})
                text = {"accept_a": item.get("party_a"), "accept_b": item.get("party_b"),
                        "custom": res.get("custom_text")}.get(decision) or ""
                if text.strip():
                    # 被替换的原文留在 history 里，规则包仍能回答「这条边界为什么这么写」
                    history = target.setdefault("field_history", [])
                    history.append({
                        "field": field,
                        "before": target.get(field, ""),
                        "after": text.strip(),
                        "from_conflict": topic,
                        "at": now,
                    })
                    target[field] = text.strip()
                    if target.get("origin") != "manual":
                        target["origin"] = "extracted+reviewed"
                    applied.append({"rule_id": rid, "field": field})

        errs = rs.validate_rule_set(doc.get("rules") or [], for_manual_input=False)
        blocking = [e for e in errs if "不能为空" in e]
        if blocking:
            return self._rule_error(blocking + ["（裁决应用后规则字段为空，已拒绝保存）"])

        doc.setdefault("meta", {})["conflicts_reviewed_at"] = now
        ok, out = self._write_rules(cdir, doc, slug)
        if not ok:
            return json_out(self, 500, {"error": "裁决已保存，但评估器重建失败", "detail": out[-800:]})
        return json_out(self, 200, {"ok": True, "applied": applied,
                                    "pending": len(rs.pending_conflicts(doc))})

    def api_rules_promote(self, slug):
        """确认转正：去掉版本号里的 -draft。"""
        try:
            cdir, doc, yaml = self._rules_ctx(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})

        meta = doc.setdefault("meta", {})
        version = str(meta.get("version") or "")
        if "draft" not in version:
            return json_out(self, 400, {"error": f"当前版本 {version} 已经是正式版"})

        sys.path.insert(0, str(SCRIPTS))
        try:
            import rule_schema as rs
        finally:
            sys.path.pop(0)

        pending = rs.pending_conflicts(doc)
        if pending:
            return json_out(self, 400, {
                "error": f"还有 {len(pending)} 处冲突未裁决，不能转正",
                "pending": [c.get("topic") for c in pending]})

        active = rs.active_rules(doc)
        errs = rs.validate_rule_set(active, for_manual_input=False)
        if errs:
            return self._rule_error(errs + ["（转正前必须全部修正）"])

        meta["version"] = re.sub(r"-?draft", "", version).strip("-") or "0.1.0"
        meta["promoted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        ok, out = self._write_rules(cdir, doc, slug)
        if not ok:
            return json_out(self, 500, {"error": "已转正，但评估器重建失败", "detail": out[-800:]})
        return json_out(self, 200, {"ok": True, "version": meta["version"]})

    def api_build(self, slug):
        try:
            cdir = client_dir(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})
        rp = cdir / "rules.yaml"
        if not rp.exists():
            return json_out(self, 404, {"error": "规则包不存在，先完成规则评审"})

        import yaml
        doc = yaml.safe_load(rp.read_text(encoding="utf-8"))
        short = doc.get("meta", {}).get("client_short") or doc.get("meta", {}).get("client_id")
        target = OUTPUT / f"{short}生文.yml"

        ok, out = run_script([SCRIPTS / "build_client_workflow.py", rp, "--out", target], timeout=300)
        if not ok:
            return json_out(self, 500, {"error": "工作流生成失败", "detail": out})

        return json_out(self, 200, {
            "ok": True, "slug": slug, "file": target.name,
            "path": str(target.relative_to(BASE)),
            "download": f"/api/download/{slug}/workflow",
            "log": out[-1500:],
        })

    def api_evaluate(self):
        """接收生文输出 JSON，按客户当前规则包评估，落地为一个批次。"""
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return json_out(self, 400, {"error": "请用 multipart/form-data 上传"})
        size = int(self.headers.get("Content-Length", "0"))
        if size < 1 or size > MAX_BODY:
            return json_out(self, 400, {"error": "文件为空或超过 200MB"})

        try:
            form = parse_multipart(self, ctype)
        except ValueError as e:
            return json_out(self, 400, {"error": f"表单解析失败：{e}"})

        slug = (form.getvalue("slug") or "").strip().lower()
        label = (form.getvalue("label") or "").strip()
        if not safe_slug(slug):
            return json_out(self, 400, {"error": "请选择客户"})

        try:
            cdir = client_dir(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})

        rp = cdir / "rules.yaml"
        if not rp.exists():
            return json_out(self, 400, {"error": "该客户还没有规则包，先生成规则包"})
        evaluator = cdir / "evaluate.py"
        if not evaluator.exists():
            ok, out = run_script([SCRIPTS / "build_client_evaluator.py", rp, "--out", evaluator], timeout=120)
            if not ok:
                return json_out(self, 500, {"error": "评估器生成失败", "detail": out})

        # 请求结束时 rfile 会被关闭，后台线程读不到表单。
        # 所以在同步阶段先把文件内容读出来，交给任务线程使用。
        # 两种入口：粘贴文本（text 字段）优先，其次是上传文件（file 字段）。
        pasted = (form.getvalue("text") or "").strip()
        fitem = form["file"] if "file" in form else None
        if pasted:
            raw_bytes = pasted.encode("utf-8")
            fname = "粘贴内容.json"
        elif fitem is not None and getattr(fitem, "filename", None):
            raw_bytes = fitem.file.read()
            fname = os.path.basename(fitem.filename)
        else:
            return json_out(self, 400, {"error": "请粘贴生文输出 JSON，或选择一个 JSON 文件"})
        if len(raw_bytes) > 50 * 1024 * 1024:
            return json_out(self, 400, {"error": "内容超过 50MB"})
        raw_text = raw_bytes.decode("utf-8-sig", "replace")
        if raw_bytes[:5] == b"{\\rtf":
            return json_out(self, 400, {
                "error": "这份文件是 RTF 富文本（可能是用「文本编辑」存成 .rtf 后改了后缀），不是 JSON。"
                         "请直接把标题和正文粘贴到输入框"})

        payload = None
        payload_err = None
        stripped = raw_text.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                payload = json.loads(stripped)
            except ValueError as e:
                payload_err = str(e)
        if payload is None:
            # 不是 JSON：按「标题 + 正文」的纯文本识别
            plain = articles_from_plain_text(raw_text)
            if plain:
                titles = [a["title"] for a in plain]
                payload = {
                    "article_titles": titles,
                    "generated_articles_list": [a["content"] for a in plain],
                }
            elif payload_err:
                return json_out(self, 400, {"error": f"不是合法 JSON，也没识别出文章：{payload_err}"})
            else:
                return json_out(self, 400, {"error": "没有识别出文章内容，请粘贴标题和正文"})

        arts = payload.get("generated_articles_list") or payload.get("articles") or []
        if not isinstance(arts, list) or not arts:
            return json_out(self, 400, {"error": "JSON 里没有 generated_articles_list，或该数组为空"})

        if not HEAVY_TASK.acquire(blocking=False):
            return json_out(self, 409, {
                "error": f"已有任务在执行（{HEAVY_INFO.get('kind')} · {HEAVY_INFO.get('slug')}），请稍后重试",
                "busy": True, **HEAVY_INFO,
            })
        HEAVY_INFO.update({"kind": "验收评估", "slug": slug,
                           "started": datetime.now().strftime("%H:%M:%S")})

        tid = new_task("验收评估", slug)

        def job(t_id):
            return self._do_evaluate(t_id, payload, fname, slug, label, cdir, rp, evaluator)

        run_task(tid, job)
        return json_out(self, 202, {"ok": True, "task_id": tid, "status": "running",
                                    "poll": f"/api/task/{tid}"})

    def _do_evaluate(self, tid, payload, fname, slug, label, cdir, rp, evaluator):
        arts = payload.get("generated_articles_list") or payload.get("articles") or []
        update_task(tid, step="准备批次", progress=10)

        # 新建批次目录
        bid = new_batch_id()
        bdir = cdir / "batches" / bid
        bdir.mkdir(parents=True, exist_ok=True)
        (bdir / "articles.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        import shutil
        import yaml
        shutil.copy2(rp, bdir / "rules_snapshot.yaml")
        rule_doc = yaml.safe_load(rp.read_text(encoding="utf-8")) or {}
        rule_meta = rule_doc.get("meta") or {}

        # 1) 生成模型判定任务 → 执行判定（语义类规则只有这步能判）
        sys.path.insert(0, str(cdir))
        llm_results = []
        judge_log = ""
        judge_warn = ""
        try:
            mod_name = f"evaluate_{slug}"
            spec0 = importlib.util.spec_from_file_location(mod_name, evaluator)
            mod0 = importlib.util.module_from_spec(spec0)
            spec0.loader.exec_module(mod0)

            # SPEC 是 dict，不能用 getattr
            if (mod0.SPEC.get("llm_rules") if isinstance(mod0.SPEC, dict)
                    else getattr(mod0.SPEC, "llm_rules", None)):
                # 生文输出里正文与标题是分开的：generated_articles_list 是纯 HTML，
                # article_titles 按下标对应。必须先合并，否则送给模型的文章是空的。
                bodies = payload.get("generated_articles_list") or []
                titles = payload.get("article_titles") or []
                arts_for_tasks = []
                for i, b in enumerate(bodies):
                    if isinstance(b, dict):
                        arts_for_tasks.append(b)
                    else:
                        arts_for_tasks.append({
                            "title": titles[i] if i < len(titles) else "",
                            "content": b,
                        })
                tasks = mod0.build_llm_tasks(arts_for_tasks)
                tasks_path = bdir / "judge_tasks.json"
                tasks_path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
                results_path = bdir / "judge_results.json"
                update_task(tid, step=f"模型判定中（{len(tasks)} 篇，约 3-8 分钟）", progress=40)
                ok_j, out_j = run_script(
                    [SCRIPTS / "run_judgement.py", tasks_path, "--out", results_path],
                    timeout=3600)
                judge_log = out_j[-800:]
                if ok_j and results_path.exists():
                    llm_results = json.loads(results_path.read_text(encoding="utf-8"))
                else:
                    # 把真实原因带出来，否则只看到一句"未完成"没法排障
                    judge_warn = "模型判定未完成：" + (out_j or "")[-600:]
        finally:
            sys.path.pop(0)

        # 2) 评估器只做代码可判部分；模型判定结果由上一步提供
        update_task(tid, step="汇总报告", progress=92)
        ok, out = run_script([evaluator, bdir / "articles.json"], timeout=600)
        if not ok:
            raise RuntimeError("评估失败：" + out[-800:])

        # 评估器把 Markdown 打到 stdout；报告结构由它内部 evaluate() 产出，
        # 这里重新导入模块拿结构化结果，避免解析文本。
        sys.path.insert(0, str(cdir))
        try:
            mod_name = f"evaluate_{slug}"
            spec = importlib.util.spec_from_file_location(mod_name, evaluator)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            report = mod.evaluate_file(str(bdir / "articles.json"), llm_results or None)
            # 补规则类别标签，供页面分组
            cat = {r["id"]: r.get("category") for r in rule_doc.get("rules") or []}
            label_map = {"identity": "实体称谓", "fact": "事实口径", "prohibition": "禁止事项",
                         "stance": "自我定位", "scope": "业务边界", "voice": "口吻体裁",
                         "structure": "文章结构", "citation": "数据引用", "delivery": "交付流程"}
            for a in report.get("articles") or []:
                for r in a.get("rows") or []:
                    c = cat.get(r.get("rule_id"), "other")
                    r["category"] = c
                    r["category_label"] = label_map.get(c, c)
        except Exception as e:
            raise RuntimeError(f"报告解析失败：{type(e).__name__}: {e}")
        finally:
            sys.path.pop(0)

        report["client"] = rule_meta.get("client_name") or slug
        report["client_short"] = rule_meta.get("client_short") or slug
        report["rules_version"] = rule_meta.get("version", "")
        report["batch_id"] = bid
        report["batch_label"] = label or bid
        report["evaluated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        (bdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        s = report.get("summary") or {}
        (bdir / "meta.json").write_text(json.dumps({
            "batch_id": bid,
            "label": report["batch_label"],
            "created_at": report["evaluated_at"],
            "article_count": report.get("article_count", 0),
            "rules_version": report["rules_version"],
            "rules_count": len(rule_doc.get("rules") or []),
            "violate": s.get("violate", 0),
            "hard_violate": s.get("hard_violate", 0),
            "unclear": s.get("unclear", 0),
            "pass_rate": s.get("pass_rate_of_judged", 0),
        }, ensure_ascii=False, indent=1), encoding="utf-8")

        persist(dblayer.sync_batch_to_db, store(), bdir, slug)

        return {"slug": slug, "batch_id": bid,
                "label": report["batch_label"], "summary": s,
                "judged_rules": len(llm_results),
                "judge_warn": judge_warn,
                "redirect": f"/index.html?slug={slug}&batch={bid}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8901)))
    ap.add_argument("--host", default=os.environ.get("GEO_BIND", "127.0.0.1"),
                    help="监听地址；容器内用 0.0.0.0")
    args = ap.parse_args()

    CLIENTS.mkdir(exist_ok=True)

    # 启动时从数据库恢复文件（容器重启后由这一步还原数据）
    db_ok, db_detail = store().status()
    if db_ok:
        n_c, n_b, errs = dblayer.materialize_all(store(), CLIENTS)
        print(f"数据库: {db_detail}")
        print(f"  已恢复 {n_c} 个客户 / {n_b} 个批次"
              + (f"，{len(errs)} 个错误" if errs else ""))
        for e in errs[:3]:
            print(f"    ! {e}")
    else:
        print(f"数据库: 未启用（{db_detail}）")
        print("  当前为纯文件模式，容器重启会丢失数据")

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"GEO 定制工作流服务已启动")
    print(f"  http://127.0.0.1:{args.port}/upload.html")
    print(f"  模型配置: {'✓ ' + str(MODEL_CONFIG) if MODEL_CONFIG.exists() else '✗ 未找到 ' + str(MODEL_CONFIG)}")
    print("  Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
