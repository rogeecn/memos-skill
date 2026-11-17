---
name: memos
description: 把内容发布到远程 Memos 实例(usememos):发布/更新/删除 memo、按关键词检索、标签统计、上传附件。当用户说「发到 memos / 记到 memos / 同步到 memos / 在 memos 里搜一下 / 删掉那条 memo / 发一条笔记 / 记到备忘录 / 存到备忘录 / 备忘录里找一下」时使用。依赖环境变量 MEMOS_URL 与 MEMOS_API_KEY,纯 Python stdlib。
version: 2.0.0
---

# Memos 远程内容发布 (memos)

用户自建 Memos 实例的发布/检索 skill。**实例地址与服务端信息不做任何硬编码,运行时只从环境变量读取。**
无第三方依赖(仅 Python stdlib),所有命令都通过 `scripts/memos.py`。

> 用户口中的「**备忘录**」就是 Memos:说「记到备忘录 / 存到备忘录 / 备忘录里搜一下」时,用本 skill 而不是本地 markdown 文件。
> 接口面向自建 Memos 的 REST API(**v26 系列**,端点 `/api/memos`;旧的 `/api/v1/...` 已被服务端移除,返回 HTTP 410)。
> 无自动 recall/capture 钩子。

## 前置:环境变量(硬规则)

```bash
echo "$MEMOS_URL"      # 如 https://memos.example.com(以环境变量为准,勿写死)
echo "$MEMOS_API_KEY"  # Memos → 设置 → 访问令牌
```

- **实例地址、端口、主机名、令牌一律不写进代码/文档/回复**,需要时从 `$MEMOS_URL`、`$MEMOS_API_KEY` 读;不把令牌明文回显给用户,也不写进 memo 正文。
- 两个变量都必须存在。**agent 的非交互 shell 常常读不到 `~/.zshenv`**:脚本在变量缺失时会自动按行解析
  `MEMOS_ENV_FILE` → `~/.zshenv` → `~/.profile` → `~/.bashrc`(只认 `KEY=VALUE` / `export KEY=VALUE`,不执行 shell),
  只补缺失项;仍然读不到才报错。手动 `set -a; . ~/.zshenv; set +a` 也可以。
- 可选:`MEMOS_DEFAULT_VISIBILITY`(默认 `private`)、`MEMOS_API_TIMEOUT`(默认 20 秒)。
- 临时覆盖:`python3 scripts/memos.py --url ... --key ... <cmd>`。

## 命令速查

```bash
S=scripts/memos.py

python3 $S ping                                  # 校验地址+令牌,打印版本与用户
python3 $S publish --content "正文" --tag 笔记 --visibility private
python3 $S publish --title "标题" --file article.md --tag 归档 --pin
python3 $S publish -c "带图" --attach shot.png --json
python3 $S list -n 20 [--tag 笔记] [--visibility public] [--state ARCHIVED|all] [--full]
python3 $S search "关键词" -n 10 [--tag 笔记] [--full]
python3 $S get <id>
python3 $S update <id> --content "新正文" --tag 追加 --visibility public
python3 $S delete <id> [--yes]                   # 不加 --yes 只预览
python3 $S forget "关键词" [--yes]               # 按匹配删最相关一条
python3 $S attach <id> a.png b.pdf
python3 $S tags -n 200                           # 最近 N 条的标签分布
```

所有子命令支持 `-h`;`publish/list/search/get/update/attach/tags` 支持 `--json`(给程序/后续步骤用)。
`list/search` 的 `--filter` 是服务端 CEL(如 `content.contains("x")`、`"Bookmark" in tags`);
`state` 只能走 `--state` 参数(CEL 里没有 `state` 变量),默认只返回 `NORMAL`。
标签一律由正文里的 `#tag` 派生,带空格的标签会变成 `a-b`。

## 常用工作流

### 1. 发布长文(heredoc,避免 shell 引号地狱)

```bash
python3 $S publish --tag 长文 --title "我的文章" --file - --json <<'EOF'
正文第一段……

## 小标题

- 列表项
EOF
```

`--file -` 或**无 `--content`/`--file` 且 stdin 非 tty** 时自动读管道,所以
`cat article.md | python3 $S publish --tag 归档` 也可。
发布成功后返回 `url`(`https://<host>/m/<id>`),把该链接给用户。

### 2. 发布前先核对请求体

```bash
python3 $S publish -c "..." --tag a --dry-run   # 只打印 content/visibility/pinned
```

### 3. 收藏某个网页/文章要点

```bash
python3 $S publish --title "<标题>" --content "<要点+链接>" --tag 收藏 --tag <主题>
```

### 4. 归档/整理

```bash
python3 $S search "旧关键词" -n 20 --json | python3 -c 'import json,sys;[print(m["name"]) for m in json.load(sys.stdin)["memos"]]'
python3 $S update <id> --tag 已归档 --visibility private
```

## 安全与礼貌

- 默认 `private`;只有用户明确要求「公开/分享」时才用 `--visibility public`。
- 删除类命令默认只预览,`--yes` 才执行;删除前先看 `delete`/`forget` 的预览行对不对。
- 连续多次发布时合并成一条带小标题的 memo,而不是刷屏多条。
- 网络失败:先 `ping` 确认地址/令牌,再重试;脚本报错会带 `HTTP <code> <method> <path>` 与响应体片段。
- 报 `HTTP 410 ... API v1 has been removed`:说明脚本还是旧版(走 `/api/v1`),确认用的是本仓库的
  `scripts/memos.py`(v2+,走 `/api/memos`),不要再用旧副本。

详细 API 记录见 `references/memos-api.md`。
