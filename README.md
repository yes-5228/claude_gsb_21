# 公厕保洁巡查记录系统

面向城市公厕管养单位的巡查记录与整改闭环管理系统，覆盖 **公厕台账 → 保洁巡查 → 问题上报 → 整改跟踪** 四条业务主线。后端为 FastAPI + SQLAlchemy，前端为 React + Vite，前后端均按模块拆分，可单独开发、单独部署。

## 功能模块

| 模块 | 页面/入口 | 主要能力 |
| --- | --- | --- |
| 总览看板 | `/` | 核心指标卡、巡查与问题趋势、整改状态/分类/严重程度分布、区域运行情况、重点关注公厕、最新问题与巡查 |
| 公厕台账 | `/restrooms`、`/restrooms/:id` | 台账增删改查、区域与状态筛选、公厕详情（档案 + 历史巡查 + 历史问题 + 月度考核）、关联数据删除保护、发起合并/拆分 |
| 合并/拆分 | `/change-orders` | 公厕撤并与拆单的申请、影响面预览、审批通过即原子执行/驳回/撤销；记录归属迁移并保留原编号追溯 |
| 保洁巡查 | `/inspections` | 8 项检查项打分、自动折算百分制得分与等级、班次/日期/结论筛选、巡查详情、一键转问题上报 |
| 问题上报 | `/issues`、`/issues/:id` | 问题上报（可关联巡查记录）、分类/程度/期限、整改流程流转、整改轨迹时间线、超期预警、追加跟进记录 |

其他页面不会互相混杂：台账、巡查、问题各自独立成页，详情页再做跨模块的关联展示。

## 技术栈

- 后端：FastAPI 0.115、SQLAlchemy 2.0、Pydantic v2、Uvicorn；数据库默认 SQLite，容器中可切换 PostgreSQL 16
- 前端：React 18、React Router 6、Vite 6；不使用 UI 组件库，样式集中在 `src/styles/global.css`
- 部署：Docker Compose 编排 PostgreSQL + 后端 + Nginx 前端（Nginx 同时反代 `/api`）

## 目录结构

```
.
├── backend
│   ├── app
│   │   ├── api/v1/endpoints      # 路由层：restrooms / inspections / issues / stats / meta
│   │   ├── core                 # 配置、数据库、业务常量、领域异常
│   │   ├── models               # ORM 模型：公厕、巡查、问题、整改流水、变更单、月度考核
│   │   ├── schemas              # Pydantic 出入参模型
│   │   ├── services             # 业务规则层：台账、巡查、问题整改、评分、统计、变更单审批、月度考核
│   │   ├── seed.py              # 演示数据生成
│   │   └── main.py              # 应用入口（含异常处理、CORS、健康检查）
│   ├── tests                    # pytest 接口测试
│   ├── Dockerfile
│   └── requirements.txt
├── frontend
│   ├── src
│   │   ├── api                  # 按资源拆分的接口封装 + 统一 fetch 客户端
│   │   ├── components           # 通用组件：表格、分页、弹窗、标签、图表、时间线等
│   │   ├── hooks                # useAsync / useListQuery / useDictionaries
│   │   ├── pages                # dashboard / restrooms / inspections / issues 四个模块
│   │   ├── utils                # 时间格式化、评分换算
│   │   └── styles/global.css
│   ├── nginx.conf
│   └── Dockerfile
└── docker-compose.yml
```

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
docker compose up -d --build
```

启动后：

- 前端界面：http://localhost:8080
- 后端接口文档：http://localhost:8000/docs （也可通过 http://localhost:8080/docs 访问）
- 健康检查：http://localhost:8000/health

三个服务均带健康检查，`backend` 等待 `db` 健康后启动，`frontend` 等待 `backend` 健康后启动。首次启动会自动建表并写入演示数据。

停止与清理：

```bash
docker compose down        # 停止容器
docker compose down -v     # 同时删除数据库卷（下次启动重新生成演示数据）
```

### 方式二：本地开发

后端（默认使用 SQLite，数据库文件为 `backend/data/app.db`）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173，/api 自动代理到 127.0.0.1:8000
```

若后端不在默认端口，可指定代理目标：

```bash
set VITE_PROXY_TARGET=http://127.0.0.1:8020   # macOS/Linux: export VITE_PROXY_TARGET=...
npm run dev
```

## 环境变量

