基线：源码 4.3.0，2026-10-16。只覆盖这次未提交的合成窗跨屏改动。捕获窗原有的多屏拖拽仍以 [`PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md`](PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md) 为准，本次没有改 `pet/window_placement.py`。

## 背景

默认拓扑是一张透明合成窗，铺在一块屏幕上，宠物坐标是这张窗里的局部坐标。光标拖出当前屏幕后，鼠标事件停在窗边上，宠物被钳在当前屏边缘，到不了另一块屏。捕获模式（`PetWindow`）在 issue #186 里已经能跨屏，overlay 路径没有。

这次要补的是最基本的 overlay 跨屏，同时和已有的甩出、弹射拉动分开：

- 慢慢拖过边界：整张合成窗搬到光标所在的那块屏，宠物留在指针下。
- 快速拖动（拖动物理开着，末段速度达到每秒 500 像素）：视为甩出，窗不搬，松手后在当前屏飞、碰到边缘反弹。
- 右键弹射拉动：光标留在当前屏，不和跨屏拖动抢同一次移动。
- 跨屏那一帧不能先画在新屏的另一边再被弹簧拉回指针。弹簧只在这一帧清零，拖动继续后恢复。

## 变更内容

- 改了什么
  - `pet/overlay_shell.py`（+203）：启动时若调用方没有指定屏幕，按 slot0 档案里的 `screen_name` 选屏。拖动跨屏时不重建窗口、不结束抓取；先把被拖的宠物钉到新屏光标下并清掉弹簧速度，再把合成窗铺满目标屏。其它宠物按原比例跟着这张窗走。已经在飞，或拖动物理开着且末段速度达到甩出死区，则不搬窗。
  - `pet/overlay_window.py`（+55 / −9）：真拖拽的鼠标移动先问壳要不要跨屏，成功就不再用旧窗的局部坐标跟手。弹射瞄准期间把光标钳回当前屏，移动只更新拉拽，松左键前也先钳再发射。卡住检测在瞄准时同样只钳光标，不跨屏。
  - `pet/window.py`（+15）：捕获窗进入弹射拉动和更新瞄准时，把系统光标留在宠物当前所在的那块屏上。
- 新增了什么
  - `pet/window_screen_cross.py`：纯几何判定。屏幕矩形左闭右开，接缝算给起点在那边的屏；光标落在屏缝里时取更近的另一块屏。另有启动屏解析、局部坐标、甩出死区判定，以及把光标钳进当前屏的 `hold_cursor_on_screen`。
  - `tests/test_window_screen_cross.py`：几何判定、慢拖搬家、快拖留在当前屏、已飞出的弹射不搬窗、弹射瞄准不跨屏、跨屏后宠物当帧落在指针下且弹簧速度为 0。
  - `docs/cross_screen.md`：本说明。`docs/INDEX.md` 增加入口，并在 issue #186 那一行指向这里。
- 删除了什么
  - 没有删除文件，也没有删配置键。没有把合成窗扩成整块虚拟桌面。

## 实现方案

合成窗仍然一次只盖一块屏。跨屏不是把窗口拉成多屏那么大，而是在一次已经成立的左键拖动里，发现光标进入另一块屏后，把这张窗的几何换成那块屏的完整矩形，抓取保持不断。

判定分三层：

1. 窗口事件看手势。位移超过 `DRAG_THRESHOLD`（5 像素乘缩放）才是真拖拽。瞄准中（`slingshot.aiming`，即控制器里记着一只宠物）直接返回，不调用跨屏。
2. 壳看这下移动算不算甩出。`interaction_state == "thrown"`，或者 `drag_physics` 为真且 `estimate_release_velocity` 的速度不低于 `DEAD_ZONE_SPEED`（500 px/s），就留在当前屏。低于死区才搬家。拖动物理关着时没有甩出，快拖也搬家。
3. 搬家前用目标屏原点把光标换成局部坐标，`set_pos` 钉到指针下，弹簧速度和弹簧活动标记清零，先 `repaint` 再 `setScreen` / `setGeometry`。Windows 上几何对不齐时用 `SetWindowPos` 按屏幕矩形铺满。旧屏上的拖动轨迹丢掉，避免换原点之后被估成一次甩出。之后的 `on_move` 仍按 `drag_physics` 写弹簧目标，弹簧恢复跟手。

