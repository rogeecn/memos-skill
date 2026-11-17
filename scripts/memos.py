#!/usr/bin/env python3
"""memos.py — Memos (usememos) 远程内容发布 CLI。

纯 stdlib，只依赖两个环境变量：
  MEMOS_URL     实例地址，如 https://memos.example.com
  MEMOS_API_KEY 访问令牌（Memos 设置 → Access Tokens）

实例地址与令牌只从环境变量读取，不得硬编码到代码/文档/回复中。

子命令：ping / publish / list / search / get / update / delete / forget / attach / tags
用法见 SKILL.md 或 `python3 memos.py <cmd> -h`。
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VISIBILITIES = {
    "private": "PRIVATE",
    "protected": "PROTECTED",
    "public": "PUBLIC",
}
_NAME_RE = re.compile(r"^memos/(.+)$")


# ── 配置 ─────────────────────────────────────────────────────────────────────


class Config:
    def __init__(self, url: str = "", key: str = ""):
        self.url = (url or os.environ.get("MEMOS_URL", "")).strip().rstrip("/")
        self.key = (key or os.environ.get("MEMOS_API_KEY", "")).strip()
        self.timeout = float(os.environ.get("MEMOS_API_TIMEOUT", "20") or 20)
        self.default_visibility = (
            os.environ.get("MEMOS_DEFAULT_VISIBILITY", "private").strip().lower() or "private"
        )

    def validate(self) -> "Config":
        missing = [n for n, v in (("MEMOS_URL", self.url), ("MEMOS_API_KEY", self.key)) if not v]
        if missing:
            fail(
                "缺少环境变量：%s\n"
                "  在 shell profile 或 ~/.hermes/.env 中设置：\n"
                "    export MEMOS_URL=https://<你的实例地址>\n"
                "    export MEMOS_API_KEY=<访问令牌>   # Memos → 设置 → 访问令牌"
                % "、".join(missing)
            )
        return self


# ── 输出 / 错误 ──────────────────────────────────────────────────────────────


def fail(msg: str, code: int = 1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def warn(msg: str):
    print(f"提示: {msg}", file=sys.stderr)


# ── HTTP ─────────────────────────────────────────────────────────────────────


class Client:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def _request(self, method: str, path: str, payload=None, raw: bool = False):
        url = f"{self.cfg.url}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.cfg.key}",
            "Accept": "application/json",
        }
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                body = resp.read()
                if raw:
                    return body
                text = body.decode("utf-8", "replace").strip()
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:500]
            except Exception:
                pass
            raise RuntimeError(f"HTTP {e.code} {method} {path}: {detail or e.reason}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"网络错误 {self.cfg.url}{path}: {e.reason}") from e
        except json.JSONDecodeError:
            raise RuntimeError(f"响应不是合法 JSON: {method} {path}")

    def create_memo(self, content: str, visibility: str) -> dict:
        return self._request("POST", "/api/v1/memos", {"content": content, "visibility": visibility})

    def patch_memo(self, memo_id: str, body: dict, mask: str) -> dict:
        q = urllib.parse.urlencode({"updateMask": mask})
        return self._request("PATCH", f"/api/v1/memos/{memo_id}?{q}", body)

    def get_memo(self, memo_id: str) -> dict:
        return self._request("GET", f"/api/v1/memos/{memo_id}")

    def delete_memo(self, memo_id: str) -> dict:
        return self._request("DELETE", f"/api/v1/memos/{memo_id}")

    def list_memos(self, *, page_size=50, page_token="", filter="", order_by="", state=""):
        params = {"pageSize": str(page_size)}
        if page_token:
            params["pageToken"] = page_token
        if filter:
            params["filter"] = filter
        if order_by:
            params["orderBy"] = order_by
        if state:
            params["state"] = state
        return self._request("GET", "/api/v1/memos?" + urllib.parse.urlencode(params))

    def create_attachment(self, filename: str, mime: str, data: bytes, memo_name: str = "") -> dict:
        body = {
            "filename": filename,
            "type": mime,
            "content": base64.b64encode(data).decode("ascii"),
        }
        if memo_name:
            body["memo"] = memo_name
        return self._request("POST", "/api/v1/attachments", body)

    def profile(self) -> dict:
        return self._request("GET", "/api/v1/instance/profile")


# ── 工具函数 ─────────────────────────────────────────────────────────────────


def memo_id(value: str) -> str:
    """把 memos/xxx、完整 URL、纯 id 统一成纯 id。"""
    v = (value or "").strip()
    if not v:
        fail("需要 memo id")
    if "://" in v:
        # https://host/m/xxx 或 https://host/memos/xxx
        v = urllib.parse.urlparse(v).path.rstrip("/").split("/")[-1]
    m = _NAME_RE.match(v)
    if m:
        v = m.group(1)
    return v


def memo_name(memo: dict) -> str:
    return memo.get("name") or f"memos/{memo_id(memo.get('id', ''))}"


def memo_url(cfg: Config, memo: dict) -> str:
    return f"{cfg.url}/m/{memo_id(memo_name(memo))}"


def normalize_visibility(value: str | None, default: str) -> str:
    if not value:
        value = default
    v = (value or "").strip().lower()
    if v in VISIBILITIES:
        return VISIBILITIES[v]
    if v.upper() in VISIBILITIES.values():
        return v.upper()
    fail(f"未知可见性 {value!r}，可用：private / protected / public")


def normalize_tag(tag: str) -> str:
    t = (tag or "").strip().lstrip("#").strip()
    t = re.sub(r"\s+", "-", t)
    t = re.sub(r"[#,]+", "", t)
    return t


def read_content(args) -> str:
    """--content / --file / stdin 三选一。"""
    chunks = []
    if getattr(args, "content", None):
        chunks.append(args.content)
    if getattr(args, "file", None):
        path = args.file
        if path == "-":
            chunks.append(sys.stdin.read())
        else:
            try:
                with open(path, encoding="utf-8") as fh:
                    chunks.append(fh.read())
            except OSError as e:
                fail(f"读取文件失败 {path}: {e}")
    if not chunks and not sys.stdin.isatty():
        piped = sys.stdin.read()
        if piped.strip():
            chunks.append(piped)
    return "\n\n".join(c.strip("\n") for c in chunks if c.strip())


def apply_tags(content: str, tags: list[str]) -> str:
    """Memos 的 tags 由正文里的 #tag 派生，标签行必须写进正文。"""
    wanted = [normalize_tag(t) for t in (tags or []) if normalize_tag(t)]
    if not wanted:
        return content
    head, _, rest = content.partition("\n")
    existing = set(re.findall(r"#([^\s#,]+)", head))
    missing = [t for t in wanted if t not in existing]
    if not missing:
        return content
    tag_line = " ".join(f"#{t}" for t in missing)
    if existing:
        return f"{tag_line} {head}\n{rest}" if rest else f"{tag_line} {head}"
    return f"{tag_line}\n\n{content}" if content else tag_line


