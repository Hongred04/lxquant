# -*- coding: utf-8 -*-
"""策略准入判定 —— 这套规则够不够格当「默认策略」。

为什么单独成一个模块（而不是塞进 backtest 里）：
  · 判定标准要能被单独引用、单独测试，不需要跑一次完整回测；
  · 前端只要「一句结论 + 逐条理由」，不该自己从一堆指标里拼判断逻辑；
  · 以后加一条门槛只动 CHECKS 这一个列表，回测页和命令行同时生效；
  · 结论是纯函数算出来的，不依赖文件、网络、时间 —— 好测、可复现。

口径（先说清楚，否则结论会被误读）：
  「折」= 把交易按买入时间排序后等分成 5 段，每段单独算平均收益。
  稳健分 robust = 0.6 × 中位折 + 0.4 × 最差折。
  为什么看折间表现而不是总体均值：一两次 +40% 的幸运单就能把均值拉高，
  但"每一段行情里都不亏"骗不了人 —— 这正是实盘在意的。

结论分四级，刻意不用「及格/不及格」二分：
  insufficient  样本不够，不下结论（最诚实的回答）
  fail          不建议当默认
  watch         勉强能用，但别当唯一依据
  pass          可以当默认
"""
from __future__ import annotations

# ---------------------------------------------------------------- 门槛
# 全部集中在这里：改阈值不用翻逻辑，也不会和前端说明文字对不上。
MIN_TRADES = 30          # 少于 30 笔，分 5 折每折不足 6 笔，统计上没有意义
MIN_WORST_FOLD = 0.0     # 「可以当默认」要求最差一折也为正 —— 核心门槛
MIN_MEDIAN_FOLD = 0.0    # 中位折的平均收益必须为正
MIN_ROBUST = 0.0         # 稳健分必须为正
MIN_PAYOFF = 1.0         # 盈亏比 < 1 = 亏的比赚的多，长期必亏
# 「能用但别当唯一依据」的容忍线。这几个值不是拍脑袋，是照着实测分布定的：
# 当前默认策略（oversold_bounce，250 天 / 60 只）最差折 -2.56%、中位折 +0.19%、
# 均值 +2.56%、盈亏比 2.46 —— 整体期望为正，但确实有一段行情会亏。
# 把它一刀切成「不能用」没有信息量，不如说清"哪一段会亏多少、还能不能拿"。
WATCH_WORST_FOLD = -3.0  # 最差折亏超 3% 就不能只算"波动"，那是真亏
WATCH_ROBUST = -1.5      # 稳健分低于这条线，说明折间表现已经不像同一套规则


def _num(v, default=None):
    """把可能为 None / NaN / 字符串的值收成 float，失败返回 default。"""
    try:
        x = float(v)
    except Exception:
        return default
    return x if x == x else default      # 过滤 NaN


def _checks(summary: dict) -> list:
    """逐条判据。每条都带「指标值 / 门槛 / 一句人话 / 三态」，前端直接渲染。

    ``level`` 有三档：ok（达标）、watch（没到"可以当默认"的线，但还在
    "能用"的容忍范围内）、no（真不行）。三态是为了避免「结论写着 watch，
    下面却一片红叉」这种自相矛盾的呈现。
    """
    s = summary or {}
    n = int(_num(s.get("count"), 0) or 0)
    worst = _num(s.get("worst"))
    med = _num(s.get("median"))
    robust = _num(s.get("robust"))
    payoff = _num(s.get("payoff"), 0.0)

    out = []

    # 1) 样本量 —— 不合格时后面的判据都没意义，所以要单独一条
    ok = n >= MIN_TRADES
    out.append({
        "key": "samples", "label": "交易笔数", "ok": ok,
        "level": "ok" if ok else "no",
        "value": n, "need": f"≥ {MIN_TRADES}",
        "text": f"{n} 笔" + ("" if ok else f"，少于 {MIN_TRADES} 笔，结论不可信"),
    })

    # 2) 最差一折 —— 核心门槛：连最难的那段行情都不亏，才配叫"稳"
    ok = worst is not None and worst > MIN_WORST_FOLD
    out.append({
        "key": "worst_fold", "label": "最差一段行情", "ok": ok,
        # 没到"可以当默认"的线，但还在"能用"的容忍范围内 → 标黄而不是标红
        "level": "ok" if ok else ("watch" if (worst is not None and worst > WATCH_WORST_FOLD) else "no"),
        "value": None if worst is None else round(worst, 2),
        "need": f"> {MIN_WORST_FOLD:.0f}%",
        "text": ("没有分折数据" if worst is None else
                 f"最差的一折 {worst:+.2f}%" + ("，最难的时候也在赚" if ok else "，说明换个行情就亏")),
    })

    # 3) 中位折 —— 一半以上的时间段要为正，避免"靠某一段救全场"
    ok = med is not None and med > MIN_MEDIAN_FOLD
    out.append({
        "key": "median_fold", "label": "中位一段", "ok": ok,
        "level": "ok" if ok else "no",
        "value": None if med is None else round(med, 2),
        "need": f"> {MIN_MEDIAN_FOLD:.0f}%",
        "text": ("没有分折数据" if med is None else
                 f"中位 {med:+.2f}%" + ("，过半时间段是赚的" if ok else "，多数时间段在亏")),
    })

    # 4) 稳健分 —— 折间表现的合成分，低于 0 等于"换个时段就白干"
    ok = robust is not None and robust > MIN_ROBUST
    out.append({
        "key": "robust", "label": "稳健分", "ok": ok,
        "level": "ok" if ok else ("watch" if (robust is not None and robust > WATCH_ROBUST) else "no"),
        "value": None if robust is None else round(robust, 2),
        "need": f"> {MIN_ROBUST:.0f}",
        "text": ("没有分折数据" if robust is None else
                 f"{robust:+.2f}" + ("，跨时段站得住" if ok else "，跨时段不成立")),
    })

    # 5) 盈亏比 —— 胜率低不要紧，但赚的要大于亏的
    ok = payoff >= MIN_PAYOFF
    out.append({
        "key": "payoff", "label": "盈亏比", "ok": ok,
        "level": "ok" if ok else "no",
        "value": round(payoff, 2),
        "need": f"≥ {MIN_PAYOFF:.1f}",
        "text": f"{payoff:.2f}" + ("，亏小赚大" if ok else "，赢的还不如亏的多"),
    })
    return out


