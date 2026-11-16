#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量执行客户规则判定：把评估器生成的任务送给模型，回收结构化结论。

用法：
  python3 scripts/run_judgement.py /tmp/qh_tasks.json --out /tmp/qh_llm_results.json
  python3 scripts/run_judgement.py tasks.json --config nano.local.json --model xxx
  python3 scripts/run_judgement.py tasks.json --dry-run      # 只估算调用量与费用

设计约束：
  - 一篇一次调用，20 条规则批量判定，输入量约为逐条调用的 1/20。
  - 强制 JSON 数组输出；单条失败不影响整批，失败项记为 error 供重试。
  - 只读配置，不打印任何密钥。
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_CONFIG_CANDIDATES = [
    Path.home() / "Documents/GitHub/kb-cleaning-workbench/nano.local.json",
]


def load_config(path=None, model=None):
    """配置读取顺序：显式 --config > 纯环境变量 > 本机配置文件。

    容器部署时没有配置文件，只有环境变量，所以环境变量必须能独立成立。
    """
    if not path:
        env = {
            "base_url": (os.environ.get("AI_PARSE_BASE_URL") or "").strip(),
            "authorization": (os.environ.get("AI_PARSE_AUTHORIZATION") or "").strip(),
            "model": (model or os.environ.get("AI_PARSE_MODEL") or "").strip(),
        }
        if env["base_url"] and env["authorization"] and env["model"]:
            return env

    candidates = [Path(path)] if path else DEFAULT_CONFIG_CANDIDATES
    for p in candidates:
        if p and p.exists():
            cfg = json.loads(p.read_text(encoding="utf-8"))
            break
    else:
        sys.exit("找不到模型配置：请设置 AI_PARSE_BASE_URL / AI_PARSE_AUTHORIZATION / "
                 "AI_PARSE_MODEL 环境变量，或用 --config 指定配置文件")

    return {
        "base_url": os.environ.get("AI_PARSE_BASE_URL") or cfg.get("ai_parse_base_url", ""),
        "authorization": os.environ.get("AI_PARSE_AUTHORIZATION") or cfg.get("ai_parse_authorization", ""),
        "model": model or os.environ.get("AI_PARSE_MODEL") or cfg.get("ai_parse_model", ""),
    }


def call_model(cfg, prompt, timeout=180):
    body = {
        "model": cfg["model"],
        "store": False,
        "stream": False,
        "max_output_tokens": 8000,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
    }
    req = urllib.request.Request(
        cfg["base_url"],
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": cfg["authorization"]},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))

    text = []
    for item in data.get("output", []) or []:
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                text.append(c.get("text", ""))
    return "".join(text), data.get("usage", {})


def parse_verdicts(raw, expected_ids):
    """从模型回复里抽出 JSON 数组，并校验 rule_id 覆盖度。"""
    t = (raw or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.I)
    t = re.sub(r"\s*```$", "", t)

    arr = None
    try:
        v = json.loads(t)
        arr = v if isinstance(v, list) else v.get("results")
    except Exception:
        pass
    if arr is None:
        m = re.search(r"\[[\s\S]*\]", t)
        if m:
            try:
                arr = json.loads(m.group(0))
            except Exception:
                arr = None
    if not isinstance(arr, list):
        return None, "回复不是合法 JSON 数组"

    got = {}
    for it in arr:
        if isinstance(it, dict) and it.get("rule_id"):
            got[str(it["rule_id"])] = {
                "verdict": str(it.get("verdict") or "unclear").lower(),
                "evidence": str(it.get("evidence") or ""),
                "reason": str(it.get("reason") or ""),
            }
    missing = [r for r in expected_ids if r not in got]
    return got, ("缺少规则: " + ",".join(missing) if missing else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tasks")
    ap.add_argument("--out", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--model", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--retry", type=int, default=1)
    args = ap.parse_args()

    tasks = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    cfg = load_config(args.config, args.model)

    total_chars = sum(len(t.get("prompt", "")) for t in tasks)
    print(f"模型: {cfg['model']}")
    print(f"任务: {len(tasks)} 次调用，输入约 {total_chars} 字符（≈{total_chars // 2} tokens）")
    if args.dry_run:
        print("dry-run，未调用")
        return

    results, failed = [], []
    t0 = time.time()
    for i, task in enumerate(tasks, 1):
        aid = task.get("article_index")
        ids = task.get("rule_ids") or []
        raw = err = None
        for attempt in range(args.retry + 1):
            try:
                raw, usage = call_model(cfg, task["prompt"])
                got, warn = parse_verdicts(raw, ids)
                if got is None:
                    err = warn
                    continue
                if warn:
                    err = warn
                for rid, v in got.items():
                    results.append({"article_index": aid, "rule_id": rid, **v})
                err = None
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
                err = f"{type(e).__name__}: {str(e)[:160]}"
            except Exception as e:
                err = f"{type(e).__name__}: {str(e)[:160]}"
        status = "ok" if err is None else "fail"
        print(f"  [{i}/{len(tasks)}] 第{aid + 1}篇 {len(ids)}条 -> {status}"
              + (f" ({err})" if err else ""))
        if err:
            failed.append({"article_index": aid, "error": err, "raw": (raw or "")[:400]})

    out = args.out or str(Path(args.tasks).with_name("llm_results.json"))
    Path(out).write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完成 {len(results)} 条判定，{len(failed)} 批失败，用时 {time.time() - t0:.1f}s")
    print(f"结果: {out}")
    if failed:
        fail_path = out.replace(".json", "_failed.json")
        Path(fail_path).write_text(json.dumps(failed, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"失败详情: {fail_path}")


if __name__ == "__main__":
    main()