后端（均可用环境变量覆盖，见 `backend/app/core/config.py`）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/app.db` | 数据库连接串；容器中为 `postgresql+psycopg://restroom:restroom_pass@db:5432/restroom` |
| `SEED_ON_STARTUP` | `true` | 启动时若库为空则写入演示数据 |
| `CORS_ORIGINS` | `*` | 允许跨域来源，逗号分隔 |
| `SQL_ECHO` | `false` | 是否打印 SQL |

前端：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE` | `/api/v1` | 接口前缀，构建时注入 |
| `VITE_PROXY_TARGET` | `http://127.0.0.1:8000` | 仅开发模式下 Vite 代理目标 |

## 接口一览

所有接口前缀为 `/api/v1`，完整文档见 `/docs`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/restrooms` | 台账分页查询（keyword/district/status/grade/排序/分页） |
| POST | `/restrooms` | 新增公厕，编号留空自动生成 `WC-0001` |
| GET | `/restrooms/{id}` | 详情，含巡查次数、均分、未闭环问题数 |
| PATCH | `/restrooms/{id}` | 局部更新 |
| DELETE | `/restrooms/{id}?force=` | 删除；有巡查或问题记录时返回 409，`force=true` 才级联删除 |
| GET | `/restrooms/meta/districts` | 区域列表（筛选下拉用） |
| GET | `/inspections` | 巡查记录查询（restroom_id/district/inspector/shift/result/日期区间/关键字） |
| POST | `/inspections` | 新增巡查，服务端按检查项自动算分、定级、判定结论 |
| GET/PATCH/DELETE | `/inspections/{id}` | 详情 / 更新 / 删除 |
| GET | `/issues` | 问题查询（status/category/severity/district/overdue/open_only/日期区间/关键字） |
| POST | `/issues` | 上报问题，自动生成编号 `WT-YYYYMMDD-001` 并写入首条整改流水 |
| GET/PATCH/DELETE | `/issues/{id}` | 详情（含完整整改轨迹）/ 更新 / 删除 |
| GET | `/issues/{id}/transitions` | 当前状态可执行的流转动作 |
| POST | `/issues/{id}/transitions` | 推进整改状态（越级流转返回 400） |
| POST | `/issues/{id}/records` | 追加跟进记录（不改变状态） |
| GET | `/stats/overview` | 核心指标 |
| GET | `/stats/dashboard` | 看板聚合数据（趋势、分布、区域、排行、最新记录） |
| GET | `/change-orders` | 合并/拆分变更单列表（status/type/restroom_id 过滤） |
| GET | `/change-orders/preview?type=&source_restroom_id=&target_restroom_id=` | 变更影响面预览（巡查/问题/考核数量、在办问题清单） |
| POST | `/change-orders/merge` | 发起合并申请（源厕 + 承接厕 + 变更依据） |
| POST | `/change-orders/split` | 发起拆分申请（新点位档案 + 在办问题逐条划归 + 变更依据） |
| GET | `/change-orders/{id}` | 变更单详情（含划归明细与执行结果快照） |
| POST | `/change-orders/{id}/approve` | 审批通过并在单事务内整体执行 |
| POST | `/change-orders/{id}/reject` | 审批驳回（记录归属不变） |
| POST | `/change-orders/{id}/revoke` | 撤销待审批单据 |
| GET | `/assessments` | 月度考核结果列表（restroom_id/period 过滤） |
| POST | `/assessments/restrooms/{id}` | 出具某公厕某月考核（出具后冻结，不重算） |
| GET | `/meta/dictionaries` | 枚举字典（状态、分类、程度、检查项、流转规则、变更类型/状态） |
| GET | `/meta/restroom-options` | 公厕下拉选项 |
| GET | `/health` | 健康检查 |

## 业务规则

- **巡查评分**：8 个检查项各 0-10 分，得分 = 总得分 / 满分 × 100；≥90 优秀、≥80 良好、≥70 合格，其余不合格。任一检查项低于 6 分或等级为不合格时，巡查结论自动置为「发现问题」。
- **问题编号**：`WT-` + 上报日期 + 当日三位流水号。
- **整改闭环**：`待整改 → 整改中 → 待验收 → 已完成 → 已关闭`；`待验证` 阶段可被驳回退回 `整改中`，`待整改/整改中` 可直接作废关闭。每次流转都会写入一条整改流水（动作、原状态、新状态、操作人、说明），详情页以时间线呈现。
- **超期预警**：整改期限早于当前时间且状态仍处于未闭环（待整改/整改中/待验收）时，列表与详情页显示「已超期」，看板统计超期数量。
- **删除保护**：删除公厕时若已存在巡查或问题记录，接口返回 409 并提示数量，需要显式 `force=true` 才会级联删除；前端会二次确认。
- **合并（撤并）**：须提交变更单并写明依据，审批通过后在单个事务内执行——源厕标记为「已撤并」并指向承接方，其巡查、问题（含已闭环）、月度考核的当前归属整体改写到承接方；每条记录用 `origin_restroom_id/origin_restroom_code` 保留原编号，并向迁移的问题追加一条「归属变更」整改流水。源厕台账保留可追溯，不能再提交巡查/问题、不能编辑或删除。
- **拆分**：审批通过后新建点位，**仅**把申请时逐条明确划归的未闭环问题（在办任务）迁到新点位并留原编号；历史巡查、已闭环问题、已出具的月度考核一律留在原公厕不动。申请必须覆盖全部在办问题，执行时若发现申请后又冒出新的在办问题，整单失败回滚、提示重新发起。
- **统计与考核口径分离**：看板与公厕详情的统计始终按记录**当前归属**实时重算；月度考核是出具后即冻结的凭证——拆分不迁移不重算，合并随记录归到承接方并保留原编号。承接方同一月份可并存多条来源不同的历史考核。
- **原子性**：合并/拆分审批通过后在一个数据库事务内完成全部归属改写，任一步失败整体回滚，变更单回到「待审批」，不会出现记录只迁移一半；可修正后重新审批。
- **归属变更期间的并发提交**：变更执行对相关公厕行加锁（PostgreSQL 为 `SELECT ... FOR UPDATE`，按固定顺序加锁防死锁；SQLite 靠单写串行），与巡查/问题提交互斥。提交若先落库会被随后生效的变更整体带走（归属确定）；变更若先生效，提交会被 409 拒绝并提示承接方，记录必然落在确定的一方。同一公厕存在进行中变更单时，不允许重复发起或删除公厕。

## 演示数据

`SEED_ON_STARTUP=true`（默认）且数据库为空时，会自动写入：10 座公厕（4 个区域、三类等级、含维修/停用状态）、近 14 天约 90 条巡查记录、13 条不同整改阶段的问题及其完整整改轨迹。数据由固定随机种子生成，结果可复现；如需重置，删除 `backend/data/app.db`（或 `docker compose down -v`）后重启即可。

## 测试与验证

```bash
cd backend && pytest -q          # 接口测试（覆盖台账 CRUD、删除保护、评分、流程流转、统计、合并/拆分/月度考核）
cd frontend && npm run build     # 生产构建
```

本项目完成时已实际运行验证：

- 后端 `pytest`：15 个用例全部通过（含台账 CRUD、删除保护、评分、流程流转、统计，以及合并/拆分记录归并、原编号留痕、月度考核冻结、审批流、执行失败整体回滚、并发提交归属等用例）；`/health`、台账/巡查/问题/统计/字典/变更单/考核接口均返回预期数据。
- 前端 `npm run build`：构建成功（76 个模块）。
- 并发脚本验证：多线程同时提交巡查与审批合并，承接方/源厕巡查数恒为「不丢不重」，提交要么随合并归到承接方，要么被 409 拒绝并提示承接方。
- 浏览器端到端验证（Chromium 无头模式，覆盖 10 个场景）：看板渲染与趋势图、台账列表筛选、新增公厕表单提交、公厕详情三个页签、巡查列表、巡查评分表单联动（拉低单项分数后结论文案实时变化）、提交巡查记录、问题列表状态筛选、问题整改流转（真实写入并在时间线新增节点）、从巡查记录跳转上报问题（自动带入公厕与关联巡查记录）。全程无控制台报错。
- Docker Compose：`docker compose up -d --build` 后 `db`、`backend`、`frontend` 三个容器均达到 healthy，通过 Nginx 访问前端并调用 `/api/v1/*` 数据正常，即容器化链路（Nginx → FastAPI → PostgreSQL）完整可用。

## 常见问题

- **端口被占用**：若 8000/8080 已被占用，可用覆盖文件改端口，例如 `docker compose -f docker-compose.yml -f override.yml up -d`，其中 `override.yml` 写 `services: { backend: { ports: ["8010:8000"] } }`。
- **想看 SQLite 而不是 PostgreSQL**：把 `backend` 服务的 `DATABASE_URL` 改为 `sqlite:///./data/app.db` 即可，无需 `db` 服务。
- **接口 422**：后端把参数校验错误统一转成中文可读文案，前端会直接弹出提示，例如「参数校验失败 - name: String should have at least 1 character」。
- **越级流转报错**：属于预期行为，接口会返回当前状态允许流转的目标状态列表，前端也只会展示合法动作。