def judge(summary: dict) -> dict:
    """给一次回测的汇总打分，回答「能不能当默认策略」。

    入参直接用 ``backtest.run_backtest(...)["summary"]``（里面已经有
    robust / median / worst / folds / payoff，由 robust_score + summarize 产出）。

    返回::

        {
          "pass":   bool,          # 能不能当默认
          "level":  "pass" | "watch" | "fail" | "insufficient",
          "label":  "可以当默认策略",       # 一句话结论（给人看）
          "note":   "补充说明",             # 为什么是这个结论
          "checks": [{key,label,ok,value,need,text}, ...],  # 逐条判据
          "rules":  {..."门槛常量"...},     # 让前端能写清"按什么标准判的"
        }

    判定顺序（后面的判据只在样本够的时候才影响结论）：
      样本不足 → insufficient
      最差折不达标 → fail（核心门槛，一票否决）
      其它项不达标 → watch
      全达标 → pass
    """
    s = summary or {}
    checks = _checks(s)
    by = {c["key"]: c for c in checks}

    def _f(k: str) -> float:
        return _num(by[k]["value"], 0.0) or 0.0

    rules = {
        "min_trades": MIN_TRADES, "min_worst_fold": MIN_WORST_FOLD,
        "min_median_fold": MIN_MEDIAN_FOLD, "min_robust": MIN_ROBUST,
        "min_payoff": MIN_PAYOFF,
        # 中间档的容忍线也一起给出去，前端才能解释「为什么这次是 watch 不是 fail」
        "watch_worst_fold": WATCH_WORST_FOLD, "watch_robust": WATCH_ROBUST,
    }

    # 样本量不够时，其他指标全是噪音 —— 直接给 insufficient，别假装有结论
    if not by["samples"]["ok"]:
        return {
            "pass": False, "level": "insufficient",
            "label": "样本还不够，先别下结论",
            "note": f"只有 {by['samples']['value']} 笔交易，分折统计没有意义。"
                    f"把回测范围拉长（更多股票或更长时间）再来判。",
            "checks": checks, "rules": rules,
        }

    if not by["worst_fold"]["ok"]:
        worst = _f("worst_fold")
        med = _f("median_fold")
        robust = _f("robust")
        # 中间档：整体期望为正、只有某一段亏，且亏得还在可忍受范围。
        # 这一档刻意不叫「通过」——它意味着"可以跑，但有一段行情会让你难受"。
        if (worst > WATCH_WORST_FOLD and med > MIN_MEDIAN_FOLD
                and robust > WATCH_ROBUST and by["payoff"]["ok"]):
            return {
                "pass": False, "level": "watch",
                "label": "能用，但有一段行情会亏",
                "note": f"整体均值 {_num(s.get('avg_ret'), 0):+.2f}%、盈亏比 {_f('payoff'):.2f}，"
                        f"期望是正的；但最差的一段亏 {worst:+.2f}%。"
                        f"能跑，别重仓、别当成唯一依据。",
                "checks": checks, "rules": rules,
            }
        return {
            "pass": False, "level": "fail",
            "label": "不建议当默认策略",
            "note": f"最差一折 {worst:+.2f}% —— 换个行情就亏，"
                    f"说明它赚的是特定时段的运气，不是可重复的规则。",
            "checks": checks, "rules": rules,
        }

    bad = [c for c in checks if not c["ok"]]
    if bad:
        names = "、".join(c["label"] for c in bad)
        return {
            "pass": False, "level": "watch",
            "label": "勉强能用，但别当唯一依据",
            "note": f"最差时段扛住了，但{names}没达标。",
            "checks": checks, "rules": rules,
        }

    return {
        "pass": True, "level": "pass",
        "label": "可以当默认策略",
        "note": f"{by['samples']['value']} 笔交易、"
                f"最差一折 {_f('worst_fold'):+.2f}%、稳健分 {_f('robust'):+.2f} —— "
                f"每一段行情都站得住。",
        "checks": checks, "rules": rules,
    }