def local_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso or ""


def memo_line(memo: dict) -> str:
    snippet = (memo.get("snippet") or memo.get("content") or "").replace("\n", " ")
    if len(snippet) > 90:
        snippet = snippet[:90] + "…"
    tags = ",".join(memo.get("tags") or [])
    pin = "📌" if memo.get("pinned") else ""
    vis = {"PRIVATE": "🔒", "PROTECTED": "👥", "PUBLIC": "🌐"}.get(memo.get("visibility"), "")
    return (
        f"{local_time(memo.get('createTime', ''))}  {vis}{pin} {memo_id(memo_name(memo))}  "
        f"{('[' + tags + '] ') if tags else ''}{snippet}"
    )


def print_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ── 子命令 ───────────────────────────────────────────────────────────────────


def cmd_ping(args, cfg: Config, cli: Client):
    prof = cli.profile()
    admin = prof.get("admin") or {}
    info = {
        "url": cfg.url,
        "version": prof.get("version", ""),
        "auth": "ok",
        "user": admin.get("username", ""),
        "role": admin.get("role", ""),
        "token": cfg.key[:12] + "…" if cfg.key else "",
    }
    if args.json:
        print_json(info)
    else:
        print(f"✅ 连接成功  {info['url']}")
        print(f"   版本: {info['version']}   用户: {info['user']} ({info['role']})")


