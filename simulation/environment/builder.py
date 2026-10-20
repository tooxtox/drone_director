"""城市环境构建器。

支持两种数据来源：
1. 显式建筑列表（声明式 JSON，便于讲解和复现）；
2. 确定性程序化生成：按“街区+街道”网格生成盒状建筑，
   并自动为起降点/备降点留出净空区——演示城市由此构建器真实产生，不硬编码。
"""

from __future__ import annotations

import random

from core.models import Building, CityConfig, Waypoint
from core.models.geometry import Polygon2D, Position2D
from simulation.environment.city import CityEnvironment

from simulation.environment.ground import BLOCK_PERIOD as _BLOCK_PERIOD, STREET_WIDTH as _STREET_WIDTH

# 街区生成默认参数（米）
_VERTIPORT_CLEARANCE = 70.0  # 起降点周边不放建筑的净空半径
_MAX_BUILDING_HEIGHT = 100.0  # 建筑限高，保证 120m 主走廊安全


def rectangle_polygon(cx: float, cy: float, w: float, h: float) -> Polygon2D:
    """以中心点构造轴对齐矩形多边形。"""
    return Polygon2D(
        points=[
            Position2D(x=cx - w / 2, y=cy - h / 2),
            Position2D(x=cx + w / 2, y=cy - h / 2),
            Position2D(x=cx + w / 2, y=cy + h / 2),
            Position2D(x=cx - w / 2, y=cy + h / 2),
        ]
    )


class CityBuilder:
    @staticmethod
    def generate_buildings(
        config: CityConfig,
        waypoints: list[Waypoint] | None = None,
    ) -> list[Building]:
        """按街区网格确定性生成建筑，并避开起降点净空区。"""
        rng = random.Random(config.building_seed)
        protected = [(w.position.x, w.position.y) for w in (waypoints or [])]
        block_size = _BLOCK_PERIOD - _STREET_WIDTH

        buildings: list[Building] = []
        seq = 0
        y = config.min_y + _STREET_WIDTH / 2
        row = 0
        while y + block_size <= config.max_y - _STREET_WIDTH / 2:
            x = config.min_x + _STREET_WIDTH / 2
            col = 0
            while x + block_size <= config.max_x - _STREET_WIDTH / 2:
                # 每个街区以 70% 概率开发，拆成 1~2 栋楼
                if rng.random() < 0.70:
                    buildings.extend(
                        CityBuilder._fill_block(
                            rng, x, y, block_size, protected, seq
                        )
                    )
                    seq += 2
                x += _BLOCK_PERIOD
                col += 1
            y += _BLOCK_PERIOD
            row += 1
        return buildings

    @staticmethod
    def _fill_block(
        rng: random.Random,
        x: float,
        y: float,
        block_size: float,
        protected: list[tuple[float, float]],
        seq_start: int,
    ) -> list[Building]:
        gap = 12.0
        use_two = rng.random() < 0.45
        plots: list[tuple[float, float, float, float]] = []
        if use_two:
            w = (block_size - gap) / 2
            plots.append((x, y, w, block_size))
            plots.append((x + w + gap, y, w, block_size))
        else:
            inset = rng.uniform(0, 20)
            plots.append((x + inset, y + inset, block_size - 2 * inset, block_size - 2 * inset))

        result: list[Building] = []
        for i, (px, py, pw, ph) in enumerate(plots):
            cx, cy = px + pw / 2, py + ph / 2
            if CityBuilder._is_protected(cx, cy, protected, pw / 2, ph / 2):
                continue
            # 高度：低层(30)、中层(60)、高层(100) 三档加权抽样
            height = rng.choices(
                population=[
                    rng.uniform(18, 40),
                    rng.uniform(40, 75),
                    rng.uniform(75, _MAX_BUILDING_HEIGHT),
                ],
                weights=[0.45, 0.4, 0.15],
                k=1,
            )[0]
            seq = seq_start + i
            result.append(
                Building(
                    id=f"BL{seq:03d}",
                    name=f"{height:.0f}米楼宇-{seq:03d}",
                    footprint=rectangle_polygon(cx, cy, pw, ph),
                    height=round(height, 1),
                )
            )
        return result

    @staticmethod
    def _is_protected(
        cx: float,
        cy: float,
        protected: list[tuple[float, float]],
        half_width: float,
        half_height: float,
    ) -> bool:
        """建筑包围盒是否侵入任一保护点的净空圆。"""
        for px, py in protected:
            nearest_x = min(max(px, cx - half_width), cx + half_width)
            nearest_y = min(max(py, cy - half_height), cy + half_height)
            dist = ((px - nearest_x) ** 2 + (py - nearest_y) ** 2) ** 0.5
            if dist <= _VERTIPORT_CLEARANCE:
                return True
        return False

    @staticmethod
    def build(
        config: CityConfig,
        buildings: list[Building] | None = None,
        waypoints: list[Waypoint] | None = None,
    ) -> CityEnvironment:
        if buildings is None and config.generate_buildings:
            buildings = CityBuilder.generate_buildings(config, waypoints)
        return CityEnvironment(config, buildings or [])
