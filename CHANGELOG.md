## [1.7.0-local.3] - 2026-11-19

> 本地补丁版本（非上游）。修复客户端反复报 `Trae SOLO upstream failed: ... SSL: UNEXPECTED_EOF_WHILE_READING ... (502) (4028)`。

### 修复

- **SOLO 路径补传输层重试**：`_handle_agent_solo()` 原本对 `trae_solo_chat()` **零重试**，上游国内域偶发 TLS EOF（实测每次卡满 5 秒后断连）会直接把 502 抛给客户端。现改为按 `TRANSIENT_MAX_RETRIES`（2 次，1s/2s 退避）重放，且仅对 `_is_transient_transport()` 判定为瞬时故障的错误重试（SSL EOF / reset / timeout），业务错误立即返回。重放安全：`_sse_begin()` 在拿到结果后才调用，此时未向客户端写出任何字节。
- **服务看门狗化**：`service-start.bat` 由「直接执行 pythonw」改为「查端口 → 占用则退出 → 否则后台拉起」，避免 `Stop-ScheduledTask` 杀不掉子进程导致新实例端口冲突、**旧代码静默继续运行**；计划任务增加「每 5 分钟重复触发」触发器，进程挂掉后 5 分钟内自动恢复。

### 诊断结论（记录备查）

- 该错误与前一天的「上下文过大导致超时」是**两类问题**：前者是客户端先超时（网关仍记 200），后者是上游 TLS 层直接断连（网关明确 502）。
- 上游在 20:43 曾返回 `ServerOverloaded`（耗时 276 秒）、23:23 两次 TLS EOF（各 5 秒），同一分钟后又恢复正常 → 判定为 Trae 服务端晚间高峰不稳定，非本地配置问题。
- 账号侧无风控：4 个账号均为 `ready`，无 cooldown/breaker。

### 验证

- `_is_transient_transport` 对 `URLError(SSLError(...))` 与裸 `SSLError` 均判定为可重试
- `_test_trae.py`：`PASS=240 FAIL=0`
- 守护链路实测：杀进程 → 端口无响应 → 任务触发 → 新 PID 拉起 → `ping 200`；端口占用时触发不会产生第二个实例
- 重启后请求正常：`DeepSeek-V4-Flash` 1766ms / `MiMo-V2.6-Flash` 1156ms

## [1.7.0-local.2] - 2026-11-19

> 本地补丁版本（非上游）。承接 `1.7.0-local.1`，补完签到链路的落盘、请求精简与进程托管。

### 新增

- **签到结果落盘**：后台签到任务逐账号写 `usage/activity.jsonl`（看板「积分获取历史」可查）与 `accounts/<uid>.json` 的 `extra.checkin`（含签到时间/状态/积分/到账），网关重启不再丢失签到记录。
- **已签到账号 0 请求跳过**：`_run_checkin_job` 前置判断 `extra.checkin` 是否今日已签，命中则**不发任何请求**直接跳过；传 `{"force": true}` 可忽略本地记录强制重查。实测 3 个已签账号由「3 次状态查询」降为「0 请求、秒级完成」。
- **网关服务托管（Windows 计划任务）**：新增 `service-start.bat`（`pythonw` 无窗口 + 日志重定向），注册任务 `trae2api-hub-gateway`：登录自启、失败每分钟重启（`RestartCount=999`）、不限运行时长、`IgnoreNew` 防重复实例、电池条件全关、错过时间补启动。本机 `schtasks.exe` 被安全策略拉黑，改用 PowerShell `Register-ScheduledTask` 注册，并以「任务定义 XML + CIM」双通道核验。

### 修复

- **后台签到状态卡死**：`_run_checkin_job` 整体包 `try/finally`，任何未预期异常都把 `state` 落回 `done` 并记录 `error`，避免卡在 `running` 导致后续任务永久被拒（原需重启网关才能恢复）。
- **前端轮询提前超时**：签到轮询上限由固定 60s 改为按 `(账号数+1)×(间隔+抖动)+30s` 动态计算，账号多时不再中途放弃。

### 验证

- `_test_trae.py`：`PASS=240 FAIL=0 SKIP=0`
- 3 账号实测：首次签到 28 秒完成（10s+0~5s 错峰，3/3 成功）；重复触发时 3/3 本地跳过（0 请求）
- 计划任务：`Start-ScheduledTask` 后 `State=Running`、`GET /ping` 200、进程 `pythonw.exe`、日志正常写入 `gateway.log`

