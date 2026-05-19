"""
mutobj-lint CLI 入口
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mutobj.lint._api import LintMessage, lint_directory, lint_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mutobj-lint",
        description="mutobj 风格静态检查（R001 声明/实现风格混合检测，R002 声明文件底部 _impl import 检查）",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="要扫描的文件或目录（可多个）",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="NAME",
        help="追加排除的目录名（可多次指定）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="输出 JSON（兼容 Code Climate spec）",
    )
    return parser


def _format_text(msgs: list[LintMessage]) -> str:
    """文本格式：path:line:col: rule_id message"""
    return "\n".join(
        f"{m.path}:{m.line}:{m.column}: {m.rule_id} {m.message}"
        for m in msgs
    )


def _format_json(msgs: list[LintMessage]) -> str:
    """Code Climate 兼容 JSON 输出

    见 https://github.com/codeclimate/platform/blob/master/spec/analyzers/SPEC.md
    """
    items: list[dict[str, object]] = []
    for m in msgs:
        items.append({
            "type": "issue",
            "check_name": m.rule_id,
            "description": m.message,
            "categories": ["Style"],
            "severity": "major" if m.severity == "error" else "minor",
            "location": {
                "path": m.path,
                "positions": {
                    "begin": {"line": m.line, "column": max(m.column, 0) + 1},
                    "end": {"line": m.line, "column": max(m.column, 0) + 1},
                },
            },
        })
    return json.dumps(items, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    all_msgs: list[LintMessage] = []
    for raw_path in args.paths:
        p = Path(raw_path)
        if p.is_file():
            all_msgs.extend(lint_file(p))
        else:
            all_msgs.extend(lint_directory(p, exclude=args.exclude))

    all_msgs.sort()

    if args.json:
        print(_format_json(all_msgs))
    else:
        text = _format_text(all_msgs)
        if text:
            print(text)

    has_error = any(m.severity == "error" for m in all_msgs)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
