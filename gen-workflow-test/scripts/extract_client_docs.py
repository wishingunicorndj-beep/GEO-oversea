#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把客户资料目录转成带来源标记的纯文本，供规则抽取使用。

支持 .docx / .xlsx / .txt / .md。不依赖 openpyxl（xlsx 走 zip+xml 解析）。
输出每份文件一个 .txt，文件名保留原序号，正文按段落分段并标注来源。

用法：
  python3 scripts/extract_client_docs.py /Users/dingjia/Desktop/前海人寿 --out /tmp/qh_docs
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def read_docx(path):
    """按段落顺序提取，保留表格单元格（以 | 分隔）。"""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    body = root.find(W + "body")
    out = []

    def para_text(p):
        return "".join(t.text or "" for t in p.iter(W + "t")).strip()

    for child in body:
        tag = child.tag.replace(W, "")
        if tag == "p":
            t = para_text(child)
            if t:
                out.append(t)
        elif tag == "tbl":
            for tr in child.iter(W + "tr"):
                cells = []
                for tc in tr.findall(W + "tc"):
                    txt = " ".join(para_text(p) for p in tc.iter(W + "p")).strip()
                    cells.append(txt)
                if any(cells):
                    out.append(" | ".join(cells))
            out.append("")
    return "\n".join(out)


def read_xlsx(path):
    """按工作表顺序提取，单元格以 | 分隔。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(S + "t")))
        sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        out = []
        for sheet in sheets:
            out.append(f"### 工作表 {Path(sheet).stem}")
            root = ET.fromstring(z.read(sheet))
            for row in root.iter(S + "row"):
                cells = []
                for c in row.findall(S + "c"):
                    t = c.get("t")
                    v = c.find(S + "v")
                    val = ""
                    if v is not None:
                        val = shared[int(v.text)] if t == "s" and v.text is not None else (v.text or "")
                    inline = c.find(S + "is")
                    if inline is not None and inline.text:
                        val = inline.text
                    cells.append(val.replace("\n", " ").strip())
                while cells and not cells[-1]:
                    cells.pop()
                if any(cells):
                    out.append(" | ".join(cells))
            out.append("")
    return "\n".join(out)


def read_text(path):
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.name.startswith("."))
    manifest = []
    for i, p in enumerate(files, 1):
        ext = p.suffix.lower()
        try:
            if ext == ".docx":
                text = read_docx(p)
            elif ext == ".xlsx":
                text = read_xlsx(p)
            elif ext in (".txt", ".md", ".csv"):
                text = read_text(p)
            else:
                print(f"  跳过不支持格式: {p.name}")
                continue
        except Exception as e:
            print(f"  解析失败 {p.name}: {type(e).__name__} {e}")
            continue

        safe = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", p.stem)
        dest = out / f"{i:02d}_{safe}.txt"
        dest.write_text(text, encoding="utf-8")
        manifest.append({
            "order": i, "source_file": p.name, "text_file": dest.name,
            "chars": len(text), "lines": text.count("\n") + 1,
        })
        print(f"  [{i}] {p.name} -> {dest.name} ({len(text)} 字)")

    (out / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n共 {len(manifest)} 份，输出目录 {out}")


if __name__ == "__main__":
    main()