## [1.7.0-local.1] - 2026-11-19

> **本地补丁版本（非上游）**：本条目记录本机自用时的改动，上游仓库不含这些提交。
> 完整证据链、事故复盘与升级/回滚指引见 [docs/local-patches/LOCAL_PATCHES.md](docs/local-patches/LOCAL_PATCHES.md)。

### 新增

- **后台慢速错峰签到**：`POST /tasks/run` 默认改为异步任务，逐账号按 `10s + 0~5s` 随机抖动间隔执行，避免多账号批量签到触发风控；接口立即返回，不阻塞面板。传 `async: false` 保留旧的同步 1s 批跑路径，`interval` / `jitter` 可覆盖默认值。
- **签到任务状态接口** `GET|POST /tasks/checkin-job`：返回 `state / total / done / ok / failed / current / results / logs`，供面板轮询进度。
- **看板签到进度显示**：「每日签到」与福利中心「全部领取」按钮改为后台模式，按钮实时显示「签到中 50% · 账号名」，完成后自动刷新账号与积分。

### 修复

- **「禁用仍签到」勾选不持久化**：`Account` 类此前无 `checkin_when_disabled` 字段，`to_dict()` 不序列化、`public()` 不输出，导致看板勾选刷新即丢失且前端永远显示未勾选。现补入 `__init__` / `to_dict()` / `public()` 三处，落盘并回显。
- **禁用账号仍被签到**：`task_daily_checkin` 增加显式判断，禁用账号默认跳过（`reason: account_disabled`），仅当勾选「禁用仍签到」时才继续；`_iter_accounts` 明确对显式传入的账号列表同样执行 `enabled` 过滤。
- **import 导入账号伪 uid 导致 token 无法刷新**：`normalise_import_row` 在导入行缺 uid 时直接生成 `import-<sha256>` 伪 uid，导致刷新请求 `UserID` 与 refresh token 绑定的用户不一致（上游 `20101 refresh token user does not match`）。新增 `_uid_from_access_token()` 从 access token JWT 的 `data.id` 提取真实用户 ID，解析失败时静默回退伪 uid；显式 uid 优先级不变。

### 运行注意

- refresh token 为**轮换式**：每次 ExchangeToken 成功后旧 refresh token 立即失效。刷新务必走 `Account.refresh()` 封装（内部会调用 `sync_desktop_auth` 把新凭证写回桌面端），**禁止**直接调用 `trae_client.refresh_account()` 做验证，否则会作废桌面端凭证导致客户端掉线。
- 相关环境变量：`TRAE_SYNC_DESKTOP`（默认 1 = 刷新后写回桌面端）、`TRAE_REFRESH_POLICY`（默认 `rotate` 主动刷新；`readonly` 只从桌面端读取）。
- 回归：`python _test_trae.py` 基线 `PASS=240 FAIL=0 SKIP=0`。

## [1.7.0] - 2026-11-18

### 新增

- 合并经修复复审的 Qoder CN 第三上游（PR #8），仅通过显式 `qoder/<key>` 路由 Chat Completions，不抢占既有 Trae 模型。目录支持单区/合并视图，遵守 Key 与模型策略；Responses / Messages 明确返回不支持。
- 默认无配置时不读取桌面状态、不访问新上游。env 模式要求 TOKEN / UID / MACHINE_ID 三项完整；Windows 桌面只读导入须显式 QODER_DESKTOP_IMPORT=1，AES-GCM 路径额外需要可选 pycryptodome，核心 env 协议仍仅用标准库。

### 修复

- 接入统一模型封禁、Key 白名单、CN 出口约束、日配额与本地上下文预算；禁用开关覆盖显式请求，不因禁用或失败回落 Trae。
- 修复通用 Key 日配额读取10秒看板缓存导致连续请求超限仍放行：配额判断改为读取最新本地用量。
- 规范 Qoder 成功/错误记账为 canonical model + provider + CN realm + key/request id；保留真实流式用量，失败不再计成功。
- 流式首帧前错误保留 HTTP 状态，截断/空/非法 SSE 明确失败，客户端断连关闭上游；聚合分片工具调用并验证完整参数，截断不伪造可执行调用。
- 限制上游响应大小、脱敏错误，模型缓存按凭据指纹隔离；移除 fork 专用同步脚本，补 CI 与镜像资源自检。

