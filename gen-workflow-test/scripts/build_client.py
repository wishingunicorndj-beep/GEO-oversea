#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""客户交付一键链路：资料 → 抽取 → 规则包 → 定制工作流。

用法：
  python3 scripts/build_client.py /Users/dingjia/Desktop/前海人寿 \
      --slug qianhai_life --name "前海人寿保险股份有限公司" --short 前海人寿

  # 跳过已有中间产物（改规则包后重新生成 yml）
  python3 scripts/build_client.py <dir> --slug x --name y --from-rules

阶段产物（默认落在 clients/<slug>/ 与 workflows/）：
  <slug>/_docs/       资料转出的纯文本
  <slug>/_draft.json  模型抽取的规则初稿（含 conflicts / not_rules）
  <slug>/rules.yaml   正式规则包（draft_to_rules 产出）
  workflows/<short>生文.yml  定制工作流

每一步都可单独重跑，产物落盘后可人工复核再继续。
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SCRIPTS = BASE / "scripts"


def run(cmd, desc):
    print(f"\n{'='*70}\n▶ {desc}\n{'='*70}")
    print("$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], capture_output=False, text=True)
    if r.returncode != 0:
        sys.exit(f"\n✗ 失败于：{desc}（退出码 {r.returncode}）")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="客户资料目录")
    ap.add_argument("--slug", required=True, help="客户标识，如 qianhai_life")
    ap.add_argument("--name", required=True, help="客户全称")
    ap.add_argument("--short", required=True, help="客户简称，用于工作流命名")
    ap.add_argument("--exclude", nargs="*", default=[], help="资料转文本后按文件名前缀排除")
    ap.add_argument("--config", default=None, help="模型配置路径")
    ap.add_argument("--from-docs", action="store_true", help="跳过资料转文本，直接用已有 _docs")
    ap.add_argument("--from-draft", action="store_true", help="跳过抽取，用已有 _draft.json")
    ap.add_argument("--from-rules", action="store_true", help="只生成 yml，用已有 rules.yaml")
    args = ap.parse_args()

    client_dir = BASE / "clients" / args.slug
    docs_dir = client_dir / "_docs"
    draft_path = client_dir / "_draft.json"
    rules_path = client_dir / "rules.yaml"
    yml_path = BASE / "output" / f"{args.short}生文.yml"

    client_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now()

    # ---- 阶段 1：资料转文本 ----
    if args.from_rules or args.from_draft or args.from_docs:
        print(f"跳过资料转文本（复用 {docs_dir}）")
        if not (docs_dir / "_manifest.json").exists():
            sys.exit(f"缺少 {docs_dir}/_manifest.json")
    else:
        run([sys.executable, SCRIPTS / "extract_client_docs.py", args.src, "--out", docs_dir],
            "阶段 1/4 资料转文本")

    # ---- 阶段 2：模型抽取规则 ----
    if args.from_rules or args.from_draft:
        print(f"跳过规则抽取（复用 {draft_path}）")
        if not draft_path.exists():
            sys.exit(f"缺少 {draft_path}")
    else:
        cmd = [sys.executable, SCRIPTS / "extract_rules.py", docs_dir, "--out", draft_path]
        if args.exclude:
            cmd += ["--exclude", *args.exclude]
        if args.config:
            cmd += ["--config", args.config]
        run(cmd, "阶段 2/4 模型抽取规则")

    # ---- 阶段 3：draft 转 rules.yaml ----
    if args.from_rules:
        print(f"跳过规则包生成（复用 {rules_path}）")
        if not rules_path.exists():
            sys.exit(f"缺少 {rules_path}")
    else:
        run([sys.executable, SCRIPTS / "draft_to_rules.py", draft_path,
             "--slug", args.slug, "--client-name", args.name,
             "--client-short", args.short, "--out", rules_path],
            "阶段 3/4 生成规则包")

    # ---- 阶段 4：生成定制工作流 ----
    run([sys.executable, SCRIPTS / "build_client_workflow.py", rules_path,
         "--out", yml_path],
        "阶段 4/4 生成定制工作流")

    # ---- 汇总 ----
    stats = {}
    if rules_path.exists():
        import yaml
        doc = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
        stats = doc.get("stats") or {}

    print(f"\n{'='*70}\n完成，用时 {(datetime.now()-started).seconds}s\n{'='*70}")
    print(f"  资料文本   {docs_dir}")
    print(f"  规则初稿   {draft_path}")
    print(f"  规则包     {rules_path}  ({stats.get('total', '?')} 条, "
          f"{stats.get('delivery_excluded', 0)} 条流程项不注入)")
    print(f"  定制工作流 {yml_path}")
    print("\n下一步：")
    print("  1. 人工复核 rules.yaml 的 conflicts 与 not_rules")
    print("  2. 把 version 从 0.1.0-draft 改为正式版本")
    print(f"  3. 导入 Dify 运行，把输出 JSON 喂给 clients/{args.slug}/evaluate.py")


if __name__ == "__main__":
    main()
