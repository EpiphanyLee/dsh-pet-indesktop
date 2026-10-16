# -*- coding: utf-8 -*-
"""合成窗拖动跨屏：光标离开当前屏、进入另一块屏时，决定要不要把整窗搬过去。

合成窗一次只铺一块屏，精灵坐标是这块屏里的局部坐标。光标进了另一块屏之后，
鼠标事件的局部坐标会落到窗外，``set_pos`` 再把宠物钳回当前屏边缘。本模块只回答
「光标现在落在哪一块别的屏上」和「启动时该铺哪一块屏」；搬窗、改边界、把被拖的
那只放到光标下，由 ``OverlayShell`` 做。

坐标都是全局逻辑像素。屏矩形用左闭右开：相邻两屏的接缝算给右边（或下边）那块。
光标已经离开当前屏、又落在屏缝里时，取更近的那一块，避免停在接缝上。
"""

from __future__ import annotations

from pathlib import Path


def rect_contains(x: float, y: float, rx: float, ry: float, rw: float, rh: float) -> bool:
    """点是否落在矩形内（左闭右开、上闭下开）。宽或高非正 = 无效屏。"""
    return rw > 0 and rh > 0 and rx <= x < rx + rw and ry <= y < ry + rh


def _distance_sq(x: float, y: float, rx: float, ry: float, rw: float, rh: float) -> float:
    """点到矩形的距离平方。落在矩形内（左闭右开）为 0。"""
    if rect_contains(x, y, rx, ry, rw, rh):
        return 0.0
    if rw <= 0 or rh <= 0:
        return float("inf")
    nearest_x = min(max(x, rx), rx + rw)
    nearest_y = min(max(y, ry), ry + rh)
    dx = x - nearest_x
    dy = y - nearest_y
    return dx * dx + dy * dy


def screen_index_at(x: float, y: float, geometries, current: int | None = None) -> int | None:
    """光标该落到的**另一块**屏下标；仍在当前屏上则返回 None。

    ``geometries`` 每项是 ``(x, y, w, h)``。当前屏优先：点还在当前屏里就不跨。
    已经离开当前屏时，先取含这个点的那一块；屏缝里哪块都不含，就取更近的那一块，
    避免光标卡在接缝上、合成窗停在旧屏边缘。距离打平时偏向离开当前屏。
    """
    count = len(geometries)

    def contains(index: int) -> bool:
        rx, ry, rw, rh = geometries[index]
        return rect_contains(x, y, rx, ry, rw, rh)

    if current is not None and 0 <= current < count and contains(current):
        return None
    for index in range(count):
        if index == current:
            continue
        if contains(index):
            return index
    best = None
    best_distance = float("inf")
    current_distance = float("inf")
    for index in range(count):
        distance = _distance_sq(x, y, *geometries[index])
        if index == current:
            current_distance = distance
            continue
        if distance < best_distance:
            best = index
            best_distance = distance
    if best is None or best_distance > current_distance:
        return None
    return best


def clamp_point_inside(x: float, y: float, rx: float, ry: float,
                       rw: float, rh: float) -> tuple[float, float]:
    """把点钳进矩形内部。右/下边是下一块屏的起点，最多停在最后一像素。"""
    if rw <= 0 or rh <= 0:
        return float(x), float(y)
    return (
        min(max(float(x), float(rx)), float(rx) + float(rw) - 1),
        min(max(float(y), float(ry)), float(ry) + float(rh) - 1),
    )


def hold_cursor_on_screen(global_pos, geometry, cursor_setter=None):
    """把系统光标留在 ``geometry`` 这块屏内。已在屏内则原样返回，不移动鼠标。

    捕获窗的弹射拉动走这里：光标出了当前屏就把鼠标拉回来，瞄准坐标用拉回后的点。
    ``cursor_setter`` 缺省是 ``QCursor.setPos``，测试可换成记录调用的函数。
    """
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QCursor

    x, y = clamp_point_inside(
        float(global_pos.x()), float(global_pos.y()),
        float(geometry.x()), float(geometry.y()),
        float(geometry.width()), float(geometry.height()))
    clamped = QPoint(int(round(x)), int(round(y)))
    current = QPoint(int(global_pos.x()), int(global_pos.y()))
    if clamped != current:
        setter = cursor_setter or QCursor.setPos
        setter(clamped)
    return clamped


def throw_stays_on_screen(drag_physics: bool, speed: float, dead_zone: float) -> bool:
    """拖动物理开、末段速度达到甩出死区 = 甩出，停在当前屏，不因光标越界搬窗。

    低于死区是慢慢把宠物拖到另一块屏上，仍然跨屏。甩出飞到边缘由当前屏的边界反弹。
    """
    return bool(drag_physics) and float(speed) >= float(dead_zone)


def local_point(global_x: float, global_y: float,
                origin_x: float, origin_y: float) -> tuple[float, float]:
    """全局坐标换成以 ``(origin_x, origin_y)`` 为原点的局部坐标。"""
    return float(global_x) - float(origin_x), float(global_y) - float(origin_y)


def same_screen(left, right) -> bool:
    """两块屏是不是同一块（同一对象，或名字加全屏几何都相同）。"""
    if left is right:
        return True
    if left is None or right is None:
        return False
    try:
        return (str(left.name()) == str(right.name())
                and left.geometry() == right.geometry())
    except Exception:
        return False


def other_screen_at(global_pos, current, screens):
    """``screens`` 里、光标所在的另一块屏；没有则 None。

    几何读失败的屏跳过。``current`` 不在列表里时，按名字加几何再认一次，
    避免 Qt 给同一块屏换了 Python 包装就被当成「跨到自己」。
    """
    geometries = []
    usable = []
    for screen in screens:
        try:
            geo = screen.geometry()
            geometries.append((geo.x(), geo.y(), geo.width(), geo.height()))
        except Exception:
            continue
        usable.append(screen)
    current_index = None
    for index, screen in enumerate(usable):
        if same_screen(screen, current):
            current_index = index
            break
    index = screen_index_at(global_pos.x(), global_pos.y(), geometries,
                            current=current_index)
    if index is None:
        return None
    target = usable[index]
    if same_screen(target, current):
        return None
    return target


def screen_by_name(screens, name: str):
    """按 ``QScreen.name()`` 找唯一一块屏。空名、没有、重名都返回 None。"""
    text = str(name or "").strip()
    if not text:
        return None
    found = []
    for screen in screens:
        try:
            label = str(screen.name())
        except Exception:
            continue
        if label == text:
            found.append(screen)
    if len(found) == 1:
        return found[0]
    return None


def resolve_startup_screen(primary, screens, saved_name: str):
    """启动时铺哪一块屏：档案里的 ``screen_name`` 还在就用它，否则用主屏。"""
    picked = screen_by_name(screens, saved_name)
    if picked is None:
        return primary
    return picked


def saved_screen_name(config_dir) -> str:
    """slot0 档案里记下的屏名。没有目录、没有档案、没有合法名字 = 空串。"""
    if not config_dir:
        return ""
    try:
        from . import pet_profiles

        profile = pet_profiles.read_slot_profile(Path(config_dir), 0)
    except Exception:
        return ""
    raw = (getattr(profile, "data", None) or {}).get("screen_name")
    if not isinstance(raw, str):
        return ""
    return raw.strip()
