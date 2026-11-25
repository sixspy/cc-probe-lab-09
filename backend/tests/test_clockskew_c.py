"""争用失败测：两路混灌并发双请求，超阈点不得进现行入栏缓冲。

红条件：
- 缺互斥导致同一偏钟点双成功（观测报文/裁决/坏点匣出现两行）则红；
- 偏钟点在任何一路请求里落进入栏缓冲则红。
"""
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services import 装载, 目录
from app import seed

固定仓时 = "2026-11-25T04:00:00Z"


@pytest.fixture()
def 紧阈(monkeypatch):
    monkeypatch.setattr(seed, "此刻", lambda: 固定仓时)
    目录.改栏规({"站钟漂移阈秒": "300"})


def _路(路号: int) -> dict:
    return {
        "批次编号": f"丙-路{路号}",
        "报文": [
            {"报文编号": f"C-trust-{路号}-1", "站点键": "站-北岭", "指标键": "PM25",
             "读数": 20.0, "观测时": "2026-11-25T03:59:00Z"},
            {"报文编号": f"C-trust-{路号}-2", "站点键": "站-北岭", "指标键": "PM25",
             "读数": 21.0, "观测时": "2026-11-25T04:01:00Z"},
            # 两路争抢同一个偏钟报文编号
            {"报文编号": "C-skew-race", "站点键": "站-河东", "指标键": "PM25",
             "读数": 99.0, "观测时": "2026-11-25T01:00:00Z"},
        ],
    }


def test_并发双请求超阈点不进现行且不双成功(紧阈):
    前 = len(目录.缓冲列表())

    with ThreadPoolExecutor(max_workers=2) as ex:
        报告s = list(ex.map(装载.装一批, [_路(1), _路(2)]))

    # 一路成功入偏钟，另一路须幂等驳回，不得双成功
    assert sum(r["偏钟"] for r in 报告s) == 1
    assert sum(r["驳回"] for r in 报告s) == 1

    在栏 = {r["报文编号"] for r in 目录.缓冲列表()}
    assert "C-skew-race" not in 在栏, "并发下偏钟点混入现行入栏缓冲"
    assert len(目录.缓冲列表()) - 前 == 4

    报文 = [r for r in 目录.报文列表() if r["报文编号"] == "C-skew-race"]
    assert len(报文) == 1, "缺互斥导致偏钟点双写入流"
    assert 报文[0]["命运"] == "已偏钟"

    裁决 = [r for r in 目录.偏移裁决列表() if r["报文编号"] == "C-skew-race"]
    assert len(裁决) == 1, "裁决账册不得双写"
    assert 裁决[0]["是否可信"] in (0, False)

    坏点 = [r for r in 目录.坏点列表() if r["报文编号"] == "C-skew-race"]
    assert len(坏点) == 1, "坏点匣不得双写"
    assert 坏点[0]["原因"] == 裁决[0]["指纹"]
