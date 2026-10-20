"""城市三维环境：建筑集合、占用栅格与三维碰撞查询。"""

from __future__ import annotations

import math

from core.coords import GeoOrigin
from core.models import Building, CityConfig, Position3D
from core.models.geometry import Position2D
from simulation.environment.grid import OccupancyGrid2D
from simulation.environment.ground import ground_layout


class CityEnvironment:
    def __init__(self, config: CityConfig, buildings: list[Building]) -> None:
        self.config = config
        self.buildings: list[Building] = list(buildings)

        self.grid = OccupancyGrid2D(
            config.min_x,
            config.min_y,
            config.max_x,
            config.max_y,
            config.grid_resolution,
        )
        for building in self.buildings:
            self.grid.rasterize_polygon(building.footprint)

        self.origin = GeoOrigin(
            config.origin.latitude,
            config.origin.longitude,
            config.origin.altitude,
        )

    # ---------- 基础查询 ----------

    @property
    def building_count(self) -> int:
        return len(self.buildings)

    def max_building_height(self) -> float:
        return max((b.height + b.elevation for b in self.buildings), default=0.0)

    def in_bounds(self, x: float, y: float, margin: float = 0.0) -> bool:
        """边界以内，正 margin 为向内保留的水平净空。"""
        if not math.isfinite(margin) or margin < 0:
            raise ValueError("边界净空必须是非负有限数")
        return (
            self.config.min_x + margin <= x <= self.config.max_x - margin
            and self.config.min_y + margin <= y <= self.config.max_y - margin
        )

    def building_at_xy(self, x: float, y: float) -> Building | None:
        """返回水平投影包含该点的建筑（取顶部最高者）。"""
        point = Position2D(x=x, y=y)
        hits = [
            b
            for b in self.buildings
            if b.footprint.contains(point)
        ]
        if not hits:
            return None
        return max(hits, key=lambda b: b.height + b.elevation)

    # ---------- 三维碰撞 ----------

    def is_position_safe(
        self,
        position: Position3D,
        horizontal_clearance: float = 0.0,
        vertical_clearance: float = 5.0,
    ) -> bool:
        """位置是否满足城市边界、地面与建筑净空约束。接触边界体算碰撞。"""
        return self.is_segment_clear(position, position, vertical_clearance,
                                     horizontal_clearance=horizontal_clearance)

    def is_segment_clear(
        self,
        start: Position3D,
        end: Position3D,
        vertical_clearance: float = 5.0,
        *,
        horizontal_clearance: float = 0.0,
    ) -> bool:
        """精确检查线性航段；建筑从局部地面 z=0 挤出至 elevation+height。

        城市水平边界为凸矩形，端点在界内可保证整段在界内；建筑检测
        不依赖栅格分辨率。垂直净空作用于楼顶，水平净空采用真实米制距离。
        """
        if not math.isfinite(vertical_clearance) or vertical_clearance < 0:
            raise ValueError("垂直净空必须是非负有限数")
        for position in (start, end):
            if position.z < 0 or not self.in_bounds(position.x, position.y, horizontal_clearance):
                return False
        for building in self.buildings:
            top = building.elevation + building.height + vertical_clearance
            if building.footprint.intersects_prism(start, end, 0.0, top, horizontal_clearance):
                return False
        return True

    # ---------- 坐标转换 ----------

    def to_geo(self, position: Position3D) -> tuple[float, float, float]:
        return self.origin.enu_to_geo(position)

    # ---------- 序列化 ----------

    def summary(self) -> dict:
        return {
            "name": self.config.name,
            "origin": self.config.origin.model_dump(),
            "bounds": {
                "min_x": self.config.min_x,
                "min_y": self.config.min_y,
                "max_x": self.config.max_x,
                "max_y": self.config.max_y,
                "width": self.config.width,
                "height": self.config.height,
            },
            "building_count": self.building_count,
            "max_building_height": round(self.max_building_height(), 2),
            "grid": self.grid.stats(),
            "ground_layout": ground_layout(),
        }
