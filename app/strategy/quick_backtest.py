import asyncio
import math
from datetime import UTC, datetime
from statistics import mean, pstdev
from typing import Any

import httpx

DEFAULT_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "JPM",
    "XOM",
    "JNJ",
    "PG",
]
BENCHMARK = "SPY"
CROSS_ASSET_UNIVERSE = ["SPY", "EFA", "TLT", "IEF", "LQD", "HYG", "GLD", "DBC", "UUP"]
BACKTEST_ADAPTERS: dict[str, dict[str, Any]] = {
    "momentum": {
        "adapter": "US_EQUITY_PRICE_MOMENTUM",
        "label": "纯价格动量适配器",
        "mode": "EXPLORATORY_MATCH",
        "score": 0.72,
        "eligible_for_ranking": True,
        "implemented": ["价格动量信号", "月度多空组合", "换手成本", "简化借券成本"],
        "missing": ["历史股票池", "真实逐股借券费", "退市收益"],
    },
    "low_volatility": {
        "adapter": "US_EQUITY_PRICE_LOW_VOLATILITY",
        "label": "纯价格低波动适配器",
        "mode": "EXPLORATORY_MATCH",
        "score": 0.70,
        "eligible_for_ranking": True,
        "implemented": ["历史波动率信号", "月度多空组合", "换手成本", "简化借券成本"],
        "missing": ["历史股票池", "真实逐股借券费", "退市收益"],
    },
    "cross_asset_etf": {
        "adapter": "CROSS_ASSET_ETF_RESIDUAL_REVERSAL",
        "label": "跨资产 ETF 代理适配器",
        "mode": "RESEARCH_PROXY",
        "score": 0.55,
        "eligible_for_ranking": False,
        "implemented": ["九类流动 ETF", "五日残差反转", "多空组合", "统一交易成本"],
        "missing": ["论文原始八类资产数据", "稳健主成分模型", "期货换月", "真实融资成本"],
    },
}


def infer_strategy_profile(text: str) -> str | None:
    normalized = text.lower()
    if "cross-asset" in normalized or "跨资产" in text:
        return "cross_asset_etf"
    unsupported_conditions = (
        "borrow fee",
        "borrowing fee",
        "securities lending",
        "institutional constraint",
        "constraint",
        "intermediary capital",
        "information cost",
        "publication timing",
        "借券费",
        "做空费用",
        "机构约束",
        "约束",
        "中介资本",
        "信息获取",
        "发表时机",
        "知晓度",
    )
    if any(term in normalized for term in unsupported_conditions):
        return None
    if any(
        term in normalized
        for term in ("low-volatility", "low volatility", "low beta", "low-beta")
    ) or any(term in text for term in ("低波动", "低贝塔")):
        return "low_volatility"
    if "momentum" in normalized or "动量" in text:
        return "momentum"
    return None


