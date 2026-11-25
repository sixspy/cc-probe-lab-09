"""偏钟混灌并发双请求脚本（探栏台收工核验用）。

两路混灌请求并发提交，争抢同一个偏钟报文编号：
- 互斥正确 → 一路把偏钟点切流进坏点匣，另一路幂等驳回；
- 缺互斥   → 偏钟点可能双成功甚至混入现行入栏缓冲（红）。

用法：
  python -I scripts/偏钟并发双请求.py            # 走服务层（不启 HTTP）
  python -I scripts/偏钟并发双请求.py --http     # 起 hypercorn 后走真实 HTTP 双请求
"""
from __future__ import annotations
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import seed  # noqa: E402
from app.services import 装载, 目录  # noqa: E402

仓时固定 = "2026-11-25T04:00:00Z"


def _路(路号: int) -> dict:
    return {
        "批次编号": f"脚本-路{路号}",
        "报文": [
            {"报文编号": f"S-trust-{路号}-1", "站点键": "站-北岭", "指标键": "PM25",
             "读数": 20.0, "观测时": "2026-11-25T03:59:00Z"},
            {"报文编号": f"S-trust-{路号}-2", "站点键": "站-北岭", "指标键": "PM25",
             "读数": 21.0, "观测时": "2026-11-25T04:01:00Z"},
            {"报文编号": "S-skew-race", "站点键": "站-河东", "指标键": "PM25",
             "读数": 99.0, "观测时": "2026-11-25T01:00:00Z"},
        ],
    }


def 服务层双请求() -> dict:
    seed.初始化库()
    目录.改栏规({"站钟漂移阈秒": "300"})
    seed.此刻 = lambda: 仓时固定  # type: ignore[attr-defined]
    with ThreadPoolExecutor(max_workers=2) as ex:
        报告 = list(ex.map(装载.装一批, [_路(1), _路(2)]))
    return _核验(报告)


def http双请求(基址: str) -> dict:
    import httpx
    from datetime import datetime, timedelta, timezone

    # 库与阈由服务端进程负责；客户端只发请求并读结论
    httpx.post(f"{基址}/api/栏规", json={"站钟漂移阈秒": "300"}, timeout=10).raise_for_status()
    # 可信点取服务端当前钟 ±1 分钟（天然在阈内）；偏钟点取远古时间，必然超阈
    钟 = datetime.now(timezone.utc)
    近1 = (钟 - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    近2 = (钟 + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    体 = [_路(1), _路(2)]
    for b in 体:
        b["报文"][0]["观测时"] = 近1
        b["报文"][1]["观测时"] = 近2
        b["报文"][2]["观测时"] = "2000-01-01T00:00:00Z"

    def 发(载荷: dict) -> dict:
        r = httpx.post(f"{基址}/api/观测报文/装载", json=载荷, timeout=30)
        r.raise_for_status()
        return r.json()

    with ThreadPoolExecutor(max_workers=2) as ex:
        报告 = list(ex.map(发, 体))
    return _核验_http(基址, 报告)


def _核验_http(基址: str, 报告: list[dict]) -> dict:
    import httpx

    在栏 = {r["报文编号"] for r in httpx.get(f"{基址}/api/入栏缓冲", timeout=10).json()}
    坏点 = [r for r in httpx.get(f"{基址}/api/坏点匣", timeout=10).json()
            if r["报文编号"] == "S-skew-race"]
    裁决 = [r for r in httpx.get(f"{基址}/api/站钟偏移裁决", timeout=10).json()
            if r["报文编号"] == "S-skew-race"]
    报文 = [r for r in httpx.get(f"{基址}/api/观测报文", timeout=10).json()
            if r["报文编号"] == "S-skew-race"]
    果 = {
        "两路报告": 报告,
        "偏钟进现行缓冲": "S-skew-race" in 在栏,
        "坏点匣行数": len(坏点),
        "裁决账册行数": len(裁决),
        "观测报文中行数": len(报文),
        "指纹": 坏点[0]["原因"] if 坏点 else "",
        "通过": (
            "S-skew-race" not in 在栏
            and len(坏点) == 1
            and len(裁决) == 1
            and len(报文) == 1
            and sum(r.get("偏钟", 0) for r in 报告) == 1
        ),
    }
    return 果


def _核验(报告: list[dict]) -> dict:
    在栏 = {r["报文编号"] for r in 目录.缓冲列表()}
    坏点 = [r for r in 目录.坏点列表() if r["报文编号"] == "S-skew-race"]
    裁决 = [r for r in 目录.偏移裁决列表() if r["报文编号"] == "S-skew-race"]
    报文 = [r for r in 目录.报文列表() if r["报文编号"] == "S-skew-race"]
    果 = {
        "两路报告": 报告,
        "偏钟进现行缓冲": "S-skew-race" in 在栏,
        "坏点匣行数": len(坏点),
        "裁决账册行数": len(裁决),
        "观测报文中行数": len(报文),
        "指纹": 坏点[0]["原因"] if 坏点 else "",
        "通过": (
            "S-skew-race" not in 在栏
            and len(坏点) == 1
            and len(裁决) == 1
            and len(报文) == 1
            and sum(r.get("偏钟", 0) for r in 报告) == 1
        ),
    }
    return 果


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true", help="起真实 HTTP 服务发双请求")
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    args = ap.parse_args()

    if args.http:
        import subprocess
        import time
        from urllib.parse import urlparse

        u = urlparse(args.base)
        绑定 = f"{u.hostname or '127.0.0.1'}:{u.port or 8100}"
        import os
        import tempfile

        临时库 = tempfile.mkdtemp(prefix="probe09-race-")
        env = dict(os.environ, 数据目录=临时库, 夹具目录=str(Path(__file__).resolve().parents[2] / "fixtures"))
        env_cmd = [sys.executable, "-m", "hypercorn", "app.main:app", "--bind", 绑定]
        日志 = open(Path(tempfile.gettempdir()) / "probe09-race-http.log", "w", encoding="utf-8")
        proc = subprocess.Popen(
            env_cmd, cwd=Path(__file__).resolve().parents[1], env=env,
            stdout=日志, stderr=subprocess.STDOUT,
        )
        try:
            import httpx

            for _ in range(40):
                try:
                    httpx.get(f"{args.base}/api/概览", timeout=2)
                    break
                except Exception:
                    time.sleep(0.25)
            果 = http双请求(args.base)
        finally:
            proc.terminate()
            proc.wait(timeout=10)
    else:
        果 = 服务层双请求()

    print(json.dumps(果, ensure_ascii=False, indent=2))
    return 0 if 果["通过"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
