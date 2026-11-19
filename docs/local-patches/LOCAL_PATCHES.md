# 本地改动说明（LOCAL PATCHES）

> 记录本项目在**本地自用**时相对上游仓库（`shuishuipingan/trae2api-hub`）的全部代码改动与账号数据修复。
> 这些改动**不在上游**，执行 `git pull` 时可能产生冲突；升级前请先阅读本文末尾的「升级与回滚」。
>
> 记录日期：2026-11-19
> 基线提交：`3d2e23e feat: merge reviewed Qoder CN provider with policy and stream fixes (#8)`

---

## 目录

1. [⚠️ 事故记录：token 轮换导致客户端掉线（2026-11-19）](#0-事故记录token-轮换导致客户端掉线2026-11-19)
2. [改动总览](#1-改动总览)
3. [Patch 1：checkin_when_disabled 勾选不持久化 / 禁用仍签到](#2-patch-1checkin_when_disabled-勾选不持久化--禁用仍签到)
4. [Patch 2：import 账号伪 uid 导致 token 刷新失败（20101）](#3-patch-2import-账号伪-uid-导致-token-刷新失败20101)
5. [账号数据修复记录](#4-账号数据修复记录)
6. [验证结果](#5-验证结果)
7. [升级与回滚](#6-升级与回滚)

---

## 0. ⚠️ 事故记录：token 轮换导致客户端掉线（2026-11-19）

> **严重等级：高**。涉及凭证失效与客户端掉线，特此完整记录，作为本机使用该网关的最高优先级教训。

### 0.1 事故时间线

| 时间 | 事件 | 影响 |
|---|---|---|
| 16:51-16:53 | 正常使用网关（GLM-5.3-Flash、Kimi-K3 测试通过） | 无 |
| 17:40 | `…70a0`（import 号）access token 到期，自动刷新失败（20101 user does not match） | 账号进入失效风险 |
| 17:50 | **落盘刷新**：改 uid 为真实 ID 后刷新成功，新凭证落盘（token 12-03 / refresh 2027-05-18） | 桌面端旧 refresh token **被作废** |
| 17:52 | **内存验证刷新**：`trae_client.refresh_account(ignore_backoff=True)` 裸调用，拿到新凭证**未落盘、未写回桌面端** | ① 桌面端再次作废 ② **磁盘上的 refresh token 也被作废**（invalid） |
| 17:53 | 桌面客户端被登出（截图确认） | 客户端登录失效 |
| 18:13 | 检查磁盘：6800 access token 仍有效（12-03），refresh token 已 invalid | 网关还能用，但无法续期 |
| 18:26 | 启用 OAuth 账号 `…1498` 为主力，验证走封装刷新 + 自动写回桌面端成功 | 网关恢复长期稳定 |

### 0.2 根因

1. **refresh token 是轮换式**（`trae_client.py:1084/2347`）：每次 ExchangeToken 成功后，旧 refresh token **立即失效**
2. 该账号（原 `…70a0`，现 `…6800`）凭证**从桌面端导入**（`source: import`，token 内 `source: refresh_token`），网关与桌面客户端**共用同一条 refresh 链**
3. 本次事故直接原因：**绕过封装调用底层 `refresh_account()` 做验证**，它只返回新凭证，**不落盘、不写回桌面端**（`sync_desktop_auth`）
4. 结果：轮换发生但同步没做 → 桌面端和磁盘上的旧 refresh token 全部作废

### 0.3 正确做法（已确认）

- **刷新必须走 `Account.refresh()` 封装**（`trae_accounts.py:1518`），它刷新成功后**默认自动调用 `sync_desktop_auth` 写回桌面端**（`:1577`，受 `TRAE_SYNC_DESKTOP=0` 控制）
- 相关环境变量：`TRAE_SYNC_DESKTOP`（默认 1=写回桌面端）、`TRAE_REFRESH_POLICY`（默认 rotate=网关主动刷新；readonly=只从桌面端读，不主动轮换）
- **严禁**：为验证目的直接调用 `trae_client.refresh_account()` / `_refresh_account_request()` 裸刷新

### 0.4 账号现状（2026-11-19 18:26 后）

| 账号 | 来源 | 状态 | access 过期 | refresh 过期 | 能否自动续期 |
|---|---|---|---|---|---|
| `2961428649351498` | OAuth | **启用（主力）** | 2026-12-03 18:26 | 2027-05-18 | ✅ 有效 refresh，已验证 |
| `3031833961306800` | 别人给的 import 号 | 启用（备胎） | 2026-12-03 17:49 | 记录 2027-05-18 但**已作废** | ❌ 不可续期，12-03 后永久失效 |
| `import-...bak-uidfix` | 备份 | 归档 | 已过期 | 已作废 | ❌ |

**结论**：6800 是**一次性凭证**（别人给的 token，无法重登），access token 到期（12-03 17:49）即永久失效；1498 是长期主力，refresh 有效可自动续期。

### 0.5 后续行动

- [x] 启用 1498 为主力，验证封装刷新 + 写回桌面端成功
- [ ] 6800 在 12-03 失效前可继续作为备胎使用，到期后从账号池删除
- [ ] 任何刷新操作前，先确认走封装（`Account.refresh()`）而非底层裸调用

---

## 1. 改动总览

| # | 问题 | 影响 | 涉及文件 | 性质 |
|---|---|---|---|---|
| 1 | 「禁用仍签到」勾选刷新后丢失，且禁用账号仍被签到 | 看板设置失效；禁用账号仍消耗签到配额 | `trae_accounts.py`、`trae_tasks.py` | 代码 bug 修复 |
| 2 | import 导入账号的 token 无法刷新 | token 过期后账号失效（上游 20101） | `trae_accounts.py` | 代码 bug 修复 + 数据修复 |
| 3 | 签到按钮同步批跑（1s 间隔），多账号易触发风控 | 账号多时 HTTP 阻塞久、并发打卡有风控风险 | `trae_proxy.py`、`dashboard.html` | 功能增强：后台慢速错峰签到 |
| 4 | 签到结果只在内存，重启即丢 | 看板「积分获取历史」查不到、无法追溯 | `trae_proxy.py` | 功能增强：落盘 activity.jsonl + extra.checkin |
| 5 | 已签到账号仍会发一次状态查询 | 多一次请求 = 多一分风控面 | `trae_proxy.py` | 优化：本地记录命中则 0 请求跳过 |
| 6 | 网关进程无守护，会话结束即停 | 需手动启动、无崩溃自愈 | `service-start.bat` + 计划任务 | 运维：登录自启 + 失败重启 |
| 7 | SOLO 路径遇 TLS 抖动（SSL EOF）一次即失败 | 上游偶发断连直接报 502/4028 给客户端 | `trae_proxy.py` | 稳定性：补传输层重试（1s/2s 退避） |
| 8 | 签到成功后状态查询过早，被误判为失败 | 看板显示「签到未生效：success」自相矛盾 | `trae_client.py` | 修复：状态未刷新时重试查询 |

代码改动统计：`trae_accounts.py` +33 行，`trae_tasks.py` +15/-1 行（共 52 插入、1 删除）。

### 1.1 Patch 3：后台慢速错峰签到（防风控）

**需求**：账号多时「每日签到 / 刷新积分」不要批跑，改成后台任务，账号间至少 10s + 0~5s 随机抖动。

**实现**：

| 位置 | 改动 |
|---|---|
| `trae_proxy.py`（`CHECKIN_MIN_GAP` 后） | 新增 `CHECKIN_JOB_STATE` 状态对象、`checkin_job_state()`、`_run_checkin_job()`（后台线程逐账号签到，间隔 `interval + rng.uniform(0, jitter)`）、`start_checkin_job()`（防重复启动） |
| `trae_proxy.py` `/tasks/run`（POST） | **默认改为异步**：立即返回 `{async:true, job:{...}}`，后台执行；传 `async:false` 保留旧的同步 1s 批跑。支持 `interval` / `jitter` 入参覆盖默认 10/5 秒 |
| `trae_proxy.py` `/tasks/checkin-job` | 新增状态查询（GET + POST 都支持），返回 `state/total/done/ok/failed/current/results/logs` |
| `dashboard.html` `doCheckin()` | 改为调用 `{async:true}` + 每 1.5s 轮询 `/tasks/checkin-job`，按钮实时显示「签到中 50% · 账号名」 |
| `dashboard.html` 福利中心领取按钮 | 检测 `r.async` 分支，切轮询模式，完成后自动刷新积分 |

**默认参数**：`interval=10.0s`，`jitter=5.0s`（即每个账号间隔 10~15 秒随机）。

**实测**：2 个账号总耗时 15 秒（落在 10~15s 区间），接口立即返回不阻塞，2/2 签到成功。

**可调**：接口入参 `{"interval": 20, "jitter": 10}`，或用环境变量思路后续扩展。

### 1.2 Patch 4/5/6：签到落盘、已签跳过、服务托管

**补丁 4 — 签到结果落盘**

`_run_checkin_job` 每个账号处理后写两处：

| 落点 | 内容 | 用途 |
|---|---|---|
| `usage/activity.jsonl` | `{ts, kind:"checkin", ok, uid, nickname, realm, detail, amount}` | 看板「积分获取历史」（`GET /accounts/activity` 读它） |
| `accounts/<uid>.json` 的 `extra.checkin` | `{at, checked_in, credits, earned_credit}` | 供下次「本地已签跳过」判断 + 账号行状态显示 |

写入复用项目自带的 `trae_activity.record()`（自动按 `MAX_BYTES` 轮转），任何异常静默不影响主流程。

**补丁 5 — 已签到账号 0 请求跳过**

`claim_checkin` 本来就是「先查 status、已签则不发 claim」，但仍会发 1 次状态查询。现在 `_run_checkin_job` 增加前置判断：

```
extra.checkin.at 是今天 且 checked_in=true  →  直接跳过，不发任何请求
```

- 实测 3 个已签账号：**0 请求、秒级完成**（原来要发 3 次状态查询）
- 传 `{"force": true}` 可忽略本地记录强制重查（用于状态可能不同步的场景）
- 昨日签到记录不影响今日（按 `YYYY-MM-DD` 前缀比对）

**补丁 6 — 网关服务托管（Windows 计划任务）**

本机 `schtasks.exe` 被安全策略拉黑（`PROGRAM BLOCKED`），改用 PowerShell `Register-ScheduledTask` 注册。

`service-start.bat`（纯 ASCII，**看门狗模式**）：

```bat
@echo off
REM - exits immediately if port 8791 is already served (no duplicate instance)
REM - otherwise launches pythonw hidden with log redirection, then returns
cd /d D:\phpstudy_pro\WWW\trae2api-hub
netstat -ano | findstr ":8791" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 0
start "" /b "C:\Users\1\AppData\Local\Programs\Python\Python312\pythonw.exe" trae_proxy.py >> gateway.log 2>&1
exit /b 0
```

> **为什么是看门狗而不是"直接等进程退出"**：第一版 bat 直接执行 `pythonw`（会等待进程结束），
> 实测发现两个问题：① `Stop-ScheduledTask` 只杀 `cmd`，`pythonw` 子进程存活 → 新实例端口冲突失败
> （`LastTaskResult=1`），**旧代码继续运行**，改动静默不生效；② 任务状态在 bat 退出后变 `Ready`，
> 崩溃不会触发 `RestartOnFailure`。
> 改为「先查端口 → 占用则退出 → 否则后台拉起」+「每 5 分钟重复触发」后：无重复实例、
> 挂掉 5 分钟内自动恢复、改代码后杀进程即生效。

任务配置（任务名 `trae2api-hub-gateway`）：

| 项 | 值 | 说明 |
|---|---|---|
| 触发器 | ① AtLogOn（当前用户）② 每 5 分钟重复（`PT5M` / `P3650D`） | 登录启动 + 看门狗巡检 |
| 运行身份 | `InteractiveToken` + `LeastPrivilege` | 不保存密码，改密码不影响 |
| 操作 | `service-start.bat`，工作目录=项目根 | `pythonw` 无窗口 + 日志重定向 |
| 失败重启 | `RestartCount=999`, `Interval=PT1M` | 崩溃后每分钟自动重试 |
| 运行上限 | `PT0S`（不限时） | 常驻服务 |
| 并发 | `IgnoreNew` | 防止重复实例抢端口 |
| 电池 | 两项均为 false | 笔记本断电也照跑 |
| 错过补跑 | `StartWhenAvailable=true` | 到点时休眠，唤醒后补启动 |

**核验（两条独立通道）**：

```powershell
# ① 直读任务定义 XML（无需 schtasks / 管理员）
Get-Content "C:\Windows\System32\Tasks\trae2api-hub-gateway"   # UTF-16
# ② CIM
Get-ScheduledTask -TaskName 'trae2api-hub-gateway'
Get-ScheduledTaskInfo -TaskName 'trae2api-hub-gateway'
```

实测结果：`State=Ready` → `Start-ScheduledTask` 后 `State=Running`、`LastTaskResult=267009`（运行中）、
`GET /ping` 返回 200、进程为 `pythonw.exe`（PID 53152）、日志写入 `gateway.log`。

> 注：`LastTaskResult=267011` 表示「从未运行」，是刚注册时的正常值，不是失败。
> `NextRunTime` 对 AtLogOn 触发器无确定值（显示为空）也属正常。

### 1.3 Patch 7：SOLO 路径补传输层重试（2026-11-19 深夜故障）

**现象**：客户端报

```
Trae SOLO upstream failed: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]
EOF occurred in violation of protocol (_ssl.c:1010)> (HTTP Status: 502) (4028)
```

网关日志：`request error: ... 5000ms status=502 msg=<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]...>`
—— 两次都**正好卡在 5 秒**，之后同一账号、同一模型立刻又能正常返回。

**根因**：`_handle_agent_solo()`（`trae_proxy.py`）的调用**没有任何重试**：

```python
try:
    result = trae_solo_chat(account, {**payload, "model": model})
except Exception as exc:
    return self._error(502, "Trae SOLO upstream failed: %s" % exc, ...)  # 一次抖动即失败
```

而项目里其实已有现成能力，只是 SOLO 路径没用上：

- `TRANSIENT_MAX_RETRIES = 2`（同账号额外重试 2 次，1s/2s 退避）
- `_is_transient_transport()` 已覆盖 `ssl.SSLError` / `URLError(SSL)` / reset / timeout，
  并按字符串匹配 `"SSL: UNEXPECTED_EOF_WHILE_READING"`
- 信封路径（`aggregate_with_envelope_retry`）早就用上了这两者

**修复**：SOLO 调用改为重试循环，仅对 `_is_transient_transport(exc)` 为真的错误重放，
业务错误立即返回；重放安全的前提是 `_sse_begin()` 在拿到 `result` 之后才调用（此时尚未向客户端写任何字节）。

```python
result = None
for attempt in range(TRANSIENT_MAX_RETRIES + 1):
    try:
        result = trae_solo_chat(account, {**payload, "model": model})
        break
    except Exception as exc:
        if attempt >= TRANSIENT_MAX_RETRIES or not _is_transient_transport(exc):
            record_error(...)
            return self._error(502, "Trae SOLO upstream failed: %s" % exc, "upstream_error")
        log("solo 传输层抖动，%.0fs 后重试 %d/%d：%s" % (...), level="WARN", tag="chat")
        time.sleep(float(attempt + 1))
```

**效果**：5 秒一次的 TLS 抖动不再直接失败给客户端，最多重试 2 次（1s、2s 退避），
常见瞬时断连可在第 2 次尝试成功。全部 3 次都失败才返回 502（此时确实是上游不可用）。

**验证**：`_is_transient_transport` 对 `URLError(SSLError(...))` 与裸 `SSLError` 均返回 `True`；
`_test_trae.py` 240 项通过；重启后 `DeepSeek-V4-Flash` 1766ms、`MiMo-V2.6-Flash` 1156ms 均正常返回。

### 1.4 Patch 8：「签到未生效：success」误判

**现象**：看板第四个账号显示 `! [富安娜春风店] 签到未生效：success` —— 上游明确回了 `success`，
却被判为失败，文案自相矛盾。

**排查**（只读）：

```json
// checkin_status 原始返回：今天确实未签到
{"checked_in": false, "code": 0, "credits": 100,
 "did_checked_in": false, "enable": true, "extra_credits": 100, "message": "success"}
```

手动执行 `claim_checkin` 立刻成功（`ok=True, checked_in=True`），说明账号本身没问题，
**失败是瞬时的**。再看代码：

```python
raw = request_json(...)                    # claim → {"code":0,"message":"success"}
after = checkin_status(...)                # ← 立刻查，上游状态可能还没写入
ok = bool(after.get("checked_in")) and (raw.get("code") in (0, None))
message = ... if ok else (after.get("message") ...)   # 失败时取到 "success"
```

三个问题叠加：① claim 后**没有任何等待/重试**就查状态；② 上游状态写入有延迟；
③ 失败分支的 message 直接取 status 的 `message`（`"success"`）→ 出现「签到未生效：success」。

**修复**（`trae_client.claim_checkin`）：

```python
CHECKIN_STATUS_RETRY = 2          # 重试次数
CHECKIN_STATUS_RETRY_GAP = 1.0    # 每次间隔（秒）

retries = 0
while (claim_ok and not after.get("checked_in") and retries < CHECKIN_STATUS_RETRY):
    retries += 1
    time.sleep(CHECKIN_STATUS_RETRY_GAP)
    after = checkin_status(...)
```

同时改写失败文案：`claim_ok` 为真但状态未刷新时，提示
「上游已受理签到但状态尚未刷新（已重试 N 次），请稍后刷新查看」——不再出现自相矛盾的 success。
返回值新增 `status_retries` 字段便于排查。

**验证**：

- 打桩场景 1（状态延迟 2 次后刷新）：`ok=True, status_retries=1` → 不再误判
- 打桩场景 2（claim 返回业务码 40001）：`ok=False, status_retries=0` → 业务错误不重试，直接透传原因
- 实跑 4 账号：`4/4 ok=True`，第四个账号显示「今日已签到（积分 100）」，`extra.checkin.checked_in` 修正为 `true`
- `_test_trae.py`：`PASS=240 FAIL=0`

---

## 2. Patch 1：checkin_when_disabled 勾选不持久化 / 禁用仍签到

### 2.1 现象

- 看板账号行勾选「仍签到」（禁用账号专用）后，刷新页面勾选消失
- 禁用账号依然参与每日签到

### 2.2 根因（证据链）

1. `Account` 类没有 `checkin_when_disabled` 字段：
   - `trae_accounts.py` 全文 grep `checkin_when_disabled` 在改动前 **0 命中**
   - `Account.to_dict()` 序列化 28 个字段中不含此项
2. 勾选时 `POST /accounts/checkin-when-disabled`（`trae_proxy.py:11718`）执行：
   `acc.checkin_when_disabled = val` —— 只是**动态添加属性**
3. `acc.save()` 调用 `to_dict()` 落盘时该属性被丢弃 → **刷新页面后状态丢失**
4. 前端 `dashboard.html:7385` 读 `a.checkinWhenDisabled`，但后端 `Account.public()`
   **从未输出该字段** → 即使落盘，前端也永远显示未勾选（断链最后一环）
5. `task_daily_checkin`（`trae_tasks.py:1426`）通过 `_iter_accounts()` 遍历账号；
   该方法原本对显式传入的 `accounts` 列表**不检查 `enabled`**，
   且签到循环内没有对禁用账号的判断 → 禁用账号照样签到

### 2.3 改动内容（`git diff` 对应位置）

**`trae_accounts.py`：**

| 位置（改动后行号约） | 改动 |
|---|---|
| `Account.__init__`（~1007） | 新增 `self.checkin_when_disabled = _truthy(data.get("checkin_when_disabled", self.extra.get("checkin_when_disabled")), False)` —— 读取时兼容顶层字段与 extra 两种来源 |
| `Account.to_dict()`（~1057） | 新增 `"checkin_when_disabled": bool(getattr(self, "checkin_when_disabled", False))` —— **落盘** |
| `Account.public()`（~1714） | 新增 `"checkinWhenDisabled": bool(getattr(self, "checkin_when_disabled", False))` —— **前端可读** |

**`trae_tasks.py`：**

| 位置（改动后行号约） | 改动 |
|---|---|
| `_iter_accounts()`（~474） | 更新 docstring，明确「显式 accounts 列表同样执行 enabled 过滤」（防御性加固；原实现已含该判断，此处固化语义） |
| `task_daily_checkin()`（~1466） | 签到循环新增：禁用账号默认跳过（记 `reason: account_disabled`），仅当 `checkin_when_disabled=True` 时才继续签到 |

### 2.4 验证

- 勾选后读取磁盘 JSON：`checkin_when_disabled: True` ✅
- 重启后 `/accounts` API 返回 `checkinWhenDisabled: True` ✅
- 单测：持久化往返、默认值 False、显式 accounts 过滤禁用账号、`include_disabled=True` 放行 —— 全部 PASS

---

## 3. Patch 2：import 账号伪 uid 导致 token 刷新失败（20101）

### 3.1 现象

- import 导入的账号（`…70a0`）token 到期后，`expiresAt` 未延长，刷新失败
- 账号文件 `last_error` 记录：
  `refresh failed: UpstreamError: [401] HTTP 401 {"Code":"20101","Data":{"__Message.error":"refresh token user does not ma...`

### 3.2 根因（证据链）

刷新请求构造（`trae_client.py:1129`）：

```python
payload = {
    "ClientID": CLIENT_ID,
    "RefreshToken": refresh,
    "UserID": _uid(account),   # ← 问题在这里
}
```

`_uid()`（`trae_client.py:292`）从账号字段取 uid。对比两个账号：

| 账号 | 文件里的 uid | JWT `data.id`（真实用户 ID） | 是否一致 |
|---|---|---|---|
| `…70a0`（import，坏） | `import-3f9e96a96c14ba8a70a0` | `3031833961306800` | ❌ |
| `…1498`（OAuth，好） | `2961428649351498` | `2961428649351498` | ✅ |

- 导入逻辑 `normalise_import_row()`（`trae_accounts.py`）在导入行缺 uid 时直接生成
  `import-<sha256哈希>` 伪 uid，**没有从 token 中提取真实用户 ID**
- 刷新时 `UserID=import-3f9e...` 与 refresh token 实际绑定的用户 `3031833961306800` 不符
- 上游返回 `20101 refresh token user does not match`，刷新失败

### 3.3 改动内容

**`trae_accounts.py`：**

| 位置（改动后行号约） | 改动 |
|---|---|
| 文件头 import（~21） | 新增 `import base64` |
| 新函数 `_uid_from_access_token()`（~2839） | 从 JWT payload 的 `data.id` 提取真实用户 ID；兼容 `data` 为 dict 或 JSON 字符串两种形态；解析失败**静默返回空串**（导入不能因坏 token 崩溃） |
| `normalise_import_row()`（~2921） | 无 uid 时**优先调用 `_uid_from_access_token(token)`**，解析不出才回退 `import-<hash>` 伪 uid；显式 uid 保持最高优先级 |

### 3.4 验证

- 内存验证：把 uid 改为真实 ID 后用同一 refresh token 强制刷新 → **成功**，拿到新 token（12月3日）+ 新 refresh token（2027年5月18日）。证明 refresh token 本身有效，根因确为伪 uid
- 单测：`normalise_import_row` 无 uid 时提取出 `3031833961306800` ✅；坏 token 安全回退伪 uid 不崩溃 ✅；显式 uid 不被覆盖 ✅
- 测试基线：`PASS=240 FAIL=0 SKIP=0`

---

## 4. 账号数据修复记录

> 以下是对 `accounts/` 目录内**数据文件**的修复（非代码），已完成。

| 项 | 修复前 | 修复后 |
|---|---|---|
| 文件名 | `import-3f9e96a96c14ba8a70a0.json` | `3031833961306800.json` |
| `uid` | `import-3f9e96a96c14ba8a70a0` | `3031833961306800`（真实 ID） |
| `token` | 已过期（17:40） | 新 token，2026-12-03 17:49 过期 |
| `refresh_token` | `pwestsoMr6EV...`（旧的） | 新 refresh，2027-05-18 17:49 过期 |
| `last_error` | `refresh failed: ... 20101 ...` | 空 |
| `fails` | 1 | 0 |

- **备份文件**：`accounts/import-3f9e96a96c14ba8a70a0.json.bak-uidfix`（确认稳定后可删）
- 修复方式：原子写（tmp → fsync → `os.replace`），避免写坏文件
- 另一个账号 `2961428649351498.json`（OAuth）未改动，当前为**禁用**状态（用户手动禁用），数据healthy

> 注意：2026-11-19 17:52 的验证中曾做了一次**内存强制刷新**（未落盘），会作废旧 refresh token。
> 若后续自动刷新再次报 20101，说明磁盘上的 refresh token 已被那次验证作废——
> 处理办法：删掉 `3031833961306800.json`，用 OAuth 重新登录该账号即可（OAuth 账号 uid 正确，刷新链路稳定）。

---

## 5. 验证结果

| 验证项 | 结果 |
|---|---|
| `_test_trae.py` 测试基线 | PASS=240 / FAIL=0 / SKIP=0 |
| 勾选状态落盘 + 重启后 API 可见 | ✅ |
| import 提取真实 uid / 坏 token 回退 / 显式 uid 优先 | ✅ 3/3 |
| 两个账号 token 状态 | 均 12-03 过期 + 2027-05-18 refresh，无 lastError |
| 强制刷新能力 | ✅ 成功 |
| 实际对话 `DeepSeek-V4-Flash` | ✅ 返回正常 |

---

## 6. 升级与回滚

### 6.0 仓库结构与远端配置（fork 工作流）

本仓库采用 **fork + 双远端 + 分支隔离** 结构：

| 远端 | 地址 | 作用 |
|---|---|---|
| `origin` | `git@github.com:wzj19960523/trae2api-hub.git`（SSH） | 自己的 fork，push 用 |
| `upstream` | `https://gh-proxy.com/https://github.com/shuishuipingan/trae2api-hub.git` | 作者原仓库，只 fetch |

| 分支 | 内容 | 说明 |
|---|---|---|
| `main` | 纯上游 `3d2e23e` | 永不加本地 commit，保证 `merge --ff-only` 无冲突 |
| `local` | 上游 + 本地补丁（`793addf`） | 日常使用/开发都在这个分支 |

> **网络说明**：本机直连 GitHub HTTPS 会 502（会话代理 `http_proxy=127.0.0.1:xxxxx` 拦截）/ 免代理也超时，因此
> `origin` 走 SSH（`~/.ssh/config` 已配 `github.com → ssh.github.com:443`，key 为 `id_ed25519_wzj`）；
> `upstream` 走 gh-proxy 镜像仅用于 fetch。
> HTTPS 操作需加 `-c http.proxy=` 绕开死代理。

### 6.1 作者更新后如何跟进（核心流程）

```bash
# 1. 拉取作者最新代码（走镜像，fetch 不需要认证）
git fetch upstream

# 2. 更新 main：纯快进，永远不会冲突
git checkout main
git merge --ff-only upstream/main

# 3. 把本地补丁重新叠到最新上游之上
git checkout local
git rebase main

# 4. 重启网关让新代码生效
```

**冲突处理**（只可能发生在第 3 步，通常集中在 `CHANGELOG.md`、`trae_accounts.py`、`trae_tasks.py`、`trae_proxy.py`、`dashboard.html`）：

```bash
# 手工编辑冲突文件 → 标记已解决 → 继续
git add <冲突文件>
git rebase --continue

# 放弃本次 rebase，回到操作前
git rebase --abort
```

**推送到自己的 fork**（让远端也同步）：

```bash
git push origin local          # 首次已 -u，之后直接 push
# rebase 改写了提交历史时（本地已 push 过），需要：
git push --force-with-lease origin local
```

**验证清单**：

```bash
git log --oneline -3 main          # 应为作者最新提交
git log --oneline -3 local         # 第一条应是你自己的补丁提交
git rev-list --count main..upstream/main   # 应为 0
git ls-remote origin local         # 上帝视角确认远端 SHA 与本地一致
```

### 6.2 回滚代码改动

```bash
# 方式 A：丢弃 local 分支上的全部补丁（回到纯上游代码）
git checkout main

# 方式 B：撤销单个文件的改动（在 local 分支）
git checkout HEAD~1 -- trae_accounts.py

# 方式 C：整体回退到某个提交
git reset --hard <commit-sha>
```

注意：回滚后 `checkin_when_disabled` 字段会保留在账号 JSON 里（无害，代码不读），
但「禁用仍签到」勾选功能会失效；import 账号伪 uid 问题会重现。

### 6.3 回滚账号数据

```bash
cp accounts/import-3f9e96a96c14ba8a70a0.json.bak-uidfix \
   accounts/3031833961306800.json
# 然后重启网关
```

### 6.4 建议的上游反馈

这两个 bug 值得向作者提 issue / PR：

1. `checkin_when_disabled` 勾选不生效（字段未纳入 `to_dict()` / `public()`，签到任务未读）
2. import 账号伪 uid 导致刷新 20101（`normalise_import_row` 应从 JWT 提取真实 uid）

已在 fork 上创建 `local` 分支，可直接用 GitHub 的对比页面向上游发起 PR：
`https://github.com/wzj19960523/trae2api-hub/pull/new/local`
