"""失败测乙：站点源对账不得把偏钟点错标成可信绿。

红条件：
- 只读裁决接口缺失、或把超阈点判成可信则红；
- 站点对账里含偏钟点的站点仍挂“可信”绿结论则红；
- 时间服务的纯裁决与装载服务落库的裁决不一致（假绿）则红。
"""
import asyncio

import pytest

from app.services import 装载, 目录, 时间
from app import seed
from app.main import app

固定仓时 = "2026-11-25T04:00:00Z"


@pytest.fixture()
def 混灌后(monkeypatch):
    monkeypatch.setattr(seed, "此刻", lambda: 固定仓时)
    目录.改栏规({"站钟漂移阈秒": "300"})
    装载.装一批({
        "批次编号": "乙-混灌",
        "报文": [
            {"报文编号": "B-trust-1", "站点键": "站-北岭", "指标键": "PM25", "读数": 18.0,
             "观测时": "2026-11-25T03:58:00Z"},   # 漂 120s，可信
            {"报文编号": "B-skew-1", "站点键": "站-河东", "指标键": "PM25", "读数": 26.0,
             "观测时": "2026-11-25T01:00:00Z"},   # 漂 10800s，超阈
            {"报文编号": "B-skew-2", "站点键": "站-河东", "指标键": "PM25", "读数": 27.0,
             "观测时": "2026-11-25T00:00:00Z"},   # 漂 14400s，超阈
        ],
    })


def test_时间服务纯裁决不假绿():
    裁决 = 时间.偏移裁决("2026-11-25T01:00:00Z", 固定仓时, 300.0)
    assert 裁决["是否可信"] is False
    assert 裁决["漂移秒"] == pytest.approx(10800.0)
    可信裁决 = 时间.偏移裁决("2026-11-25T03:59:00Z", 固定仓时, 300.0)
    assert 可信裁决["是否可信"] is True


def test_站点对账含偏钟点不得标可信绿(混灌后):
    对账 = {r["源键"]: r for r in 目录.站点对账()}
    assert 对账["站-河东"]["偏钟数"] == 2
    assert 对账["站-河东"]["可信数"] == 0
    assert 对账["站-河东"]["对账结论"] != "可信", "含偏钟点的站点错标可信绿"
    assert 对账["站-北岭"]["可信数"] == 1
    assert 对账["站-北岭"]["偏钟数"] == 0
    assert 对账["站-北岭"]["对账结论"] == "可信"

    源行 = {r["源键"]: r for r in 目录.站点列表()}
    assert 源行["站-河东"]["对账结论"] != "可信"
    assert 源行["站-北岭"]["对账结论"] == "可信"


def test_只读裁决接口与装载落库一致(混灌后):
    行 = {r["报文编号"]: r for r in 目录.偏移裁决列表()}
    assert 行["B-trust-1"]["是否可信"] in (1, True)
    assert 行["B-skew-1"]["是否可信"] in (0, False)
    assert 行["B-skew-2"]["是否可信"] in (0, False)
    assert "偏钟" in 行["B-skew-1"]["指纹"]

    async def 取(path):
        async with app.test_client() as c:
            r = await c.get(path)
            assert r.status_code == 200
            return await r.get_json()

    接口 = asyncio.run(取("/api/站钟偏移裁决"))
    接口行 = {r["报文编号"]: r for r in 接口}
    assert 接口行["B-skew-1"]["是否可信"] in (0, False)
    assert 接口行["B-trust-1"]["是否可信"] in (1, True)

    源接口 = asyncio.run(取("/api/站点源"))
    源 = {r["源键"]: r for r in 源接口}
    assert 源["站-河东"]["对账结论"] != "可信"