弹射拉动不搬窗。合成窗在瞄准的移动、轮询和松手发射前把光标钳到当前屏最后一个像素；捕获窗走同一个 `hold_cursor_on_screen`。

## 影响范围

- 模块：`pet/overlay_shell.py`、`pet/overlay_window.py`、`pet/window.py`、新增 `pet/window_screen_cross.py`。拖动弹簧、甩出初速、弹射瞄准的原有公式没有改。
- 页面：没有改设置页，没有新配置键。启动仍读已有的 slot0 `screen_name`。
- 行为：同一张合成窗上的其它宠物会按比例迁到新屏，因为一张窗盖不住两块屏。气泡跟随用原来的原点同步。捕获窗的普通拖拽/抛掷边界仍走 `pet/window_placement.py`，这次只加了弹射拉动时的光标钳制。
- 接口 / 数据库：无。位置仍写在 `%APPDATA%\dsh-pet-standalone\config-slot-N.json` 的 `rx` / `ry` / `screen_name`。

## 测试情况

- 本地测试：调试时确认过三件事。快速拖到另一块屏会甩出，不能当成搬家。慢慢拖才搬窗。跨屏后宠物会先出现在新屏另一边再被弹簧拉回指针；落点已改成先钉到指针再挪窗。
- 单元测试：`tests/test_window_screen_cross.py` 于 2026-10-16 在本机 `.venv`（Python 3.11，`QT_QPA_PLATFORM=offscreen`）跑过，**19 passed**。覆盖接缝/屏缝、慢拖搬家、快拖不搬、已飞出不搬、瞄准不跨屏、跨屏当帧落在指针下且弹簧速度为 0。复跑：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q tests/test_window_screen_cross.py
```

- 联调情况：未做捕获模式与 overlay 的对照联调，也未在多块真实显示器上把慢拖、快甩、右键弹射拉动各走一遍并记录结果。
- 截图/录屏（如有）：无。

## 风险评估

- 慢和快的分界是固定的 500 px/s。拖动物理开着时，略快的搬家会被当成甩出，窗不跟着走。
- 一张合成窗跨屏时，没被拖的宠物会整批换到新屏，不能一半留在旧屏。
- 跨屏那一帧弹簧速度被清掉。若 `repaint` 没有在窗口挪走前画完，仍可能闪一帧旧位置。
- 跨屏会丢掉越屏前的速度样本。松手若紧挨着跨屏，不会因为旧屏上的速度甩出；在新屏上重新拖快，仍然可以甩出。
- `SetWindowPos` 只在 Windows 上补几何。macOS / Linux 只靠 `setScreen` 和 `setGeometry`，未实机验证。
- 测试注入了假屏。假屏路径不读真实虚拟桌面，单屏测试不应突然铺满多屏；这条依赖「调用方传入了 screen 就不再解析启动屏」。

## 回滚方案

回退这次提交，并删掉随提交新增的文件（若提交里已经包含它们，`git revert` 会一并去掉）：

```powershell
git revert <本次提交>
```

若改动还在工作区、尚未提交：

```powershell
git checkout -- pet/overlay_shell.py pet/overlay_window.py pet/window.py docs/INDEX.md
Remove-Item pet/window_screen_cross.py, tests/test_window_screen_cross.py, docs/cross_screen.md
```

回退后 overlay 恢复为单屏合成窗，捕获窗的弹射拉动不再钳光标。`screen_name` 的读写本来就有，档案不用迁移。

## 关联链接

- Issue / Ticket / 设计稿 / 接口文档
  - 捕获窗跨屏的既有实现：[`PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md`](PR-REPORT-ISSUE-186-TRAY-MENU-2026-09-23.md)（issue #186，`pet/window_placement.py` 的 `DesktopArea`）
  - 本次代码：`pet/window_screen_cross.py`、`pet/overlay_shell.py` 的 `_on_cross_screen_drag`、`pet/overlay_window.py` 的 `_maybe_cross_screen`
  - 无单独设计稿，无新接口
