"""
mutobj-lint CLI 入口
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import cast

from mutobj.lint._api import LintMessage, lint_directory, lint_file


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mutobj-lint",
        description="mutobj 代码风格与命名规范静态检查",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=None,
        help="要扫描的文件或目录（可多个，默认从 pyproject.toml 读取或当前目录）",
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


def _find_pyproject() -> Path | None:
    """从当前目录向上搜索 pyproject.toml，返回找到的第一个路径"""
    cwd = Path.cwd().resolve()
    for d in [cwd, *list(cwd.parents)]:
        cfg = d / "pyproject.toml"
        if cfg.is_file():
            return cfg
    return None


def _load_mutobj_lint_config() -> tuple[list[str], list[str]]:
    """读取 pyproject.toml 中 [tool.mutobj-lint] 段。

    Returns:
        (include, exclude)：include 为默认扫描路径列表，exclude 为排除目录列表。
        无配置段或读取失败时返回 ([], [])。
    """
    cfg_path = _find_pyproject()
    if cfg_path is None:
        return [], []
    try:
        data: dict[str, object] = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        return [], []

    tool: dict[str, object] = _get_dict(data.get("tool"))
    lint_cfg: dict[str, object] = _get_dict(tool.get("mutobj-lint"))
    include_raw: object = lint_cfg.get("include", [])
    exclude_raw: object = lint_cfg.get("exclude", [])

    include: list[str] = _to_str_list(include_raw)
    exclude: list[str] = _to_str_list(exclude_raw)
    return include, exclude


def _get_dict(value: object) -> dict[str, object]:
    """安全转为 dict，非 dict 返回空字典。"""
    if not isinstance(value, dict):
        return {}
    return cast(dict[str, object], value)


def _to_str_list(value: object) -> list[str]:
    """安全转为 list[str]，非 list 返回空列表。"""
    if not isinstance(value, list):
        return []
    return [str(x) for x in cast(list[object], value)]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # 先加载 config exclude（始终与 CLI --exclude 合并）
    _config_include, config_exclude = _load_mutobj_lint_config()
    if config_exclude:
        if args.exclude:
            args.exclude = args.exclude + config_exclude
        else:
            args.exclude = config_exclude

    # 确定扫描路径：CLI paths > pyproject.toml include > current directory
    if args.paths:
        scan_paths: list[str] = args.paths
    elif _config_include:
        # config include 路径相对于 pyproject.toml 所在目录
        cfg_path = _find_pyproject()
        cfg_dir = cfg_path.parent if cfg_path else Path.cwd()
        scan_paths = [str(cfg_dir / p) for p in _config_include]
    else:
        scan_paths = [str(Path.cwd())]

    all_msgs: list[LintMessage] = []
    for raw_path in scan_paths:
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

        # 汇总行（始终输出，模拟 pyright）
        error_count = sum(1 for m in all_msgs if m.severity == "error")
        warning_count = sum(1 for m in all_msgs if m.severity == "warning")
        err_plural = "" if error_count == 1 else "s"
        warn_plural = "" if warning_count == 1 else "s"
        print(f"{error_count} error{err_plural}, {warning_count} warning{warn_plural}")

    has_error = any(m.severity == "error" for m in all_msgs)
    return 1 if has_error else 0


if __name__ == "__main__":
    sys.exit(main())