### 验证与边界

- 新增适配器与真实本地 HTTP 隔离回归；不读取真实账号、不访问实际提供方。上游实时模型可用性以配置账号目录为准，不宣称已做真实账号端到端登录。
- #9 企业版仍缺少实际数据，继续保持开放；本版不虚构 Enterprise/SaaS 支持，保留 v1.6.1 的个人协议隔离。

## [1.6.1] - 2026-11-16

### 问题修复与支持范围

- 针对 #9，明确 Enterprise/SaaS 与个人 CN/INTL 为独立协议；增加账号类型识别及导入、加载、刷新、OAuth、raw/SOLO 的个人协议隔离。已知企业凭据不会回落到个人版默认主机，不会写入个人账号池。
- 修复 refreshToken 管理入口把未知/企业 realm 默认为 cn，以及鉴权头异常被内置 fallback 吞掉的问题。
- OAuth 授权页隐藏企业登录；面板、README 和 [企业版说明](docs/ENTERPRISE.md) 明确当前未实现企业租户代理。#9 的完整企业支持需求仍保留开放，不能把本次隔离修复视为企业端到端验收。
- 新增纯标准库账号类型辅助模块与企业隔离回归，保留协议客户端不可导入时的个人账号内置 fallback；镜像打包自检与 CI 同步覆盖。

### PR 审查

- PR #8（Qoder 第三上游）经隔离 AST/mock 复现存在模型/配额预检绕过、禁用开关失效、同名路由抢占、流式错误/成功重复记账、用量丢失及非流式工具调用丢失；已提交 changes requested，本次不合并、不打包未验收通道。

## [1.6.0] - 2026-11-12

### ✨ 新增功能

#### 浏览器 OAuth 登录

- 新增浏览器 native_ide + S256 PKCE 授权登录（CN / INTL），本机随机端口回调、面板会话绑定、一次性授权码交换、取消、过期及脱敏状态查询。
- 新增远程浏览器/容器部署的回调地址粘贴完成入口；移除旧设备授权探测，保留桌面、JSON 和 refreshToken 导入。
- OAuth 凭证先原子落盘再报告成功；重新登录保留账号启停、权重及路由配置；登录设备密钥与设备标识随账号持久化并用于后续请求。
- 新增隔离 OAuth 协议、真实本地 HTTP 和前端状态机回归，无真实账号登录；说明见 [docs/OAUTH.md](docs/OAUTH.md)。
- 安全约束：`state`/`login_trace_id` 双重绑定且单次消费，回调仅接受对应会话的 `127.0.0.1` 回环监听，交换与用户信息仅允许各区域官方主机，公共状态接口不返回任何令牌、PKCE verifier 或私钥。

## [1.5.1] - 2026-11-11

### 问题修复

- 修复添加账号读取不存在的 OAuth state 导致断连；不支持的设备授权返回 501 JSON，面板提供桌面凭证、JSON 和 refreshToken 三种真实导入入口（#2）。
- 修复桌面/JSON 导入返回结构不匹配、显式路径被忽略、macOS/Linux 凭证路径不正确及扫描结果被前端误过滤（#5）。
- 修复成功请求缺失 usage 时漏记、SOLO 未记账、未知缓存命中被算成 0%，以及用量统计日期窗口和日志路径不一致（#6）。
- 模型上下文配置实现持久化、读取/清除和模型列表回显，并在 raw/SOLO 入口实施本地 UTF-8 保守预算准入；不截断历史，不伪造上游窗口参数（#6）。
- 管理 POST 在执行前检查面板会话；SOLO 不再回退使用禁用账号，补齐成功/失败记账及配置预算检查。
- 修复所有 5 个 shell 启动/防火墙脚本的 Git 执行位；镜像增加脚本 chmod 和运行资源完整性检查（#4）。

### 运行参数与回归

