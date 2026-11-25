"""报文装载 → 入栏或坏点。

站钟漂移裁决（甲-切流账册）：
- 单进程装载锁 + SQLite BEGIN IMMEDIATE，混灌并发下偏钟点不可能双成功；
- 偏移阈在事务内读取，阈损坏 → 整批回滚不写一行，读取与写入命运同成同败；
- 偏钟超阈点带偏钟指纹进坏点匣并写裁决账册，绝不进现行入栏缓冲。
"""
from __future__ import annotations
import json
import threading
import uuid
from app.db import 连接
from app import seed
from app.services import 校验, 目录, 时间
from app.modules import 站点时钟漂移 as 漂移闸

装载锁 = threading.Lock()


def _批次号(体: dict) -> str:
    前 = str(体.get("批次编号") or "探批").strip() or "探批"
    return f"{前}-{uuid.uuid4().hex[:8]}"


def 装一批(体: dict, 仓时覆盖: str | None = None) -> dict:
    批次 = _批次号(体 or {})
    报文 = (体 or {}).get("报文") or []
    报告 = {"批次编号": 批次, "入流": 0, "入栏": 0, "坏点": 0, "偏钟": 0, "驳回": 0, "明细": []}
    预检 = 校验.校验批次(体 or {})
    if 预检:
        报告["明细"].append({"命运": "批次预检", "说明": 校验.摘要错误(预检)})
    # 生产取真实仓钟；仓时覆盖仅供演示夹具与测试钉参考钟，不改变裁决逻辑
    仓时 = 仓时覆盖 or seed.此刻()
    conn = 连接()
    # 进程内互斥：两路混灌双请求串行化，杜绝缺互斥的双成功窗口
    with 装载锁:
        try:
            # 立即拿写锁：并发装载在事务层面排队，而不是各自先查后写
            conn.execute("BEGIN IMMEDIATE")
            规行 = conn.execute("SELECT 键,值 FROM 栏规").fetchall()
            规 = {r["键"]: r["值"] for r in 规行}
            # 阈读取失败即整批失败闭：不允许阈未知时默认放行（假绿）
            try:
                阈秒 = 漂移闸.读阈(规)
            except ValueError as e:
                conn.rollback()
                报告["明细"].append({"命运": "批次预检", "说明": str(e)})
                return 报告
            栏号 = 规.get("当前栏号", "B-demo")
            站集合 = {s["源键"] for s in conn.execute("SELECT 源键 FROM 站点源").fetchall()}
            for ev in 报文:
                行错 = 校验.校验报文(ev)
                if 行错:
                    报告["驳回"] += 1
                    报告["明细"].append({"命运": "驳回-校验", "说明": 校验.摘要错误(行错)})
                    continue
                try:
                    时间.解析时(ev["观测时"])
                except Exception:
                    报告["驳回"] += 1
                    报告["明细"].append({"命运": "驳回-观测时", "说明": ev.get("观测时")})
                    continue
                编号 = ev["报文编号"]
                if conn.execute("SELECT 1 FROM 观测报文 WHERE 报文编号=?", (编号,)).fetchone():
                    报告["驳回"] += 1
                    报告["明细"].append({"命运": "驳回-幂等", "说明": 编号})
                    continue
                if ev["站点键"] not in 站集合:
                    报告["驳回"] += 1
                    报告["明细"].append({"命运": "驳回-未知站点", "说明": ev["站点键"]})
                    continue
                读数 = float(ev["读数"])
                # 纯裁决与写库共用同一份判定，时间服务不假绿
                判 = 漂移闸.裁决(ev["观测时"], 仓时, 阈秒)
                conn.execute(
                    """INSERT INTO 观测报文(报文编号,站点键,指标键,读数,观测时,处理时,命运,批次编号)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (编号, ev["站点键"], ev["指标键"], 读数, ev["观测时"], 仓时, "已装载", 批次),
                )
                报告["入流"] += 1
                conn.execute(
                    """INSERT INTO 站钟偏移裁决
                       (报文编号,站点键,观测时,仓时时,漂移秒,阈值秒,是否可信,指纹,批次编号,裁决时)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (编号, ev["站点键"], ev["观测时"], 仓时, 判["漂移秒"], 判["阈值秒"],
                     1 if 判["是否可信"] else 0, 判["指纹"], 批次, 仓时),
                )
                if not 判["是否可信"]:
                    # 甲案切流：偏钟点带指纹进坏点匣，不入现行缓冲
                    conn.execute(
                        """INSERT INTO 坏点匣(报文编号,站点键,原因,读数,观测时,入匣时)
                           VALUES (?,?,?,?,?,?)""",
                        (编号, ev["站点键"], 判["指纹"], 读数, ev["观测时"], 仓时),
                    )
                    conn.execute(
                        "UPDATE 观测报文 SET 命运=? WHERE 报文编号=?",
                        (漂移闸.偏钟命运, 编号),
                    )
                    报告["坏点"] += 1
                    报告["偏钟"] += 1
                    报告["明细"].append({
                        "命运": "偏钟坏点",
                        "报文编号": 编号,
                        "原因": 判["指纹"],
                        "漂移秒": 判["漂移秒"],
                        "阈值秒": 判["阈值秒"],
                    })
                    continue
                ok, 原因 = 校验.过门槛(读数, 规, ev["指标键"])
                if ok:
                    conn.execute(
                        """INSERT INTO 入栏缓冲(报文编号,站点键,指标键,读数,观测时,栏号,命运,入栏时)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (编号, ev["站点键"], ev["指标键"], 读数, ev["观测时"], 栏号, "在栏", 仓时),
                    )
                    conn.execute("UPDATE 观测报文 SET 命运=? WHERE 报文编号=?", ("已入栏", 编号))
                    报告["入栏"] += 1
                    报告["明细"].append({
                        "命运": "入栏",
                        "报文编号": 编号,
                        "栏号": 栏号,
                        "漂移秒": 判["漂移秒"],
                        "受控": 校验.指标是否受控(ev["指标键"]),
                    })
                else:
                    conn.execute(
                        """INSERT INTO 坏点匣(报文编号,站点键,原因,读数,观测时,入匣时)
                           VALUES (?,?,?,?,?,?)""",
                        (编号, ev["站点键"], 原因, 读数, ev["观测时"], 仓时),
                    )
                    conn.execute("UPDATE 观测报文 SET 命运=? WHERE 报文编号=?", ("已坏点", 编号))
                    报告["坏点"] += 1
                    报告["明细"].append({"命运": "坏点", "报文编号": 编号, "原因": 原因})
            conn.execute(
                """INSERT INTO 装载批次(编号,时刻,入流,入栏,坏点,报告) VALUES (?,?,?,?,?,?)""",
                (批次, 仓时, 报告["入流"], 报告["入栏"], 报告["坏点"],
                 json.dumps(报告, ensure_ascii=False)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return 报告