def cmd_publish(args, cfg: Config, cli: Client):
    content = read_content(args)
    if not content.strip():
        fail("内容为空：用 --content、--file 或管道传入正文")
    if getattr(args, "title", None):
        content = f"# {args.title.strip()}\n\n{content}"
    content = apply_tags(content, args.tag)
    visibility = normalize_visibility(args.visibility, cfg.default_visibility)

    payload = {"content": content, "visibility": visibility, "pinned": bool(args.pin)}
    if args.dry_run:
        print_json({"dry_run": True, "payload": payload, "chars": len(content)})
        return

    memo = cli.create_memo(content, visibility)
    if args.pin and not memo.get("pinned"):
        memo = cli.patch_memo(memo_id(memo_name(memo)), {"pinned": True}, "pinned")

    attachments = []
    for path in args.attach or []:
        attachments.append(upload(cli, memo_name(memo), path))

    result = {
        "ok": True,
        "id": memo_id(memo_name(memo)),
        "url": memo_url(cfg, memo),
        "visibility": memo.get("visibility", visibility),
        "pinned": memo.get("pinned", False),
        "tags": memo.get("tags", []),
        "attachments": attachments,
        "chars": len(content),
    }
    if args.json:
        print_json(result)
    else:
        print(f"✅ 已发布  {result['url']}")
        print(
            f"   id={result['id']}  可见性={result['visibility']}  "
            f"标签={','.join(result['tags']) or '-'}  字数={result['chars']}"
        )
        for a in attachments:
            print(f"   附件: {a['filename']} → {a['url']}")


def upload(cli: Client, memo_name_value: str, path: str) -> dict:
    if not os.path.isfile(path):
        fail(f"附件不存在: {path}")
    filename = os.path.basename(path)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        data = fh.read()
    att = cli.create_attachment(filename, mime, data, memo_name_value)
    aid = (att.get("name") or "").split("/")[-1]
    return {
        "filename": filename,
        "name": att.get("name", ""),
        "size": att.get("size", str(len(data))),
        "url": f"{cli.cfg.url}/file/attachments/{aid}/{urllib.parse.quote(filename)}",
    }


def build_filter(args) -> str:
    parts = []
    if getattr(args, "filter", None):
        parts.append(f"({args.filter})")
    if getattr(args, "tag", None):
        tags = [normalize_tag(t) for t in args.tag if normalize_tag(t)]
        parts.append(" && ".join(f'"{t}" in tags' for t in tags))
    if getattr(args, "visibility", None):
        parts.append(f'visibility == "{normalize_visibility(args.visibility, "private")}"')
    if getattr(args, "state", None):
        parts.append(f'state == "{args.state.upper()}"')
    if getattr(args, "pinned", False):
        parts.append("pinned == true")
    return " && ".join(parts)


def collect(cli: Client, filter_str: str, limit: int, order_by: str, state: str = ""):
    """按 nextPageToken 翻页，最多取 limit 条。"""
    out, token, page_size = [], "", min(max(limit, 1), 100)
    while True:
        page = cli.list_memos(
            page_size=page_size, page_token=token, filter=filter_str,
            order_by=order_by, state=state,
        )
        out.extend(page.get("memos") or [])
        token = page.get("nextPageToken") or ""
        if not token or len(out) >= limit:
            break
    return out[:limit]


def cmd_list(args, cfg: Config, cli: Client):
    memos = collect(cli, build_filter(args), args.limit, args.order,
                    state="" if args.state else "NORMAL")
    if args.json:
        print_json({"count": len(memos), "memos": memos})
        return
    if not memos:
        print("（没有匹配的 memo）")
        return
    for memo in memos:
        print(memo_line(memo))
        if args.full:
            print()
            print(memo.get("content", ""))
            print()