- 每号默认并发由 8 调整为 2；后台签到默认错峰 45~120 秒，定时窗口增加 0~25 分钟抖动，保留手动同步接口短间隔兼容。
- 新增账号导入、上下文、用量、HTTP、SOLO、调度、前端和打包回归；CI 覆盖 Python 3.11 / 3.13 / 3.14。
- 本机离线回归：基线 240 项、上下文/桌面/调度 84 项、用量 64 项、HTTP 95 项、SOLO 52 项、前端 53 项、打包 63 项通过；Windows 下 5 项 POSIX 文件执行位检查跳过。

## [1.5.0] - 2026-11-09

### ✨ 新增功能

- **全新看板 UI 重构**：移植自包含单页 CPAMC 动效系统与仪表盘，支持流式吞吐监控、折线/柱状图表实时渲染。
- **路由与算力编排工作台**：新增账号编排优先层（Tiers）、调度策略（轮询 / 加权轮询 / 优先填满）、会话亲和性管理及模型决策实时命中预览。
- **深度用量统计分析**：单次日志扫描计算 6 大核心 KPI、Top 账号/提供商/模型贡献排行、近 24 小时缓存命中走势与 365 天活跃热力图。
- **多语言（i18n）动态切换**：新增国际化包结构，支持中/英双语无刷新即时切换。
- **Trae 业务深度适配**：完美融合国际版额度预警与自动降级至国内版备用模型，以及网关配置快照一键备份与恢复。

## [1.4.3] - 2026-11-05

### 问题修复
- SOLO 通道 device_id / machine_id 缺省值改为按账号 UID 派生，避免多个部署共用同一硬编码设备导致 4017 风控。
- 账号级 extra.device_id / machine_id 仍然优先。
- 版本号升级到 **1.4.3**。

## [1.4.2] - 2026-11-05

### 🐛 问题修复

- SOLO 通道（Agent 模型）遇到上游 `progress_notice` 的字符串 data 帧时抛
  `AttributeError: 'str' object has no attribute 'get'`，请求 502（实测 kimi-k3 连续 8 次失败 4 次）。
- 带 `tools` 的请求统一回 4001：上游 `FunctionDefinition.tools[].function.parameters` 要 string，
  网关直接送 OpenAI 的 dict。

### ✨ 新增功能

- SOLO 通道支持工具调用：上游 `tool_calls` 增量帧按 index 聚合，回填标准 OpenAI
  `tool_calls`（非流式）与 `delta.tool_calls`（流式），`finish_reason` 相应改为 `tool_calls`。
- SOLO 通道支持多轮工具往返：保留 `assistant.tool_calls` 消息，并给 `tool` 回执补上
  `tool_call_id` + `name`（name 由历史 `assistant.tool_calls` 的 id→name 映射）。
  修复第二轮回灌时报 `4027 tool_call_id is not found ... tool name: ''`。
- 工具调用严格校验：`arguments` 必须是**完整 JSON 对象**（截断/畸形直接报错，不自动修复）；
  上游 `finish_reason` 不是 `stop`（如 `length` 截断）时不再包装成可执行的 `tool_calls`。

### ✅ 测试

- `_test_trae.py` 新增 [6] SOLO 通道分组：非对象 data 帧、tools.parameters 归一、
  tool_calls 聚合、工具消息保留与各类缺字段报错，共 26 项断言。

- 版本号升级到 **1.4.2**。

## [1.4.1] - 2026-10-23

### 问题修复
- 账号测试不再使用非法 model=auto，CN/INTL 分别选择合法 raw 模型。
- 账号池装载时清理已过期冷却，避免 no usable account。
- 统计页补齐卡片、图表和热力图动效；日期区间可交互切换。
- 版本号升级到 1.4.1。

## [1.4.0] - 2026-10-23

### 新增功能
- 接入 Trae SOLO 纯 HTTP 通道：/api/agent/v3/llm_utils_chat。
- /v1/chat/completions 自动识别 20 个 SOLO/Agent 模型。
- 新增 /v1/agent/chat 显式入口，支持流式与非流式。
- 新增统计概览：KPI、Top 账号/提供商、365 天热力图、缓存窗口和趋势图。
- 版本号升级到 1.4.0。

## [1.1.5] - 2026-10-22

### ✨ 新增功能

- 模型页区分「网关可用」与「仅 App」：官方客户端目录存在、但 raw_chat model_list 未返回的模型不再标成「不可用」。
- 模型页统计改为「网关可用 N 个 · 仅 App M 个」。
- 前端按 upstream_key/id 去重，避免同一模型出现两行。
- 工具提示明确说明：官方 App 可见、网关 raw_chat 未接入、直接请求会 4023。

