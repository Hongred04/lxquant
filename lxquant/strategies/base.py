# -*- coding: utf-8 -*-
"""策略插件的公共底座。

一个策略 = 一组「关卡(gate)」+ 一个评分函数 + 一份参数默认值。

设计要点：
  · 实盘选股(screener/analyzer) 和 回测(backtest) 调用的是**同一组 gate**，
    所以回测出来的东西就是你实盘会下的单，不会两套逻辑各算各的。
  · 关卡按「计算成本」排序，便宜的先算，贵的后算，回测里能省大量时间。
  · 想加一个新方案：在 data/strategies/ 里放一个 .py 文件，重启即可。
    见本文件末尾的注释模板。
"""
import numpy as np

# ---------------------------------------------------------------- 惰性事实表
class Facts(dict):
    """按需计算的事实表：谁用到才去算谁。

    回测里一只要跑几百天，如果每天把所有指标都算一遍会慢十倍；
    有了它，便宜的关卡先判，一旦不过就直接短路，贵的筹码/位置根本不算。
    """

    def __init__(self, builders: dict):
        super().__init__()
        self._builders = builders

    def __missing__(self, key):
        fn = self._builders.get(key)
        if fn is None:
            raise KeyError(key)
        v = fn()
        self[key] = v
        return v


# ---------------------------------------------------------------- 判断上下文
class Ctx:
    """一次判断所需的全部数据。实盘传当天的行情，回测用 at(i) 把视角挪到历史某天。"""

    def __init__(self, code: str, name: str, daily, k5=None, rt=None,
                 i: int | None = None, shared: dict | None = None):
        self.code = code
        self.name = name
        self.daily = daily                      # 完整日线（不要在这上面直接取最后一行）
        self.k5 = k5                            # 5/30 分钟线，回测时没有
        self.rt = rt                            # 实时快照，回测时没有
        self.i = (len(daily) - 1) if i is None else int(i)
        self._shared = shared if shared is not None else {}

    def at(self, i: int) -> "Ctx":
        """回测用：把视角挪到第 i 根 K 线，之后所有计算只看 i 及之前，杜绝前视。"""
        return Ctx(self.code, self.name, self.daily, None, None, i, self._shared)

    @property
    def hist(self):
        """截至当前的日线切片（含当前这根）。"""
        return self.daily.iloc[:self.i + 1]

    def row(self):
        return self.daily.iloc[self.i]

    def close(self) -> float:
        return float(self.daily["close"].iloc[self.i])

    def memo(self, key: str, fn):
        """跨 at() 共享的缓存，用来放整段序列这种「算一次全用」的东西。"""
        if key not in self._shared:
            self._shared[key] = fn()
        return self._shared[key]


# ---------------------------------------------------------------- 关卡
class Gate:
    """一道过滤条件。

    fn(facts, ctx, p) -> {"ok": bool, "why": str}
      why 是「没过的话差在哪」的人话说明，直接显示在界面上。
    cost：1 很快（读现成数字）、2 中等（扫最近几十根）、3 很慢（重算筹码分布）。
         回测里按 cost 升序跑，能省掉大部分计算。
    enable_key：参数里哪个开关控制它；关掉时这一关整个不出现（不算拦截，也不显示）。
    """

    def __init__(self, key: str, label: str, hint: str, fn, cost: int = 1,
                 enable_key: str | None = None):
        self.key = key
        self.label = label
        self.hint = hint
        self.fn = fn
        self.cost = int(cost)
        self.enable_key = enable_key

    def active(self, p: dict) -> bool:
        return True if not self.enable_key else bool(p.get(self.enable_key, True))

    def eval(self, facts: Facts, ctx: Ctx, p: dict) -> dict:
        try:
            r = self.fn(facts, ctx, p) or {}
        except Exception as e:                              # noqa: BLE001
            return {"ok": False, "why": "算不出来（%s）" % type(e).__name__}
        return {"ok": bool(r.get("ok")), "why": str(r.get("why") or "")}


# ---------------------------------------------------------------- 策略
class Strategy:
    key = "base"
    name = "未命名"
    desc = ""
    # 参数默认值，会合并进 config.DEFAULT_PARAMS
    defaults: dict = {}
    # 评分权重默认值，会合并进 config.DEFAULT_WEIGHTS
    weights: dict = {}
    # 关卡表，子类必须填
    gates: list = []

    # ---- 要子类实现的三件事 ----
    def facts(self, ctx: Ctx, p: dict) -> Facts:
        """返回惰性事实表。只有被 gate 引用到的键才会真的去算。"""
        return Facts({})

    def score(self, f: Facts, checks: dict, p: dict) -> float:
        """0~100 综合分。默认按「过了几关」给分，子类可以覆盖成更细的打分。"""
        ks = [g.key for g in self.gate_list(p)]
        if not ks:
            return 0.0
        return round(sum(1 for k in ks if checks.get(k)) / len(ks) * 100, 2)

    def extra_checks(self, f: Facts, ctx: Ctx, p: dict) -> dict:
        """除了关卡之外，额外想报给界面的真假值（老的 close_ma / tail 这类）。"""
        return {}

    # ---- 通用 ----
    def gate_list(self, p: dict) -> list:
        return [g for g in self.gates if g.active(p)]

    def check_all(self, f: Facts, ctx: Ctx, p: dict) -> tuple:
        """跑一遍所有关卡，返回 (checks 字典, 给界面用的关卡明细)。"""
        checks, rows = {}, []
        for g in sorted(self.gate_list(p), key=lambda x: x.cost):
            r = g.eval(f, ctx, p)
            checks[g.key] = r["ok"]
            rows.append({"key": g.key, "label": g.label, "hint": g.hint,
                         "ok": r["ok"], "why": r["why"]})
        checks.update(self.extra_checks(f, ctx, p))
        rows.sort(key=lambda x: [g.key for g in self.gate_list(p)].index(x["key"]))
        return checks, rows

    def signal_at(self, ctx: Ctx, p: dict) -> bool:
        """回测用：这一天所有关卡是否都过。短路求值，贵的关卡排在后面。"""
        f = self.facts(ctx, p)
        for g in sorted(self.gate_list(p), key=lambda x: x.cost):
            if not g.eval(f, ctx, p)["ok"]:
                return False
        return True


# ---------------------------------------------------------------- 小工具
def pct(v) -> str:
    return "%+.2f%%" % (float(v) * 100)


def num_or_none(v, nd: int = 4):
    try:
        v = float(v)
        if not np.isfinite(v):
            return None
        return round(v, nd)
    except Exception:
        return None