async def run_quick_backtest(profile: str = "momentum") -> dict[str, Any]:
    """Run an intentionally simple supported cross-sectional strategy proxy."""
    if profile == "cross_asset_etf":
        return await _run_cross_asset_etf_backtest()
    base_profile = profile.removesuffix("_v2")
    adapter = BACKTEST_ADAPTERS.get(base_profile)
    if not adapter:
        raise ValueError(f"没有适配 {profile} 的快速回测模型")
    symbols = [*DEFAULT_UNIVERSE, BENCHMARK]
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "Mozilla/5.0 QRI/0.1"},
    ) as client:
        results = await asyncio.gather(*(_fetch_daily(client, symbol) for symbol in symbols))
    market = dict(zip(symbols, results, strict=True))
    dates = [item["date"] for item in market[BENCHMARK]]
    by_symbol = {
        symbol: {item["date"]: item for item in rows} for symbol, rows in market.items()
    }
    common_dates = [
        date
        for date in dates
        if all(date in by_symbol[symbol] for symbol in DEFAULT_UNIVERSE)
    ]
    month_ends = _month_ends(common_dates)
    month_end_set = set(month_ends)
    close = {
        symbol: [float(by_symbol[symbol][date]["close"]) for date in common_dates]
        for symbol in symbols
    }
    weights = {symbol: 0.0 for symbol in DEFAULT_UNIVERSE}
    equity = 1.0
    benchmark_equity = 1.0
    equity_curve: list[dict[str, Any]] = []
    daily_returns: list[float] = []
    trades: list[dict[str, Any]] = []
    active = False
    total_cost = 0.0
    previous_spy = close[BENCHMARK][0]

    for index, date in enumerate(common_dates):
        if index:
            strategy_return = sum(
                weights[symbol]
                * (close[symbol][index] / close[symbol][index - 1] - 1.0)
                for symbol in DEFAULT_UNIVERSE
            )
            borrow_cost = sum(abs(min(weight, 0.0)) for weight in weights.values()) * (
                0.03 / 252
            )
            net_return = strategy_return - borrow_cost
            if active:
                equity *= 1.0 + net_return
                daily_returns.append(net_return)
            if active:
                benchmark_equity *= close[BENCHMARK][index] / previous_spy
            previous_spy = close[BENCHMARK][index]

        if date in month_end_set and index >= 252:
            signal = _signal_values(profile, close, index)
            ranked = sorted(signal, key=lambda symbol: signal[symbol])
            leg_size = 3 if profile.endswith("_v2") else 2
            if profile.startswith("low_volatility"):
                longs, shorts = ranked[:leg_size], ranked[-leg_size:]
            else:
                shorts, longs = ranked[:leg_size], ranked[-leg_size:]
            target = {symbol: 0.0 for symbol in DEFAULT_UNIVERSE}
            leg_weight = 0.40 if profile.endswith("_v2") else 0.50
            for symbol in longs:
                target[symbol] = leg_weight / leg_size
            for symbol in shorts:
                target[symbol] = -leg_weight / leg_size
            turnover = sum(abs(target[symbol] - weights[symbol]) for symbol in DEFAULT_UNIVERSE)
            rebalance_cost = turnover * 0.001
            if active:
                equity *= 1.0 - rebalance_cost
                daily_returns[-1] = (1.0 + daily_returns[-1]) * (1.0 - rebalance_cost) - 1.0
                total_cost += rebalance_cost
            for symbol in DEFAULT_UNIVERSE:
                old, new = weights[symbol], target[symbol]
                if old != new:
                    action = "退出" if new == 0 else "做多" if new > 0 else "做空"
                    trades.append(
                        {"date": date, "symbol": symbol, "action": action, "weight": new}
                    )
            weights = target
            active = True

        if active:
            equity_curve.append(
                {
                    "date": date,
                    "strategy": round((equity - 1.0) * 100, 3),
                    "benchmark": round((benchmark_equity - 1.0) * 100, 3),
                }
            )

    if not equity_curve:
        raise ValueError("可用行情长度不足，无法完成快速回测")

    candles = {
        symbol: [by_symbol[symbol][date] for date in common_dates[-180:]]
        for symbol in DEFAULT_UNIVERSE
    }
    metrics = _metrics(daily_returns, equity_curve, total_cost)
    strategy_name, method = _profile_description(profile)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "EXPLORATORY_ONLY",
        "profile": profile,
        "strategy_name": strategy_name,
        "method": method,
        "universe": DEFAULT_UNIVERSE,
        "benchmark": BENCHMARK,
        "period": {"start": equity_curve[0]["date"], "end": equity_curve[-1]["date"]},
        "metrics": metrics,
        "equity_curve": equity_curve,
        "candles": candles,
        "trades": trades,
        "current_positions": [
            {"symbol": symbol, "weight": weight}
            for symbol, weight in weights.items()
            if weight
        ],
        "limitations": [
            "固定使用当前仍活跃的10只大盘股，未严格消除幸存者偏差。",
            "这是对论文策略的简化近似，不包含历史真实借券费和有效价差。",
            "行情来自公开日线接口，适合快速筛选，不用于正式业绩声明。",
        ],
        "coverage": dict(adapter),
    }


