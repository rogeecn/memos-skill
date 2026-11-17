# memos-skill

面向自建 **Memos**(usememos)实例的远程内容发布/检索 skill。
实例地址与令牌**只从环境变量读取**,仓库内不含任何实例信息。

```
memos-skill/
├── SKILL.md                 # skill 入口:触发词、命令、工作流
├── scripts/memos.py         # 纯 stdlib CLI:ping/publish/list/search/get/update/delete/forget/attach/tags
├── references/memos-api.md  # 实测 REST API(v0.30)记录
└── README.md
```

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `MEMOS_URL` | ✅ | 实例地址,如 `https://memos.example.com` |
| `MEMOS_API_KEY` | ✅ | 访问令牌(Memos → 设置 → 访问令牌),`Bearer` 认证 |
| `MEMOS_DEFAULT_VISIBILITY` | – | 默认 `private` |
| `MEMOS_API_TIMEOUT` | – | 默认 20 秒 |

## 快速开始

```bash
export MEMOS_URL=https://memos.example.com   # 换成你自己的实例
export MEMOS_API_KEY=<访问令牌>

python3 scripts/memos.py ping
python3 scripts/memos.py publish --tag 笔记 --content "第一条 memo"
python3 scripts/memos.py list -n 5
python3 scripts/memos.py search "memo"
```

安装为 pi skill(已建立软链):

```bash
ln -sfn ~/Workspace/memos-skill ~/.pi/agent/skills/memos
```