def cmd_search(args, cfg: Config, cli: Client):
    query = (args.query or "").strip()
    if not query:
        fail("search 需要查询词")
    safe = query.replace("\\", "\\\\").replace('"', '\\"')
    args.filter = f'content.contains("{safe}")'
    args.tag = args.tag or []
    memos = collect(cli, build_filter(args), args.limit, "create_time desc", state="NORMAL")
    if args.json:
        print_json({"query": query, "count": len(memos), "memos": memos})
        return
    if not memos:
        print(f"（没有包含 {query!r} 的 memo）")
        return
    for memo in memos:
        print(memo_line(memo))
        if args.full:
            print()
            print(memo.get("content", ""))
            print()


def cmd_get(args, cfg: Config, cli: Client):
    memo = cli.get_memo(memo_id(args.id))
    if args.json:
        print_json(memo)
        return
    print(f"id: {memo_id(memo_name(memo))}")
    print(f"url: {memo_url(cfg, memo)}")
    print(f"created: {local_time(memo.get('createTime', ''))}   visibility: {memo.get('visibility')}")
    print(f"tags: {','.join(memo.get('tags') or []) or '-'}   pinned: {memo.get('pinned')}")
    for att in memo.get("attachments") or []:
        print(f"attachment: {att.get('name')}  {att.get('filename')}  {att.get('size')}B")
    print("---")
    print(memo.get("content", ""))


def cmd_update(args, cfg: Config, cli: Client):
    mid = memo_id(args.id)
    mask, body = [], {}
    if args.content or args.file:
        content = read_content(args)
        if not content.strip():
            fail("内容为空")
        body["content"] = apply_tags(content, args.tag)
        mask.append("content")
    elif args.tag:
        current = cli.get_memo(mid)
        body["content"] = apply_tags(current.get("content", ""), args.tag)
        if body["content"] == current.get("content", ""):
            print("标签已存在，未改动")
            return
        mask.append("content")
    if args.visibility:
        body["visibility"] = normalize_visibility(args.visibility, cfg.default_visibility)
        mask.append("visibility")
    if args.pin is not None:
        body["pinned"] = bool(args.pin)
        mask.append("pinned")
    if not mask:
        fail("没有要更新的字段（--content/--file/--tag/--visibility/--pin/--unpin）")
    memo = cli.patch_memo(mid, body, ",".join(mask))
    if args.json:
        print_json(memo)
    else:
        print(f"✅ 已更新  {memo_url(cfg, memo)}  （字段: {','.join(mask)}）")


def cmd_delete(args, cfg: Config, cli: Client):
    mid = memo_id(args.id)
    memo = cli.get_memo(mid)
    if not args.yes:
        print("将删除：")
        print("  " + memo_line(memo))
        print("确认请加 --yes 重新执行。")
        return
    cli.delete_memo(mid)
    print(f"✅ 已删除 memo {mid}" + (f"  ({memo_url(cfg, memo)})" if args.json else ""))


def cmd_forget(args, cfg: Config, cli: Client):
    """按语义/关键词找最匹配的一条，预览后（--yes）删除。"""
    query = (args.query or "").strip()
    if not query:
        fail("forget 需要查询词")
    safe = query.replace("\\", "\\\\").replace('"', '\\"')
    memos = collect(cli, f'content.contains("{safe}")', 5, "create_time desc", state="NORMAL")
    if not memos:
        print(f"没找到包含 {query!r} 的 memo，未删除任何内容。")
        return
    target = memos[0]
    print("最佳匹配：")
    print("  " + memo_line(target))
    if len(memos) > 1:
        print(f"  （另有 {len(memos) - 1} 条同类匹配，如不符请改用 delete <id>）")
    if not args.yes:
        print("确认删除请加 --yes 重新执行。")
        return
    cli.delete_memo(memo_id(memo_name(target)))
    print(f"✅ 已删除 {memo_id(memo_name(target))}")


def cmd_attach(args, cfg: Config, cli: Client):
    mid = memo_id(args.id)
    memo = cli.get_memo(mid)
    results = [upload(cli, memo_name(memo), path) for path in args.files]
    if args.json:
        print_json({"ok": True, "memo": mid, "attachments": results})
    else:
        print(f"✅ 已上传 {len(results)} 个附件到 {memo_url(cfg, memo)}")
        for a in results:
            print(f"   {a['filename']} ({a['size']}B) → {a['url']}")
    warn("私有/受保护 memo 的附件直链需要登录态；公开 memo 的附件直链可直接访问。")


