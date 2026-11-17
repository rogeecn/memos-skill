# Memos v0.30 系列 REST API 实测记录

目标:`$MEMOS_URL` 指向的自建实例。本文件记录的是 Memos **v0.30 系列**的接口行为。
认证:`Authorization: Bearer $MEMOS_API_KEY`(Memos → 设置 → 访问令牌)。
响应为 protobuf-JSON(gRPC-gateway),错误体形如 `{"code":5, "message":"...", "details":[]}`。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/instance/profile` | 版本、admin 信息(用于 ping) |
| POST | `/api/v1/memos` | 创建 memo:`{content, visibility}` |
| GET | `/api/v1/memos` | 列表:`pageSize`(≤100)、`pageToken`、`filter`、`orderBy`、`state` |
| GET | `/api/v1/memos/{id}` | 单条(id **不带** `memos/` 前缀) |
| PATCH | `/api/v1/memos/{id}?updateMask=...` | 部分更新,多个字段逗号分隔 |
| DELETE | `/api/v1/memos/{id}` | 删除 |
| POST | `/api/v1/attachments` | 上传附件(JSON + base64) |
| DELETE | `/api/v1/attachments/{id}` | 删除附件 |
| GET | `/api/v1/attachments` | 附件列表 |

**不存在**(均 404):`/api/v1/auth/status`、`/api/v1/workspace/profile`、`/api/v1/workspace/setting`、
`/api/v1/memo/{id}`(旧版单数路由)、`/api/v1/users/me`、`/openapi.json`、`/api/v1/openapi.json`。

## memo 对象

```json
{
  "name": "memos/ZTSxBhFvpvDWwKvFGwNkgz",
  "state": "NORMAL",
  "creator": "users/<username>",
  "createTime": "2026-11-17T03:14:49Z",
  "updateTime": "2026-11-17T03:14:49Z",
  "content": "#skilltest\n\n正文",
  "visibility": "PRIVATE",
  "tags": ["skilltest"],
  "pinned": false,
  "attachments": [],
  "relations": [],
  "reactions": [],
  "property": {"hasLink": false, "hasTaskList": false, "hasCode": false, "hasIncompleteTasks": false, "title": ""},
  "snippet": "#skilltest 正文"
}
```

- `state`:`NORMAL` / `ARCHIVED`(归档 memo 默认不出现在列表,需 `state=ARCHIVED` 或 filter)。
- `visibility`:`PRIVATE` / `PROTECTED` / `PUBLIC`。
- `tags` 由正文里的 `#tag` 派生;创建时传 `tags` 数组**无效**;`#memos skill` 这种带空格的标签会变成 `memos-skill`。
- `pinned` 创建时传**无效**(返回仍 false),必须 `PATCH ?updateMask=pinned {"pinned": true}`。
- 分享链接:`{MEMOS_URL}/m/{id}`。

## 过滤(CEL)

可用:

```
content.contains("关键词")
"js" in tags
visibility == "PUBLIC"
pinned == true
state == "ARCHIVED"
```

不可用:`tags.contains("js")` → 400 `found no matching overload for 'contains' applied to 'list(string).(string)'`;
`memo == "memos/..."`(attachments 列表) → 400 `undeclared reference to 'memo'`。

组合:`(A) && (B)`;URL 需整体 `urllib.parse.quote`。

## 附件

```http
POST /api/v1/attachments
{"filename": "probe.png", "type": "image/png", "content": "<base64>", "memo": "memos/xxx"}
```

- 带 `memo` 字段即绑定到该 memo,返回的 memo 里 `attachments` 立刻可见。
- 返回 `{"name":"attachments/<id>", "filename":..., "type":..., "size":"67"}`(size 是字符串)。
- 直链:`{MEMOS_URL}/file/attachments/{attId}/{filename}`。
  **private/protected** memo 的直链直接 GET 会 401(需要会话 cookie);public memo 才能匿名访问附件。
- 单独 `POST`(不带 `memo`)会创建游离附件,可用 `DELETE /api/v1/attachments/{id}` 清理。

## 实测片段(供回归对照)

```bash
curl -s -H "Authorization: Bearer $MEMOS_API_KEY" \
  "$MEMOS_URL/api/v1/memos?pageSize=1&filter=content.contains(%22memos%22)"
# → 200 {"memos":[{... "tags":["js","css","config"], "visibility":"PRIVATE" ...}], "nextPageToken":""}
```