### 🐛 问题修复

- 修复国内版账号可在 App 使用、但看板显示「不可用」的误导。
- 修复 DeepSeek-V4-Flash / V4.1-Flash 等目录模型的状态文案不准确。
- 修复模型目录与动态清单叠加时可能出现重复行的问题。

### 🎨 体验优化

- 「仅 App」模型不再整体变灰，保留完整参数/价格/能力信息。
- 模型页统计更贴近真实：5 个网关可用 + 20 个仅 App。

### ⚠️ 其他变更

- 版本号升级到 **1.1.5**。
- 网关仍只支持 raw_chat 模型；仅 App 模型需要 Agent 通道，当前未接入。
## [1.1.4] - 2026-10-22

### ✨ 新增功能

- 账号页标题旁新增「总可用积分 899.61」，一眼可见。
- 积分汇总保留两位小数，不再把 899.61 截断为 899。

### 🐛 问题修复

- 修复账号页只有单个账号行显示积分、没有汇总入口的问题。
- 修复 `/credits/summary` 的 `by_realm` / `totals` 使用整数截断的问题。

### 🎨 体验优化

- 账号池始终展示国内版 + 国际版，区域徽标区分。
- 总积分、签到积分、套餐三个信息分层显示。

### ⚠️ 其他变更

- 版本号升级到 **1.1.4**。
## [1.1.3] - 2026-10-22

### ✨ 新增功能

- 账号行显示「总积分」：直接读取 Trae v2 `ide_user_ent_usage` 的 `usage_summary`。
- 总积分 = `total_amount - consumed_amount`（当前实测 900 - 0.39 = 899.61）。
- 保留签到积分与套餐展示，不再把签到积分误当总积分。
- 账号池同时显示国内版与国际版账号，不再只显示当前区域。

### 🐛 问题修复

- 修复只读取本地 entitlement、看不到 Trae 总可用积分的问题。
- 修复国内版使用 v1 entitlement 缺少 `usage_summary` 的问题；CN 改用 v2。
- 修复积分汇总把 899.61 截断成 899 的问题，保留两位小数。
- 修复账号池被当前视图过滤、国际版账号不显示的问题。

### 🎨 体验优化

- 账号行格式：`总积分 899.61 · 签到 100 · 免费`。
- 刷新权益覆盖双区全部账号。

### ⚠️ 其他变更

- 版本号升级到 **1.1.3**。
## [1.1.2] - 2026-10-22

### ✨ 新增功能

- 账号积分真实刷新：`/accounts/credits/fetch` 现在调用 Trae `fetch_usage` / `fetch_entitlement` 与国内版签到状态。
- 账号行显示签到积分、套餐、剩余/上限/已用额度。
- `/credits/summary` 增加 `checkin` / `checkin_at` 字段。

### 🐛 问题修复

- 修复「刷新权益」实际调用签到任务、从未刷新积分的错误。
- 修复 `Account.fetch_credits()` 只读本地快照、不请求上游的问题。
- 修复账号页 `credits` 字段缺失，导致积分显示不出来的问题。
- 修复刷新后上游 entitlement 未写回账号、重启后又变回旧值的问题。

### 🎨 体验优化

- 刷新按钮显示成功/失败账号数量与首个错误原因。
- 国际版无签到接口时仍展示套餐/额度，不误报失败。

### ⚠️ 其他变更

- 版本号升级到 **1.1.2**。

## [1.1.1] - 2026-10-20

### ✨ 新增功能

- 更新检测改为页面加载强制刷新，避免 6 小时缓存挡住新 Release。
- 后端检查缓存缩短为 5 分钟；顶部徽标与设置页会更快出现更新提示。

### 🐛 问题修复

- 修复 1.1.0 中自动检查命中旧缓存、发布新版本后不能立即提示的问题。

### 🎨 体验优化

- 更新提示与一键更新流程保持同一入口，减少等待。

### ⚠️ 其他变更

- 版本号升级到 **1.1.1**。

## [1.1.0] - 2026-10-20

### ✨ 新增功能