async def _run_cross_asset_etf_backtest() -> dict[str, Any]:
    symbols = CROSS_ASSET_UNIVERSE
    async with httpx.AsyncClient(
        timeout=30.0,
        headers={"User-Agent": "Mozilla/5.0 QRI/0.1"},
    ) as client:
        results = await asyncio.gather(*(_fetch_daily(client, symbol) for symbol in symbols))
    market = dict(zip(symbols, results, strict=True))
    by_symbol = {
        symbol: {item["date"]: item for item in rows} for symbol, rows in market.items()
    }
    dates = [item["date"] for item in market[BENCHMARK]]
    common_dates = [
        day for day in dates if all(day in by_symbol[symbol] for symbol in symbols)
    ]
    close = {
        symbol: [float(by_symbol[symbol][day]["close"]) for day in common_dates]
        for symbol in symbols
    }
    weights = {symbol: 0.0 for symbol in symbols}
    equity = 1.0
    benchmark_equity = 1.0
    previous_spy = close[BENCHMARK][0]
    equity_curve: list[dict[str, Any]] = []
    daily_returns: list[float] = []
    trades: list[dict[str, Any]] = []
    total_cost = 0.0
    active = False

    for index, day in enumerate(common_dates):
        if index:
            gross_return = sum(
                weights[symbol] * (close[symbol][index] / close[symbol][index - 1] - 1.0)
                for symbol in symbols
            )
            borrow_cost = sum(abs(min(weight, 0.0)) for weight in weights.values()) * (
                0.02 / 252
            )
            net_return = gross_return - borrow_cost
            if active:
                equity *= 1.0 + net_return
                benchmark_equity *= close[BENCHMARK][index] / previous_spy
                daily_returns.append(net_return)
            previous_spy = close[BENCHMARK][index]

        if index >= 60 and (index - 60) % 5 == 0:
            recent_returns = {
                symbol: close[symbol][index] / close[symbol][index - 5] - 1.0
                for symbol in symbols
            }
            cross_mean = mean(recent_returns.values())
            residuals = {
                symbol: value - cross_mean for symbol, value in recent_returns.items()
            }
            ranked = sorted(residuals, key=lambda symbol: residuals[symbol])
            longs, shorts = ranked[:2], ranked[-2:]
            target = {symbol: 0.0 for symbol in symbols}
            for symbol in longs:
                target[symbol] = 0.25
            for symbol in shorts:
                target[symbol] = -0.25
            turnover = sum(abs(target[symbol] - weights[symbol]) for symbol in symbols)
            rebalance_cost = turnover * 0.001
            if active:
                equity *= 1.0 - rebalance_cost
                daily_returns[-1] = (1.0 + daily_returns[-1]) * (1.0 - rebalance_cost) - 1.0
                total_cost += rebalance_cost
            for symbol in symbols:
                if weights[symbol] != target[symbol]:
                    action = (
                        "退出" if target[symbol] == 0 else "做多" if target[symbol] > 0 else "做空"
                    )
                    trades.append(
                        {"date": day, "symbol": symbol, "action": action, "weight": target[symbol]}
                    )
            weights = target
            active = True

        if active:
            equity_curve.append(
                {
                    "date": day,
                    "strategy": round((equity - 1.0) * 100, 3),
                    "benchmark": round((benchmark_equity - 1.0) * 100, 3),
                }
            )

    if not equity_curve:
        raise ValueError("可用跨资产行情长度不足，无法完成代理回测")
    adapter = BACKTEST_ADAPTERS["cross_asset_etf"]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PROXY_ONLY",
        "profile": "cross_asset_etf",
        "strategy_name": "跨资产 ETF 五日残差反转代理",
        "method": (
            "每五个交易日比较九类流动 ETF 的近期收益偏离，做多负残差最大的两类、"
            "做空正残差最大的两类；它只检验反转方向，不等同于论文的稳健主成分模型。"
        ),
        "universe": symbols,
        "benchmark": BENCHMARK,
        "period": {"start": equity_curve[0]["date"], "end": equity_curve[-1]["date"]},
        "metrics": _metrics(daily_returns, equity_curve, total_cost),
        "equity_curve": equity_curve,
        "candles": {
            symbol: [by_symbol[symbol][day] for day in common_dates[-180:]]
            for symbol in symbols
        },
        "trades": trades,
        "current_positions": [
            {"symbol": symbol, "weight": weight}
            for symbol, weight in weights.items()
            if weight
        ],
        "limitations": [
            "ETF 是资产类别代理，不是论文使用的原始现货、期货、债券和衍生品数据。",
            "残差信号采用五日横截面偏离，不是论文要求的稳健主成分异常检测。",
            "统一成本不能替代期货换月、融资、跨市场时区和真实做空成本。",
            "代理结果只用于决定是否值得继续研究，不参与每日最优排名。",
        ],
        "coverage": dict(adapter),
    }


