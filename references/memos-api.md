# Memos v26 系列 REST API 实测记录

目标:`$MEMOS_URL` 指向的自建实例(实测 **v26.11.1**)。
认证:`Authorization: Bearer $MEMOS_API_KEY`(Memos → 设置 → 访问令牌)。

> **重要**:v0.30 时代的 `/api/v1/...`(gRPC-gateway)已被服务端**整体移除**,
> 现在一律返回 `HTTP 410 {"code":12,"message":"API v1 has been removed. Use /api/... for REST and /memos.api.<Service>/<Method>"}`。
> 现行接口是精简版 REST:`/api/memos`、`/api/attachments`、`/api/instance/profile`。
> (另有 connect 风格的 `/memos.api.*`,用 Bearer token 直连返回 401,未使用。)

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/instance/profile` | 版本、admin 信息(用于 ping) |
| POST | `/api/memos` | 创建 memo:`{content, visibility}` |
| GET | `/api/memos` | 列表:`pageSize`、`pageToken`、`filter`、`orderBy`、`state` |
| GET | `/api/memos/{id}` | 单条(id **裸 id**,带 `memos/` 前缀会 404) |
| PATCH | `/api/memos/{id}` | **部分更新**,只改 body 里出现的字段(见下) |
| DELETE | `/api/memos/{id}` | 删除(级联删掉挂在该 memo 上的附件) |
| POST | `/api/attachments` | 上传附件(JSON + base64),可带 `memo` 直接绑定 |
| GET | `/api/memos/{id}/attachments` | 某条 memo 的附件列表 |
| GET | `/api/attachments` | 附件列表 |
| DELETE | `/api/attachments/{id}` | 删除附件 |

**不存在**(404):`/api/workspace/profile`、`/api/auth/status`、`/api/users/me`、
`/api/memo/{id}`(旧单数路由)、`/api/tags`。`PUT /api/memos/{id}` → 501。
`POST /api/memos/{id}/attachments` → 501(附件只能走 `/api/attachments`)。
`/api/attachments` 不接受 multipart(`-F file=@...` → 400 `invalid character '-' in numeric literal`)。

## 创建 / 更新

```http
POST /api/memos
{"content": "正文", "visibility": "PRIVATE"}
```

- 返回完整 memo 对象;`name` 形如 `memos/<id>`。
- `pinned`、`tags` 在创建时传**无效**(tags 由正文里的 `#tag` 派生;`pinned` 返回仍 false)。
- `visibility`:`PRIVATE` / `PROTECTED` / `PUBLIC`,缺省私有。
- 置顶必须再发一次 PATCH:

```http
PATCH /api/memos/<id>
{"pinned": true}
```

PATCH 语义:

- **部分更新**——只传 `content` 时 `pinned`/`visibility` 保持不变,不需要 `updateMask`。
- 带 `?updateMask=content,pinned` 也能工作(旧写法兼容),但没必要。
- 可更新字段: `content`、`visibility`、`pinned`、`state`(如 `{"state":"ARCHIVED"}`)。

## 列表 / 过滤

| 参数 | 说明 |
|---|---|
| `pageSize` | 实测 1000 可用;翻页看 `nextPageToken` |
| `pageToken` | 上一页返回的 `nextPageToken` |
| `orderBy` | `create_time desc/asc`、`update_time desc`、`pinned desc`、`name` |
| `state` | 不传 = 只返回 `NORMAL`;`ARCHIVED` 单查;没有 `ALL` 语义 |
| `filter` | CEL 表达式,服务端执行 |

`orderBy` 非法值 → 400 `invalid order_by: unsupported order field: X, supported fields are: pinned, create_time, update_time, name`。

`filter` 可用(与旧 v1 基本一致):

```
content.contains("关键词")
"js" in tags
visibility == "PUBLIC"
pinned == true
(A) && (B)
(A) || (B)          # 注意:是 CEL 的 && / ||,写成 and / or 会 400 Syntax error
```

`filter` 不可用:

- `tags.contains("js")` → 400 `found no matching overload for 'contains' applied to 'list(string).(string)'`
- `state == "ARCHIVED"` → 400 `undeclared reference to 'state'`(**state 只能走 query 参数**)
- `createTime > "..."` → 400 `undeclared reference to 'createTime'`

URL 里的 filter 需整体 `urllib.parse.quote`。
`tag=` 参数会被**忽略**(服务端没有按标签过滤的参数),标签统计只能客户端扫列表。

## memo 对象

```json
{
  "name": "memos/iorNhFP8t9dqcE3EmEk28R",
  "creator": "users/<username>",
  "content": "#skilltest\n\n正文",
  "visibility": "PRIVATE",
  "state": "NORMAL",
  "pinned": false,
  "attachments": [],
  "relations": [],
  "reactions": [],
  "tags": ["skilltest"],
  "property": {"title": "", "hasLink": true, "hasCode": false, "hasTaskList": false,
               "hasIncompleteTasks": false, "hasInlineImage": false},
  "snippet": "#skilltest 正文",
  "createTime": "2026-11-17T08:19:47Z",
  "updateTime": "2026-11-17T08:19:47Z"
}
```

- `state`:`NORMAL` / `ARCHIVED`。
- `tags` 由正文里的 `#tag` 派生;`#memos skill` 这种带空格的标签会变成 `memos-skill`。
- 分享链接:`{MEMOS_URL}/m/{id}`。

## 附件

```http
POST /api/attachments
{"filename": "probe.png", "type": "image/png", "content": "<base64>", "memo": "memos/xxx"}
```

- 带 `memo` 字段即绑定到该 memo,随后 `GET /api/memos/<id>` 的 `attachments` 立刻可见。
- 返回 `{"name":"attachments/<id>", "filename":..., "type":..., "size":"68", "createTime":...}`
  (`size` 是字符串,`content` 恒为空)。
- 直链:`{MEMOS_URL}/file/attachments/{attId}/{filename}`。
  **private/protected** memo 的直链直接 GET 会 401(需要会话 cookie);public memo 才能匿名访问。
- 不带 `memo` 的上传会产生游离附件;`DELETE /api/attachments/{id}` 清理(挂到 memo 上的会被级联删除,删完再删附件会 404)。

## 环境变量

实例地址/令牌常常只写在 `~/.zshenv`,agent 的非交互 shell 读不到。
`scripts/memos.py` 会在 `MEMOS_URL`/`MEMOS_API_KEY` 缺失时按行解析
`MEMOS_ENV_FILE` → `~/.zshenv` → `~/.profile` → `~/.bashrc`(只认 `KEY=VALUE`/`export KEY=VALUE`,不执行 shell),
仅填充缺失项。仍然推荐显式 `source ~/.zshenv`。

## 实测片段(供回归对照)

```bash
curl -s -H "Authorization: Bearer $MEMOS_API_KEY" \
  "$MEMOS_URL/api/memos?pageSize=1&orderBy=create_time%20desc"
# → 200 {"memos":[{... "tags":["Twitter","Bookmark"] ...}], "nextPageToken":"..."}

curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $MEMOS_API_KEY" \
  "$MEMOS_URL/api/v1/memos?pageSize=1"
# → 410
```