- 看板自动检测 GitHub 最新 Release，有更新时顶部显示「有新版本 → 一键更新」。
- 设置页「运行信息」增加一键更新按钮，展示当前版本与目标版本。
- 一键更新流程：下载 release tarball → 安全解压 → 自动备份 → 替换代码 → 自动重启网关。
- 更新完成后页面自动轮询 `/health`，版本一致后自动刷新。
- 更新失败时保留 `update.log` 与 `update-backups/update-*.tar.gz`，可手动回滚。
- Docker 部署检测：容器内拒绝自更新，提示使用 `docker compose pull`。

### 🐛 问题修复

- 修复 GitHub tarball 下载 `415 Unsupported Media Type`：改用 `application/vnd.github+json`。
- 修复更新检查没有返回 `tarball_url`，导致无法一键下载的问题。
- 修复看板顶部更新徽标只能跳 Releases、不能直接更新的问题。

### 🎨 体验优化

- 更新按钮显示目标版本号；下载、重启、完成都有状态提示。
- 更新包解压排除 `accounts/`、`usage/`、`.git/`、`update-backups/`，不会碰账号数据。
- 更新前自动生成 tar.gz 备份，更新日志写入 `update.log`。

### ⚠️ 其他变更

- 版本号升级到 **1.1.0**。
- 更新源固定为 `shuishuipingan/trae2api-hub` 的 GitHub Release。

# Changelog

所有重要变更都记录在这里。版本号遵循 [Semantic Versioning](https://semver.org/)。

## [1.0.0] - 2026-10-19

### ✨ 新增功能

- 国际版直连：使用当前客户端版本头 + `Authorization: Bearer`，不再依赖 Trae 桌面版、调试端口或 Agent 桥。
- 双区账号池：国内版 / 国际版独立选号、权重、冷却、会话亲和与自动换区。
- 模型目录：国内 25 个 / 国际 10 个，保留官方展示名、上下文、最大输出、思考档位与 Free / 升级标记。
- API Key 治理：模型白名单、每日请求上限、每日 Token 上限，超限返回 429。
- 额度预警：`/quota` / `/v1/quota` 暴露 `notify_usage` 剩余额度，面板顶部与账号行告警。
- 自动降级：额度耗尽或模型需升级时自动切换备用模型/出口，响应头 `X-Trae-Degraded`。
- 按 Key 图形化用量页：Token 趋势、模型分布、缓存命中率、平均延迟、日配额进度与最近请求。
- 配置备份 / 恢复：`/config/export` 与 `/config/restore`，恢复前自动写回滚备份。
- Docker / GHCR：多架构镜像（linux/amd64 + linux/arm64），Compose 一键部署。
- 8 页签玻璃拟态看板：总览、账号池、模型库、数据指标、Key 用量、维护任务、运行日志、设置。

### 🐛 问题修复

- 修复国际版旧版本头导致的 `4015`。
- 修复国际版使用 `Cloud-IDE-JWT` 导致的 `4023 model_unknown`。
- 修复 `4008 quota exceeded` 被误判为上游瞬态故障的问题；现在映射为 429 + `Retry-After: 60`，不冷却账号。
- 修复额度错误导致账号被错误冷却、模型被误标不可用的问题。
- 修复国际版免费额度耗尽后无法区分“风控”和“额度”的问题。
- 修复配置恢复时先写 settings、后校验账号可能导致半恢复的问题。
- 修复 API Key 编辑保存时模型白名单被静默丢弃的问题。

### 🎨 体验优化

- 看板新增额度告警条与 Key 用量页，移动端导航支持 8 个页签。
- 模型表增加「升级 / 目录」徽标与官方禁用原因。
- API Key 编辑行增加模型白名单、每日请求、每日 Token 三个可视化字段。
- 账号行显示国际版剩余额度与「额度已用尽」状态。
- README 重构，补充看板预览、Docker、模型状态、Key 配额与自动降级文档。
- 增加 `tests` 与 `docker-publish` GitHub Actions。

### ⚠️ 其他变更

- 项目版本从内部迭代版本统一为 **1.0.0**。
- 国际版 Agent 桥保留为可选排障 fallback，默认关闭。
- 免费额度、模型可用性与升级策略以 Trae 官方实时返回为准。
- 使用本项目即表示你理解并遵守 Trae 官方服务条款及所在地法律。