def _signal_values(
    profile: str, close: dict[str, list[float]], index: int
) -> dict[str, float]:
    if profile.startswith("low_volatility"):
        window = 90 if profile.endswith("_v2") else 60
        values = {}
        for symbol in DEFAULT_UNIVERSE:
            returns = [
                close[symbol][day] / close[symbol][day - 1] - 1.0
                for day in range(index - window + 1, index + 1)
            ]
            values[symbol] = pstdev(returns) * math.sqrt(252)
        return values
    if profile == "momentum_v2":
        return {
            symbol: close[symbol][index - 21] / close[symbol][index - 126] - 1.0
            for symbol in DEFAULT_UNIVERSE
        }
    return {
        symbol: close[symbol][index - 42] / close[symbol][index - 252] - 1.0
        for symbol in DEFAULT_UNIVERSE
    }


def _profile_description(profile: str) -> tuple[str, str]:
    if profile == "low_volatility_v2":
        return (
            "重构版 · 90日低波动率分散多空",
            "每月做多波动率最低3只、做空最高3只；总敞口降至80%，月末调仓，"
            "通过更长估计窗、更多持仓和较低杠杆减少偶然性与集中风险。",
        )
    if profile == "low_volatility":
        return (
            "60日低波动率 · 液体大盘股多空近似回测",
            "每月做多波动率最低2只、做空最高2只；多空各50%，月末调仓，"
            "单次换手成本10个基点，空头借券费按年化3%简化。",
        )
    if profile == "momentum_v2":
        return (
            "重构版 · 6至1个月分散动量多空",
            "每月做多动量最高3只、做空最低3只；总敞口降至80%，月末调仓，"
            "通过缩短信号窗口、增加持仓并降低杠杆控制回撤。",
        )
    return (
        "12至2个月动量 · 液体大盘股多空近似回测",
        "每月做多动量最高2只、做空最低2只；多空各50%，月末调仓，"
        "单次换手成本10个基点，空头借券费按年化3%简化。",
    )


