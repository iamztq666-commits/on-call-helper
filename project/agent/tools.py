import os
import re

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": (
                "读取 data/ 目录下的文件内容。"
                "先读 index.json 获取所有可用文档摘要，再按需读取具体 SOP 文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fname": {
                        "type": "string",
                        "description": "文件名，如 index.json、sop-001.html",
                    }
                },
                "required": ["fname"],
            },
        },
    }
]


def execute_read_file(fname: str) -> str:
    # Allow index.json
    if fname == "index.json":
        path = os.path.join("data", "index.json")
        if not os.path.exists(path):
            return "错误：index.json 不存在，服务启动时应自动生成"
        with open(path, encoding="utf-8") as f:
            return f.read()

    # Only sop-XXX.html
    if not re.match(r"^sop-\d{3}\.html$", fname):
        return "错误：只能读取 index.json 或 sop-XXX.html 格式的文件"
    path = os.path.join("data", fname)
    if not os.path.exists(path):
        return f"错误：文件 {fname} 不存在"
    with open(path, encoding="utf-8") as f:
        return f.read()
