"""列表与栏规。"""
from __future__ import annotations
from app.db import 连接
from app.services import 校验


def 栏规() -> dict:
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键,值 FROM 栏规").fetchall()}
    finally:
        conn.close()


def 改栏规(体: dict) -> dict:
    错 = 校验.校验栏规补丁(体 or {})
    if 错:
        return {"错误": 校验.摘要错误(错), "栏规": 栏规()}
    conn = 连接()
    try:
        for k, v in (体 or {}).items():
            conn.execute(
                "INSERT INTO 栏规(键,值) VALUES (?,?) ON CONFLICT(键) DO UPDATE SET 值=excluded.值",
                (str(k), str(v)),
            )
        conn.commit()
        return 栏规()
    finally:
        conn.close()


def 站点列表() -> list[dict]:
    conn = 连接()
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM 站点源 ORDER BY 源键").fetchall()]
        对账 = {r["源键"]: r for r in _站点对账(conn)}
        for r in rows:
            m = 对账.get(r["源键"])
            r["可信数"] = m["可信数"] if m else 0
            r["偏钟数"] = m["偏钟数"] if m else 0
            r["对账结论"] = m["对账结论"] if m else "无数据"
        return rows
    finally:
        conn.close()


def _站点对账(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT s.源键,
                  COALESCE(SUM(CASE WHEN v.是否可信=1 THEN 1 ELSE 0 END),0) AS 可信数,
                  COALESCE(SUM(CASE WHEN v.是否可信=0 THEN 1 ELSE 0 END),0) AS 偏钟数,
                  COUNT(v.报文编号) AS 裁决数
           FROM 站点源 s
           LEFT JOIN 站钟偏移裁决 v ON v.站点键 = s.源键
           GROUP BY s.源键 ORDER BY s.源键"""
    ).fetchall()
    out = []
    for r in rows:
        可, 偏, 总 = int(r["可信数"]), int(r["偏钟数"]), int(r["裁决数"])
        if 总 == 0:
            结论 = "无数据"
        elif 偏 > 0:
            结论 = "偏钟旁路"
        else:
            结论 = "可信"
        out.append({
            "源键": r["源键"], "可信数": 可, "偏钟数": 偏, "裁决数": 总, "对账结论": 结论,
        })
    return out


def 站点对账() -> list[dict]:
    conn = 连接()
    try:
        return _站点对账(conn)
    finally:
        conn.close()


def 偏移裁决列表(限制: int = 500) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 站钟偏移裁决 ORDER BY 编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 报文列表(限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 观测报文 ORDER BY 观测时 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 缓冲列表(命运: str | None = None) -> list[dict]:
    conn = 连接()
    try:
        if 命运:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM 入栏缓冲 WHERE 命运=? ORDER BY 观测时", (命运,)
                ).fetchall()
            ]
        return [dict(r) for r in conn.execute("SELECT * FROM 入栏缓冲 ORDER BY 观测时").fetchall()]
    finally:
        conn.close()


def 汇总列表(限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 站点汇总账 ORDER BY 物化时 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 坏点列表(限制: int = 200) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 坏点匣 ORDER BY 编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 贯验列表(限制: int = 50) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 栏贯验 ORDER BY 编号 DESC LIMIT ?", (限制,)
            ).fetchall()
        ]
    finally:
        conn.close()


def 概览() -> dict:
    conn = 连接()
    try:
        return {
            "观测报文": conn.execute("SELECT COUNT(*) AS c FROM 观测报文").fetchone()["c"],
            "在栏": conn.execute("SELECT COUNT(*) AS c FROM 入栏缓冲 WHERE 命运='在栏'").fetchone()["c"],
            "站点汇总": conn.execute("SELECT COUNT(*) AS c FROM 站点汇总账").fetchone()["c"],
            "坏点": conn.execute("SELECT COUNT(*) AS c FROM 坏点匣").fetchone()["c"],
            "栏规": 栏规(),
        }
    finally:
        conn.close()


def 装载批次列表(限制: int = 50) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT 编号,时刻,入流,入栏,坏点 FROM 装载批次 ORDER BY 时刻 DESC LIMIT ?",
                (限制,),
            ).fetchall()
        ]
    finally:
        conn.close()


def 结栏批次列表(限制: int = 50) -> list[dict]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT 编号,栏号,时刻,汇总数 FROM 结栏批次 ORDER BY 时刻 DESC LIMIT ?",
                (限制,),
            ).fetchall()
        ]
    finally:
        conn.close()


def 站点查(源键: str) -> dict | None:
    conn = 连接()
    try:
        r = conn.execute("SELECT * FROM 站点源 WHERE 源键=?", (源键,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()
