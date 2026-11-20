"""本轮交叉复核修复的回归测试（零网络、零副作用）。

覆盖 2026-11-19/20 两轮复核修掉的关键缺陷，防止再退化：
  R1  safe_uid 路径穿越与 Windows 保留名
  R2  _as_float 的 inf/nan 收敛
  R3  签到互斥：busy 语义 + 异常路径锁释放
  R4  签到失败不覆盖当天已成功记录
  R5  energy 与 credits.remain 在"全未知"时同步为 None
  R6  禁用+勾选「禁用仍签到」会真正进入签到循环

运行：python _test_review_regressions.py
"""
import json
import os
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import trae_accounts
import trae_tasks

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  PASS  %s" % name)
    else:
        FAIL += 1
        print("  FAIL  %s  %s" % (name, detail))


def test_safe_uid():
    print("[R1] safe_uid")
    bad = ["../../evil", "..\\evil", "/etc/passwd", "C:/windows/x",
           "..", ".", "evil.", "evil. ", "CON", "NUL", "COM1", "con.txt",
           "a\x00b", "a\nb", "x" * 65, "   ", ""]
    for value in bad:
        check("拒绝 %r" % value, trae_accounts.safe_uid(value) == "",
              "实际=%r" % trae_accounts.safe_uid(value))
    good = ["1993839615946135", "tok-abc_123", "import-3f9e96a96c14ba8a",
            "富安娜春风店", "user.name"]
    for value in good:
        got = trae_accounts.safe_uid(value)
        check("保留 %r" % value, got == value, "实际=%r" % got)


def test_as_float():
    print("[R2] _as_float")
    cases = [("1e400", 0.0), (float("inf"), 0.0), (float("-inf"), 0.0),
             (float("nan"), 0.0), ("597.56", 597.56), (" 597.56 ", 597.56),
             (None, 0.0), (True, 0.0), ("abc", 0.0)]
    for value, expect in cases:
        got = trae_tasks._as_float(value)
        check("_as_float(%r)=%r" % (value, expect), got == expect,
              "实际=%r" % got)


def test_mutex():
    print("[R3] 签到互斥")
    # busy 语义
    trae_tasks.CHECKIN_MUTEX.acquire()
    try:
        res = trae_tasks.task_daily_checkin(accounts=[], trigger="manual")
        check("busy 时 ok=True", res.get("ok") is True, "实际=%r" % res.get("ok"))
        check("busy 时 skipped=True", res.get("skipped") is True)
        check("busy 时 stats.busy", (res.get("stats") or {}).get("busy") is True)
    finally:
        trae_tasks.CHECKIN_MUTEX.release()

    # 异常路径必须释放锁
    original = trae_tasks._task_daily_checkin_locked
    try:
        trae_tasks._task_daily_checkin_locked = lambda **kw: (_ for _ in ()).throw(
            RuntimeError("boom"))
        try:
            trae_tasks.task_daily_checkin(accounts=[], trigger="manual")
        except RuntimeError:
            pass
        check("异常后锁已释放", not trae_tasks.CHECKIN_MUTEX.locked())
    finally:
        trae_tasks._task_daily_checkin_locked = original

    # 正常路径可连续调用
    try:
        trae_tasks._task_daily_checkin_locked = lambda **kw: {"ok": True, "stub": True}
        first = trae_tasks.task_daily_checkin(accounts=[], trigger="manual")
        second = trae_tasks.task_daily_checkin(accounts=[], trigger="manual")
        check("连续两次都成功", first.get("stub") and second.get("stub"))
    finally:
        trae_tasks._task_daily_checkin_locked = original