def cmd_tags(args, cfg: Config, cli: Client):
    counts: dict[str, int] = {}
    memos = collect(cli, "", args.limit, "create_time desc", state="NORMAL")
    for memo in memos:
        for t in memo.get("tags") or []:
            counts[t] = counts.get(t, 0) + 1
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if args.json:
        print_json({"scanned": len(memos), "tags": [{"tag": t, "count": c} for t, c in ordered]})
    else:
        print(f"扫描 {len(memos)} 条 memo，共 {len(ordered)} 个标签：")
        for t, c in ordered:
            print(f"  #{t:<24} {c}")


# ── argparse ─────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="memos.py",
        description="Memos 远程内容发布 / 检索 CLI（依赖 MEMOS_URL + MEMOS_API_KEY）",
    )
    p.add_argument("--url", default="", help="覆盖 MEMOS_URL")
    p.add_argument("--key", default="", help="覆盖 MEMOS_API_KEY")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("ping", help="校验连通性与令牌")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_ping)

    sp = sub.add_parser("publish", help="发布一条 memo")
    sp.add_argument("--content", "-c", default="", help="正文（markdown）")
    sp.add_argument("--file", "-f", default="", help="从文件读正文，- 表示 stdin")
    sp.add_argument("--title", "-t", default="", help="正文前插入 `# 标题`")
    sp.add_argument("--tag", "-g", action="append", default=[], help="标签，可重复；会写入正文 #tag")
    sp.add_argument("--visibility", "-v", default="", help="private|protected|public")
    sp.add_argument("--pin", action="store_true", help="置顶")
    sp.add_argument("--attach", "-a", action="append", default=[], help="附件路径，可重复")
    sp.add_argument("--dry-run", action="store_true", help="只打印请求体，不发请求")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_publish)

    sp = sub.add_parser("list", help="列出 memo（默认最近 20 条）")
    sp.add_argument("--limit", "-n", type=int, default=20)
    sp.add_argument("--tag", "-g", action="append", default=[])
    sp.add_argument("--visibility", "-v", default="")
    sp.add_argument("--state", default="", help="NORMAL（默认）| ARCHIVED")
    sp.add_argument("--filter", default="", help="原生 CEL 过滤条件，如 content.contains(\"x\")")
    sp.add_argument("--order", default="create_time desc")
    sp.add_argument("--full", action="store_true", help="打印完整正文")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("search", help="按正文关键词搜索")
    sp.add_argument("query")
    sp.add_argument("--tag", "-g", action="append", default=[])
    sp.add_argument("--limit", "-n", type=int, default=10)
    sp.add_argument("--full", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("get", help="读取单条 memo")
    sp.add_argument("id")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("update", help="修改正文 / 可见性 / 置顶 / 追标签")
    sp.add_argument("id")
    sp.add_argument("--content", "-c", default="")
    sp.add_argument("--file", "-f", default="")
    sp.add_argument("--tag", "-g", action="append", default=[])
    sp.add_argument("--visibility", "-v", default="")
    sp.add_argument("--pin", dest="pin", action="store_true", default=None)
    sp.add_argument("--unpin", dest="pin", action="store_false")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("delete", help="按 id 删除（不加 --yes 只预览）")
    sp.add_argument("id")
    sp.add_argument("--yes", "-y", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("forget", help="按关键词找最佳匹配并删除")
    sp.add_argument("query")
    sp.add_argument("--yes", "-y", action="store_true")
    sp.set_defaults(func=cmd_forget)

    sp = sub.add_parser("attach", help="给已有 memo 上传附件")
    sp.add_argument("id")
    sp.add_argument("files", nargs="+")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_attach)

    sp = sub.add_parser("tags", help="统计最近 memo 的标签分布")
    sp.add_argument("--limit", "-n", type=int, default=200)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_tags)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    cfg = Config(args.url, args.key).validate()
    cli = Client(cfg)
    try:
        args.func(args, cfg, cli)
    except RuntimeError as e:
        fail(str(e))
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