async def _fetch_daily(client: httpx.AsyncClient, symbol: str) -> list[dict[str, Any]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    response = await client.get(
        url,
        params={"range": "5y", "interval": "1d", "events": "div,splits"},
    )
    response.raise_for_status()
    result = response.json()["chart"]["result"][0]
    quotes = result["indicators"]["quote"][0]
    rows = []
    for index, timestamp in enumerate(result["timestamp"]):
        values = {name: quotes[name][index] for name in ("open", "high", "low", "close")}
        if any(value is None for value in values.values()):
            continue
        rows.append(
            {
                "date": datetime.fromtimestamp(timestamp, UTC).date().isoformat(),
                **{name: round(float(value), 4) for name, value in values.items()},
                "volume": int(quotes["volume"][index] or 0),
            }
        )
    return rows


def _month_ends(dates: list[str]) -> list[str]:
    result: dict[str, str] = {}
    for date in dates:
        result[date[:7]] = date
    return list(result.values())


def _metrics(
    returns: list[float], equity_curve: list[dict[str, Any]], total_cost: float
) -> dict[str, float]:
    if not returns:
        raise ValueError("回测没有产生有效收益序列")
    years = len(returns) / 252
    final_equity = 1.0 + equity_curve[-1]["strategy"] / 100
    annual_return = final_equity ** (1 / years) - 1 if final_equity > 0 else -1.0
    volatility = pstdev(returns) * math.sqrt(252)
    sharpe = mean(returns) * 252 / volatility if volatility else 0.0
    peak = -math.inf
    max_drawdown = 0.0
    for point in equity_curve:
        value = 1.0 + point["strategy"] / 100
        peak = max(peak, value)
        max_drawdown = min(max_drawdown, value / peak - 1.0)
    return {
        "total_return": round((final_equity - 1.0) * 100, 2),
        "annual_return": round(annual_return * 100, 2),
        "annual_volatility": round(volatility * 100, 2),
        "sharpe": round(sharpe, 2),
        "max_drawdown": round(max_drawdown * 100, 2),
        "positive_day_ratio": round(sum(value > 0 for value in returns) / len(returns) * 100, 2),
        "estimated_cost": round(total_cost * 100, 2),
    }


def evaluate_quick_result(result: dict[str, Any]) -> dict[str, Any]:
    """Turn exploratory metrics into a transparent continue/rework/stop decision."""
    metrics = result["metrics"]
    coverage = result.get("coverage") or {}
    benchmark_return = float(result["equity_curve"][-1]["benchmark"])
    sharpe = float(metrics["sharpe"])
    drawdown = float(metrics["max_drawdown"])
    annual_return = float(metrics["annual_return"])
    total_return = float(metrics["total_return"])
    if coverage and not coverage.get("eligible_for_ranking", False):
        verdict, tone = "代理回测，仅供方向检查", "proxy"
        summary = "当前结果只覆盖部分策略规则，不用于淘汰策略，也不参与每日最优排名。"
    elif total_return <= 0 or sharpe < 0 or drawdown <= -45:
        verdict, tone = "淘汰", "fail"
        summary = "当前简化策略没有提供可接受的风险收益，不建议继续投入严格回测资源。"
    elif sharpe < 0.8 or drawdown < -25 or annual_return < 8:
        verdict, tone = "暂不通过，建议重构", "warning"
        summary = "策略有正收益，但风险调整后表现偏弱，应先修改信号或组合规则，再决定是否严格回测。"
    else:
        verdict, tone = "通过快速筛选", "pass"
        summary = "策略达到探索性门槛，可以进入更严格的点时数据和幸存者偏差检验。"
    evidence = [
        f"累计收益 {total_return:.2f}%，同期 SPY {benchmark_return:.2f}%",
        f"夏普比率 {sharpe:.2f}；快速筛选参考线为 0.80",
        f"最大回撤 {drawdown:.2f}%；快速筛选容忍线为 -25%",
        f"估算换手成本累计影响 {float(metrics['estimated_cost']):.2f}%",
    ]
    next_steps = (
        [
            "补齐适配器列出的缺失数据与原始信号算法。",
            "规则覆盖率达到100%后重新运行，代理结果不得直接升级为策略结论。",
            "使用点时股票池、退市数据和策略特定成本进行严格回测。",
        ]
        if tone == "proxy"
        else [
            "把固定10只股票扩展为更宽的流动性股票池，检查结果是否依赖少数个股。",
            "分别回测多头腿和空头腿，识别主要亏损来源。",
            "测试波动率缩放和更严格的单股、行业风险上限。",
            "重构后至少达到夏普0.80、最大回撤不低于-25%，再进入严格回测。",
        ]
    )
    return {
        "verdict": verdict,
        "tone": tone,
        "summary": summary,
        "evidence": evidence,
        "next_steps": next_steps,
    }