def test_checkin_record_not_overwritten():
    print("[R4] 失败不覆盖已签到记录")
    tmp = tempfile.mkdtemp(prefix="t2a_reg_")
    uid = "9999999999999999"
    doc = {
        "uid": uid, "enabled": True, "realm": "cn",
        "account": {"access_token": "tok", "refresh_token": "r"},
        "extra": {"checkin": {"at": "2026-11-19 10:00:00",
                              "checked_in": True, "credits": 100}},
    }
    path = os.path.join(tmp, uid + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
    account = trae_accounts.Account(doc, directory=tmp)

    class FailingClient:
        @staticmethod
        def claim_checkin(acc, realm=None):
            return {"ok": False, "already": False, "checked_in": False,
                    "credits": None, "earned_credit": 0,
                    "message": "network down", "raw": {}}

    original_client = trae_tasks._client_module
    try:
        trae_tasks._client_module = lambda: FailingClient
        trae_tasks._task_daily_checkin_locked(
            accounts=[account], trigger="manual",
            pacing={"interval": 0, "jitter": 0})
    finally:
        trae_tasks._client_module = original_client

    with open(path, encoding="utf-8") as fh:
        saved = json.load(fh)
    record = (saved.get("extra") or {}).get("checkin") or {}
    check("失败后 checked_in 仍为 True", record.get("checked_in") is True,
          "实际=%r" % record.get("checked_in"))
    check("失败后 at 未被改写", record.get("at") == "2026-11-19 10:00:00",
          "实际=%r" % record.get("at"))


def test_energy_consistency():
    print("[R5] energy 与 credits.remain 一致")
    # 构造全未知：entitlement 为空、usage 为空
    class UnknownAccount:
        uid = "u1"
        enabled = True
        access_token = "t"
        realm = "cn"
        plan = ""
        usage = {}
        entitlement = {}
        extra = {}

    original_iter = trae_tasks._iter_accounts
    try:
        trae_tasks._iter_accounts = lambda *a, **k: [UnknownAccount()]
        view = trae_tasks.fetch_tasks_view(pool=None, realm="cn")
    finally:
        trae_tasks._iter_accounts = original_iter
    summary = view.get("summary") or {}
    check("energy 为 None", summary.get("energy") is None,
          "实际=%r" % summary.get("energy"))
    check("credits.remain 同步为 None",
          (summary.get("credits") or {}).get("remain") is None,
          "实际=%r" % (summary.get("credits") or {}).get("remain"))


def test_disabled_opt_in():
    print("[R6] 禁用+勾选会真正签到")
    calls = []

    class FakeClient:
        @staticmethod
        def claim_checkin(acc, realm=None):
            calls.append(acc.uid)
            return {"ok": True, "already": True, "checked_in": True,
                    "credits": 100, "earned_credit": 0, "message": "ok",
                    "raw": {}}

    class Acc:
        def __init__(self, uid, enabled, allow):
            self.uid = uid
            self.enabled = enabled
            self.checkin_when_disabled = allow
            self.token = "t"
            self.access_token = "t"
            self.realm = "cn"
            self.extra = {}
            self.plan = ""

        def save(self, directory=None):
            pass

    accounts = [Acc("dis-allow", False, True), Acc("dis-deny", False, False),
                Acc("enabled", True, False)]
    original_client = trae_tasks._client_module
    try:
        trae_tasks._client_module = lambda: FakeClient
        trae_tasks._task_daily_checkin_locked(
            accounts=accounts, trigger="manual",
            pacing={"interval": 0, "jitter": 0})
    finally:
        trae_tasks._client_module = original_client
    check("只对 勾选禁用 + 启用 发起签到", calls == ["dis-allow", "enabled"],
          "实际=%r" % calls)


def test_solo_quota_detection():
    print("[R7] SOLO 配额错误识别（换号重试的判定依据）")
    import trae_proxy
    cases = [
        ("solo error 4008: Your requests have exceeded the quota.", True),
        ("solo error 4008: x", True),
        ("solo HTTP 500: boom", False),
        ("solo error 5001: rate limited", False),
        ("connection reset by peer", False),
        ("", False),
        (None, False),
    ]
    for msg, expect in cases:
        got = trae_proxy._solo_quota_exhausted(RuntimeError(msg) if msg else None)
        check("_solo_quota_exhausted(%r)=%r" % (msg, expect), got is expect,
              "实际=%r" % got)


def test_model_suggestion():
    """4023 错误提示：缩写能给出正确建议，乱码不误报，向后兼容。"""
    import trae_proxy
    detail = "trae 4023 model_unknown: We're sorry, the model is unknown."
    # 缩写 -> 建议真实目录 id
    msg, kind = trae_proxy.friendly_upstream_error(4023, detail, model="D4f")
    check("4023 kind", kind == "model_unknown", "实际=%r" % kind)
    check("D4f 建议 DeepSeek-V4-Flash", "DeepSeek-V4-Flash" in msg,
          "文案=%r" % msg[:120])
    # 乱码 -> 不给误导性建议
    msg2, _ = trae_proxy.friendly_upstream_error(4023, detail,
                                                 model="gpt-xyz-nonexist")
    check("乱码不误报建议", "你可能想填" not in msg2, "文案=%r" % msg2[:120])
    # 不传 model -> 向后兼容（不抛异常）
    msg3, kind3 = trae_proxy.friendly_upstream_error(4023, detail)
    check("不传 model 兼容", kind3 == "model_unknown" and "请从 /v1/models" in msg3,
          "文案=%r" % msg3[:120])
    # 其他错误码不受 model 参数影响
    msg4, kind4 = trae_proxy.friendly_upstream_error(
        4008, "trae 4008 quota exceeded", model="D4f")
    check("4008 不受影响", kind4 == "quota_exceeded", "实际=%r" % kind4)


if __name__ == "__main__":
    for fn in (test_safe_uid, test_as_float, test_mutex,
               test_checkin_record_not_overwritten, test_energy_consistency,
               test_disabled_opt_in, test_solo_quota_detection,
               test_model_suggestion):
        fn()
    print("\n汇总: PASS=%d FAIL=%d" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)
