"""Startup utility: scan data/ and generate index.json."""
import json
import os

from core.html_parser import parse_html
from core.keyword_extractor import extract_keywords


def generate_index(data_dir: str = "data") -> list[dict]:
    index = []
    if not os.path.isdir(data_dir):
        return index
    for fname in sorted(os.listdir(data_dir)):
        if not fname.endswith(".html"):
            continue
        try:
            with open(os.path.join(data_dir, fname), encoding="utf-8") as f:
                html = f.read()
            title, text = parse_html(html)
            summary = text.replace("\n", " ").strip()[:200]
            entry: dict = {"fname": fname, "title": title, "summary": summary}
            # Auto-extract department + keywords for Agent routing
            kw_meta = extract_keywords(title, text)
            if kw_meta:
                entry["department"] = kw_meta.get("department", "")
                entry["keywords"] = kw_meta.get("keywords", [])
            index.append(entry)
        except Exception:
            continue
    out_path = os.path.join(data_dir, "index.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    return index
