# -*- coding: utf-8 -*-
"""合成窗拖动跨屏：纯几何判定 + 壳把整窗搬到光标所在的另一块屏。"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF
from PySide6.QtWidgets import QApplication

from pet import physics as physics_mod
from pet.overlay_window import OverlayWindow
from pet.window_screen_cross import (
    clamp_point_inside,
    hold_cursor_on_screen,
    local_point,
    other_screen_at,
    resolve_startup_screen,
    screen_by_name,
    screen_index_at,
    short_flick_speed,
    throw_stays_on_screen,
)
from tests.test_overlay_screen_migration import FakeScreen, _make_shell, _teardown

app = QApplication.instance() or QApplication([])

PRIMARY = (0, 0, 1920, 1080)
SECONDARY = (1920, 0, 1920, 1080)


def test_cursor_on_current_screen_does_not_cross():
    assert screen_index_at(100, 100, [PRIMARY, SECONDARY], current=0) is None


def test_cursor_on_secondary_screen_crosses():
    assert screen_index_at(2000, 400, [PRIMARY, SECONDARY], current=0) == 1


def test_cursor_on_the_other_screen_crosses_even_beside_a_gap():
    above = (1920, -1080, 1920, 1080)
    assert screen_index_at(2000, -50, [PRIMARY, above], current=0) == 1


def test_gap_closer_to_the_other_screen_does_not_stick():
    right = (2000, 0, 1920, 1080)  # 与主屏之间空 80px
    assert screen_index_at(1970, 400, [PRIMARY, right], current=0) == 1
    assert screen_index_at(1930, 400, [PRIMARY, right], current=0) is None


def test_shared_edge_belongs_to_the_screen_that_starts_there():
    assert screen_index_at(1920, 10, [PRIMARY, SECONDARY], current=0) == 1


def test_local_point_subtracts_overlay_origin():
    assert local_point(2000, 400, 1920, 0) == (80.0, 400.0)


def test_screen_by_name_requires_a_unique_match():
    primary = FakeScreen(PRIMARY, PRIMARY, name="DISPLAY1")
    other = FakeScreen(SECONDARY, SECONDARY, name="DISPLAY2")
    twin = FakeScreen((0, 1080, 1920, 1080), (0, 1080, 1920, 1080), name="DISPLAY2")
    assert screen_by_name([primary, other], "DISPLAY2") is other
    assert screen_by_name([primary, other], "") is None
    assert screen_by_name([primary, other], "missing") is None
    assert screen_by_name([other, twin], "DISPLAY2") is None


def test_startup_uses_saved_screen_when_it_is_still_connected():
    primary = FakeScreen(PRIMARY, PRIMARY, name="DISPLAY1")
    other = FakeScreen(SECONDARY, SECONDARY, name="DISPLAY2")
    assert resolve_startup_screen(primary, [primary, other], "DISPLAY2") is other
    assert resolve_startup_screen(primary, [primary, other], "gone") is primary
    assert resolve_startup_screen(primary, [primary, other], "") is primary


def test_other_screen_at_ignores_the_screen_under_the_cursor_when_it_is_current():
    primary = FakeScreen(PRIMARY, PRIMARY, name="DISPLAY1")
    other = FakeScreen(SECONDARY, SECONDARY, name="DISPLAY2")
    assert other_screen_at(QPoint(100, 100), primary, [primary, other]) is None
    assert other_screen_at(QPoint(2000, 400), primary, [primary, other]) is other


def test_hold_cursor_on_screen_warps_only_when_outside():
    from PySide6.QtCore import QRect

    geo = QRect(0, 0, 1920, 1080)
    moved = []
    assert hold_cursor_on_screen(QPoint(10, 20), geo, cursor_setter=moved.append) == QPoint(10, 20)
    assert moved == []
    assert hold_cursor_on_screen(QPoint(2500, -4), geo, cursor_setter=moved.append) == QPoint(1919, 0)
    assert moved == [QPoint(1919, 0)]


def test_clamp_point_inside_stops_on_the_last_pixel():
    assert clamp_point_inside(10, 20, 0, 0, 1920, 1080) == (10.0, 20.0)
    assert clamp_point_inside(2500, -4, 0, 0, 1920, 1080) == (1919.0, 0.0)
    assert clamp_point_inside(-2000, 100, -1920, 0, 1920, 1080) == (-1920.0, 100.0)


def test_slingshot_pull_warps_cursor_back_onto_the_overlay_screen():
    screen = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    overlay = OverlayWindow(screen)
    moved = []
    overlay._cursor_pos_setter = moved.append
    try:
        assert overlay._clamp_cursor_to_screen(QPoint(10, 20)) == QPoint(10, 20)
        assert moved == []
        assert overlay._clamp_cursor_to_screen(QPoint(2500, 100)) == QPoint(1919, 100)
        assert moved == [QPoint(1919, 100)]
    finally:
        overlay.stop()


def test_throw_speed_stays_on_the_current_screen():
    assert throw_stays_on_screen(True, physics_mod.DEAD_ZONE_SPEED, physics_mod.DEAD_ZONE_SPEED)
    assert throw_stays_on_screen(True, physics_mod.DEAD_ZONE_SPEED - 1, physics_mod.DEAD_ZONE_SPEED) is False
    assert throw_stays_on_screen(False, 9000, physics_mod.DEAD_ZONE_SPEED) is False


def test_short_flick_ignores_the_hold_before_it():
    """停住后再在 20ms 内甩出：更早的停留不把这次快甩拉成慢拖。"""
    now = 10.0
    trail = [
        (now - 0.14, 100.0, 400.0),
        (now - 0.008, 100.0, 400.0),
        (now, 700.0, 400.0),
    ]
    speed = short_flick_speed(trail, now, physics_mod.RELEASE_WINDOW_SEC,
                              physics_mod.MIN_SPAN_SEC, 20.0)
    assert speed is not None and speed >= physics_mod.DEAD_ZONE_SPEED
    slow = [(now - 0.10, 400.0, 400.0), (now, 408.0, 400.0)]
    assert short_flick_speed(slow, now, physics_mod.RELEASE_WINDOW_SEC,
                             physics_mod.MIN_SPAN_SEC, 20.0) is None


def test_flick_after_a_hold_does_not_move_the_overlay(tmp_path):
    """停住后 20ms 内甩过边界：初速估算返回 0，合成窗仍然留在当前屏。"""
    primary = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    other = FakeScreen(SECONDARY, (1920, 0, 1920, 1040), name="DISPLAY2")
    shell = _make_shell(tmp_path, primary)
    try:
        sprite = shell.sprite
        sprite._dragging = True
        sprite.drag_physics = True
        sprite._drag_offset = QPointF(10, 20)
        now = sprite._clock()
        sprite._drag_trail = [
            (now - 0.14, 100.0, 400.0),
            (now - 0.008, 100.0, 400.0),
            (now, 700.0, 400.0),
        ]
        shell.overlay._mouse_grab = sprite
        shell.overlay._drag_committed = True

        assert shell._on_cross_screen_drag(QPoint(2500, 400), screens=[primary, other]) is False
        assert shell._screen is primary
        assert shell.overlay.geometry() == primary.geometry()
    finally:
        _teardown(shell)


def test_fast_drag_toward_another_screen_stays_and_counts_as_throw(tmp_path):
    """末段速度达到甩出死区：光标即使进了另一块屏，合成窗也不搬。"""
    primary = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    other = FakeScreen(SECONDARY, (1920, 0, 1920, 1040), name="DISPLAY2")
    shell = _make_shell(tmp_path, primary)
    try:
        sprite = shell.sprite
        sprite._dragging = True
        sprite.drag_physics = True
        sprite._drag_offset = QPointF(10, 20)
        now = sprite._clock()
        sprite._drag_trail = [(now - 0.04, 100.0, 400.0), (now, 700.0, 400.0)]
        shell.overlay._mouse_grab = sprite
        shell.overlay._drag_committed = True

        assert shell._on_cross_screen_drag(QPoint(2500, 400), screens=[primary, other]) is False
        assert shell._screen is primary
        assert shell.overlay.geometry() == primary.geometry()
    finally:
        _teardown(shell)


def test_slow_drag_onto_another_screen_moves_the_overlay(tmp_path):
    """低于甩出死区的慢拖才把合成窗搬到光标所在的另一块屏。"""
    primary = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    other = FakeScreen(SECONDARY, (1920, 0, 1920, 1040), name="DISPLAY2")
    shell = _make_shell(tmp_path, primary)
    try:
        sprite = shell.sprite
        sprite._dragging = True
        sprite.drag_physics = True
        sprite._drag_offset = QPointF(10, 20)
        sprite.set_pos(QPointF(1600, 200))
        sprite._drag_spring_vel = QPointF(900, 0)
        sprite._drag_spring_target = QPointF(1700, 200)
        now = sprite._clock()
        sprite._drag_trail = [(now - 0.10, 400.0, 400.0), (now, 408.0, 400.0)]
        shell.overlay._mouse_grab = sprite
        shell.overlay._drag_committed = True

        assert shell._on_cross_screen_drag(QPoint(2500, 500), screens=[primary, other]) is True
        assert shell._screen is other
        assert shell.overlay.geometry() == other.geometry()
        assert shell.overlay._mouse_grab is sprite
        # 光标局部 (580, 500)，偏移 (10, 20)。必须当帧就在指针下，不能从旧坐标弹簧拉过去。
        assert sprite.pos.x() == 570
        assert sprite.pos.y() == 480
        assert sprite._drag_spring_vel.isNull()
    finally:
        _teardown(shell)


def test_already_thrown_flight_does_not_move_the_overlay(tmp_path):
    """已经飞起来的弹射撞到屏幕边缘时，不把合成窗带去下一块屏。"""
    primary = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    other = FakeScreen(SECONDARY, (1920, 0, 1920, 1040), name="DISPLAY2")
    shell = _make_shell(tmp_path, primary)
    try:
        sprite = shell.sprite
        sprite._dragging = True
        sprite.drag_physics = True
        sprite.interaction_state = "thrown"
        shell.overlay._mouse_grab = sprite
        shell.overlay._drag_committed = True

        assert shell._on_cross_screen_drag(QPoint(2500, 400), screens=[primary, other]) is False
        assert shell._screen is primary
        assert shell.overlay.geometry() == primary.geometry()
    finally:
        _teardown(shell)


def test_slingshot_aim_blocks_cross_screen_drag(tmp_path):
    """弹射拉拽进行中，光标即使在另一块屏上也不搬合成窗。"""
    primary = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    other = FakeScreen(SECONDARY, (1920, 0, 1920, 1040), name="DISPLAY2")
    shell = _make_shell(tmp_path, primary)
    try:
        sprite = shell.sprite
        sprite._dragging = True
        sprite.drag_physics = False
        shell.overlay._mouse_grab = sprite
        shell.overlay._drag_committed = True
        shell.overlay.slingshot._sprite = sprite
        assert shell.overlay.slingshot.aiming is True

        assert shell._on_cross_screen_drag(QPoint(2500, 500), screens=[primary, other]) is False
        assert shell._screen is primary
        assert shell.overlay.geometry() == primary.geometry()
        assert overlay_cross_blocked(shell.overlay, QPoint(2500, 500)) is True
    finally:
        shell.overlay.slingshot._sprite = None
        _teardown(shell)


def overlay_cross_blocked(overlay, global_pos) -> bool:
    """瞄准中 ``_maybe_cross_screen`` 必须直接拒绝，不调用跨屏回调。"""
    calls = []
    overlay._cross_screen_drag = lambda pos: calls.append(QPoint(pos)) or True
    blocked = overlay._maybe_cross_screen(global_pos) is False and calls == []
    return blocked


def test_drag_without_slingshot_still_reaches_the_cross_callback():
    screen = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    overlay = OverlayWindow(screen)
    calls = []
    overlay._cursor_pos_setter = lambda pos: None
    overlay._drag_committed = True
    overlay._cross_screen_drag = lambda pos: calls.append(QPoint(pos)) or True
    try:
        assert overlay.slingshot.aiming is False
        assert overlay._maybe_cross_screen(QPoint(2500, 400)) is True
        assert calls == [QPoint(2500, 400)]
    finally:
        overlay.stop()


def test_drag_onto_another_screen_moves_overlay_and_keeps_the_grab(tmp_path):
    primary = FakeScreen(PRIMARY, (0, 0, 1920, 1040), name="DISPLAY1")
    other = FakeScreen(SECONDARY, (1920, 0, 1920, 1040), name="DISPLAY2")
    shell = _make_shell(tmp_path, primary)
    try:
        sprite = shell.sprite
        sprite._dragging = True
        sprite._drag_offset = QPointF(10, 20)
        shell.overlay._mouse_grab = sprite
        shell.overlay._drag_committed = True
        before = QPointF(sprite.pos)

        assert shell._on_cross_screen_drag(QPoint(100, 100), screens=[primary, other]) is False
        assert shell._screen is primary
        assert shell.overlay._mouse_grab is sprite

        assert shell._on_cross_screen_drag(QPoint(2500, 500), screens=[primary, other]) is True
        assert shell._screen is other
        assert shell.overlay.geometry() == other.geometry()
        assert shell.overlay._mouse_grab is sprite
        assert shell.overlay._drag_committed is True
        assert sprite.home_screen is other
        assert sprite.pos != before
        body = sprite.body_rect()
        bounds = shell._bounds
        assert bounds.contains(body.center())
        # 光标局部 = (2500-1920, 500) = (580, 500)；抓取偏移 (10, 20)
        assert sprite.pos.x() == 570
        assert sprite.pos.y() == 480
    finally:
        _teardown(shell)
