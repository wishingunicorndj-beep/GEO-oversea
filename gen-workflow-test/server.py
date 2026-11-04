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
import cgi
import json
import os
import re
import subprocess
import sys
import traceback
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, unquote

BASE = Path(__file__).resolve().parent
SCRIPTS = BASE / "scripts"
CLIENTS = BASE / "clients"
OUTPUT = BASE / "output"
REPORT = BASE / "report"

MAX_BODY = 200 * 1024 * 1024          # 单次上传上限 200MB
ALLOWED_EXT = {".docx", ".xlsx", ".txt", ".md", ".csv", ".pdf"}
MODEL_CONFIG = Path.home() / "Documents/GitHub/kb-cleaning-workbench/nano.local.json"

SLUG_RE = re.compile(r"^[a-z0-9_]{2,40}$")


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

    rules = []
    for r in d.get("rules") or []:
        item = dict(r)
        item["category_label"] = label.get(r.get("category"), r.get("category"))
        item["polarity_label"] = pol.get(r.get("polarity"), r.get("polarity"))
        item["enforcement_label"] = enf.get(r.get("enforcement"), r.get("enforcement"))
        rules.append(item)
    rules.sort(key=lambda x: (order.index(x["category"]) if x.get("category") in order else 99, x.get("id", "")))

    used = set((d.get("meta", {}).get("extraction", {}) or {}).get("source_files") or [])
    man = read_manifest(cdir)
    sources = [{"name": m["source_file"], "chars": m["chars"]} for m in man if m["source_file"] in used]
    excluded = [m["source_file"] for m in man if used and m["source_file"] not in used]

    return {
        "client": {"name": d["meta"].get("client_name"), "short": d["meta"].get("client_short"),
                   "version": d["meta"].get("version"), "note": d["meta"].get("note", "")},
        "stats": d.get("stats") or {},
        "source_files": sources,
        "excluded_files": excluded,
        "extraction": d["meta"].get("extraction") or {},
        "rules": rules,
        "conflicts": d.get("conflicts") or [],
        "not_rules": d.get("not_rules") or [],
        "slug": slug,
    }


class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(REPORT), **kwargs)

    # ---------------- 安全 ----------------
    def host_allowed(self):
        host = self.headers.get("Host", "")
        return host in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

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
            cfg_ok = MODEL_CONFIG.exists()
            return json_out(self, 200, {
                "ok": True,
                "model_config": str(MODEL_CONFIG) if cfg_ok else None,
                "model_config_ok": cfg_ok,
                "clients": len([p for p in CLIENTS.iterdir() if p.is_dir() and not p.name.startswith("_")]) if CLIENTS.exists() else 0,
            })

        if path == "/api/clients":
            items = []
            if CLIENTS.exists():
                for p in sorted(CLIENTS.iterdir()):
                    if not p.is_dir() or p.name.startswith("_"):
                        continue
                    items.append({
                        "slug": p.name,
                        "has_docs": (p / "_docs" / "_manifest.json").exists(),
                        "has_draft": (p / "_draft.json").exists(),
                        "has_rules": (p / "rules.yaml").exists(),
                        "updated": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                    })
            return json_out(self, 200, {"items": items})

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

        m = re.match(r"^/api/download/([a-z0-9_]+)/(rules|workflow)$", path)
        if m:
            slug, kind = m.group(1), m.group(2)
            try:
                cdir = client_dir(slug)
            except ValueError as e:
                return json_out(self, 400, {"error": str(e)})
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
        m = re.match(r"^/api/rules/([a-z0-9_]+)/save$", path)
        if m:
            return self.api_save_rules(m.group(1))
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

        env = {"REQUEST_METHOD": "POST", "CONTENT_TYPE": ctype, "CONTENT_LENGTH": str(size)}
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=env)

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
        if not MODEL_CONFIG.exists():
            return json_out(self, 500, {"error": f"找不到模型配置 {MODEL_CONFIG}"})

        # 1. 转文本
        ok, out = run_script([SCRIPTS / "extract_client_docs.py", cdir / "_raw", "--out", cdir / "_docs"], timeout=300)
        if not ok:
            return json_out(self, 500, {"error": "资料转文本失败", "detail": out})

        # 2. 模型抽取
        cmd = [SCRIPTS / "extract_rules.py", cdir / "_docs", "--out", cdir / "_draft.json"]
        if exclude:
            cmd += ["--exclude", *exclude]
        ok, out = run_script(cmd, timeout=1800)
        if not ok:
            return json_out(self, 500, {"error": "规则抽取失败", "detail": out})

        # 3. 转规则包
        ok, out2 = run_script([SCRIPTS / "draft_to_rules.py", cdir / "_draft.json",
                               "--slug", slug, "--client-name", client["name"],
                               "--client-short", client["short"], "--out", cdir / "rules.yaml"], timeout=300)
        if not ok:
            return json_out(self, 500, {"error": "规则包生成失败", "detail": out2})

        return json_out(self, 200, {"ok": True, "slug": slug, "log": out[-2000:] + "\n" + out2[-1000:]})

    def api_save_rules(self, slug):
        try:
            body = self.read_json()
        except Exception as e:
            return json_out(self, 400, {"error": str(e)})
        try:
            cdir = client_dir(slug)
        except ValueError as e:
            return json_out(self, 400, {"error": str(e)})
        rp = cdir / "rules.yaml"
        if not rp.exists():
            return json_out(self, 404, {"error": "规则包不存在"})

        kept = body.get("kept")
        if not isinstance(kept, dict):
            return json_out(self, 400, {"error": "缺少 kept 映射"})

        import yaml
        doc = yaml.safe_load(rp.read_text(encoding="utf-8"))
        removed = []
        new_rules = []
        for r in doc.get("rules") or []:
            if kept.get(r.get("id"), True):
                new_rules.append(r)
            else:
                removed.append(r.get("id"))
        doc["rules"] = new_rules
        doc["meta"]["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        doc["meta"]["removed_rules"] = removed

        from collections import Counter
        doc["stats"]["total"] = len(new_rules)
        doc["stats"]["by_category"] = dict(Counter(r["category"] for r in new_rules))
        doc["stats"]["by_polarity"] = dict(Counter(r["polarity"] for r in new_rules))
        doc["stats"]["by_enforcement"] = dict(Counter(r["enforcement"] for r in new_rules))
        doc["stats"]["delivery_excluded"] = sum(1 for r in new_rules if r["category"] == "delivery")

        header = (
            "# 客户规则包（人工评审后保存）\n"
            f"# 评审时间: {doc['meta']['reviewed_at']}\n"
            f"# 移除 {len(removed)} 条: {', '.join(removed) if removed else '无'}\n\n"
        )
        rp.write_text(header + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=4000),
                      encoding="utf-8")
        return json_out(self, 200, {"ok": True, "kept": len(new_rules), "removed": removed})

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8901)
    args = ap.parse_args()

    CLIENTS.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
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
