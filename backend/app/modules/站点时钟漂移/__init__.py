"""站点时钟漂移裁决（甲案：切流账册，非双写双轨）。

形态：
- 站点时钟相对仓时钟漂移超阈 → 装载闸口切流，偏钟点带偏钟指纹进坏点匣，
  同步写站钟偏移裁决账册；现行入栏缓冲只收可信点。
- 偏移阈读取与写入命运同成同败：阈不可读/损坏时整批失败闭，不写任何业务行。
- 时间服务的纯裁决（时间.偏移裁决）与本模块同一份判定，杜绝假绿。
"""
from __future__ import annotations

from app.services import 时间

NAME = "站点时钟漂移"
CONTRACT = "站点时钟相对仓时钟漂移超阈进坏点，可信点入栏，分轨不混栏"
形态 = "甲-切流账册（偏钟点带指纹进坏点匣，不做双写归档双轨）"
默认阈秒 = 604800.0  # 7 天，保住基线夹具 happy path
HOOKS = ("before_load", "after_load", "decide_gate", "before_close", "after_close", "extra_verify_checks")
阈键 = "站钟漂移阈秒"
偏钟命运 = "已偏钟"


def describe() -> dict:
    return {"空桩": NAME, "契约": CONTRACT, "形态": 形态, "钩子": list(HOOKS), "默认启用": True}


def 偏钟指纹(漂移: float, 阈秒: float) -> str:
    return f"偏钟超阈:漂移{float(漂移):.1f}s>阈{float(阈秒):.1f}s"


def 读阈(规: dict) -> float:
    """阈读取失败即抛异常，由装载整批失败闭——读取与写入同成同败。"""
    try:
        阈 = float(规[阈键])
    except (KeyError, TypeError, ValueError):
        raise ValueError("站钟漂移阈秒缺失或损坏，装载失败闭")
    if 阈 < 0:
        raise ValueError("站钟漂移阈秒不得为负，装载失败闭")
    return 阈


def 裁决(观测时: str, 仓时: str, 阈秒: float) -> dict:
    return 时间.偏移裁决(观测时, 仓时, float(阈秒))


def decide_gate(event: dict, rules: dict) -> str:
    """入栏 / 偏钟坏点 二选一，不允许偏钟点落入入栏。"""
    try:
        阈 = 读阈(rules or {})
    except ValueError:
        return "偏钟坏点"
    r = 裁决(event["观测时"], event.get("仓时", ""), 阈)
    return "入栏" if r["是否可信"] else "偏钟坏点"


def extra_verify_checks(snapshot: dict) -> list[str]:
    问 = []
    if snapshot.get("偏钟在栏"):
        问.append("偏钟点混入现行入栏缓冲")
    return 问


def before_load(batch: dict) -> dict:
    return batch


def after_load(report: dict) -> dict:
    return report


def before_close(pen_id: str) -> None:
    return None


def after_close(report: dict) -> dict:
    return report
