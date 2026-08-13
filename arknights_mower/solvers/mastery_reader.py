"""共享训练室状态读取器（#63）。

训练室**一次进房读全部状态**，在自然触发点（SKILL_UPGRADE dispatch、排班房间
循环、仓库扫描）顺路调用，并按 #61 恢复矩阵执行对账动作。

铁律：
- training 状态永远先读房（主页面面板干员名），`expires_at` 只是调度提示；
- DB 与截图冲突**以截图为准**；
- 一次进房做完全部动作（读+动作不拆两次）；短动作（核实/帮收/重置/对账）可排班路径
  内联，长动作（开始训练）返回给调用方（SKILL_UPGRADE dispatch）执行。

读取能力（坐标已钉，见 #61）：
- 主页面面板（主读取器）：`[干员名]技能名`、倒计时、专精图标（亮 N 颗 = 在专N/专N完成）；
- 技能选择页 lit_zones 按 DB skill_index 直接读对应槽（已到target检测）；
- 收集页只截图不读文本。
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from arknights_mower.utils import config
from arknights_mower.utils.log import logger
from arknights_mower.utils.scene import Scene
from arknights_mower.utils.scheduler_task import SchedulerTask, TaskTypes
from arknights_mower.utils.skill_label import format_skill_label, panel_skill_matches

# 主页面面板坐标（#61 已钉）
PANEL_REGION = ((239, 878), (776, 977))  # `[干员名]技能名`
COUNTDOWN_REGION = ((236, 978), (380, 1020))  # 训练位倒计时
MASTERY_ICON_REGION = ((337, 833), (373, 866))  # 专精图标（亮N颗=在专N/专N完成）

ARRANGING_RETRY_BUFFER = timedelta(minutes=2)

# 像素验证阈值（#63 待实现细节，实机校准待办）
MASTERY_ICON_BRIGHTNESS = 150  # 专精图标"亮"的像素亮度下限
MASTERY_ICON_LIT_RATIO = 0.30  # 一个图标槽内亮像素占比达到此值计为点亮

# 技能选择页目标技能槽的专精星级显示区（已到target检测）。
# 实机像素验证后填入 1080p 坐标，例如 ((430, 360), (560, 395))；未填入时检测停用。
SKILL_SLOT_PIP_REGION = None


@dataclass
class RoomPanel:
    """主页面面板读取结果（全部信息源）。"""

    operator_name: str = ""
    skill_name: str = ""
    mastery_tier: int = 0  # 专精图标亮灯计数 0-3
    countdown: Optional[datetime] = None  # 训练位倒计时结束时刻


@dataclass
class RoomState:
    """训练室房间状态（截图权威）。"""

    state: str = "empty"  # "training" | "waiting_collect" | "empty"
    panel: RoomPanel = field(default_factory=RoomPanel)

    @property
    def locked(self) -> bool:
        """训练位是否锁定（gate 用）：🔴 训练中 / 🟡 待收取 都算锁定。"""
        return self.state in ("training", "waiting_collect")


# --- 纯函数：技能名/面板解析/像素计数/状态分类 ---


def _parse_panel_text(text):
    """`[干员名]技能名` → (干员名, 技能名)。无方括号视为纯技能名。"""
    if not text:
        return "", ""
    t = str(text).strip()
    if t.startswith("[") and "]" in t:
        name, _, rest = t[1:].partition("]")
        return name.strip(), rest.strip()
    return "", t


def _count_lit_from_region(region, brightness=None, lit_ratio=None):
    """专精图标亮灯计数：region 为 (h,w[,3]) 的图标区，按宽度分 3 槽。

    每槽亮像素占比 ≥ lit_ratio 计 1 颗。返回 0-3。阈值待实机像素验证。
    """
    import numpy as np

    if region is None or region.size == 0:
        return 0
    brightness = brightness if brightness is not None else MASTERY_ICON_BRIGHTNESS
    lit_ratio = lit_ratio if lit_ratio is not None else MASTERY_ICON_LIT_RATIO
    if region.ndim == 3:
        gray = np.mean(region.astype(np.float32), axis=2)
    else:
        gray = region.astype(np.float32)
    h, w = gray.shape
    slot_w = max(1, w // 3)
    count = 0
    for i in range(3):
        seg = gray[:, i * slot_w : (i + 1) * slot_w]
        if seg.size == 0:
            continue
        lit = float((seg > brightness).mean())
        if lit >= lit_ratio:
            count += 1
    return count


def classify_room_state(scene, countdown) -> str:
    """纯函数：场景 + 倒计时结束时刻 → 房间状态。

    - TRAIN_FINISH → 🟡 waiting_collect
    - TRAIN_MAIN：有效倒计时 → 🔴 training；否则 ⚪ empty
      （"刚完成"的 TRAIN_MAIN 由读取器额外查 training_completed 模板区分）
    - 其他房内场景保守视为占用（🔴）。
    """
    if scene == Scene.TRAIN_FINISH:
        return "waiting_collect"
    if scene == Scene.TRAIN_MAIN:
        if countdown is not None and countdown > datetime.now():
            return "training"
        return "empty"
    return "training"


# --- 读取原语 ---


def _read_train_countdown(solver) -> Optional[datetime]:
    """读训练位倒计时，返回结束时刻；读不到返回 now（等于没读）。"""
    return solver.double_read_time(COUNTDOWN_REGION)


def _count_lit_mastery_icons(solver, img=None) -> int:
    if img is None:
        img = getattr(getattr(solver, "recog", None), "img", None)
    if img is None:
        return 0
    (x0, y0), (x1, y1) = MASTERY_ICON_REGION
    return _count_lit_from_region(img[y0:y1, x0:x1])


def _read_slot_mastery_tier(solver, skill_index):
    """读技能选择页目标技能槽的专精档位（亮灯计数），用于已到target检测。

    SKILL_SLOT_PIP_REGION 为第 1 技能槽（index 0）的星级显示区，按槽位行距
    0.3h 下移。未校准（None）/读不到 → 返回 None，调用方走正常开始（安全）。
    """
    if SKILL_SLOT_PIP_REGION is None:
        return None
    img = getattr(getattr(solver, "recog", None), "img", None)
    if img is None:
        return None
    (x0, y0), (x1, y1) = SKILL_SLOT_PIP_REGION
    dy = int(solver.recog.h * 0.3) * skill_index
    return _count_lit_from_region(img[y0 + dy : y1 + dy, x0:x1])


def read_main_panel(solver, img=None) -> RoomPanel:
    """读主页面面板：干员名/技能名/专精图标档位/倒计时。"""
    if img is None:
        solver.recog.update()
        img = solver.recog.img
    try:
        text = solver.read_screen(img, type="text", cord=PANEL_REGION)
    except Exception as e:
        logger.debug(f"面板 OCR 失败: {e}")
        text = ""
    operator_name, skill_name = _parse_panel_text(text)
    tier = _count_lit_mastery_icons(solver, img)
    countdown = _read_train_countdown(solver)
    return RoomPanel(
        operator_name=operator_name,
        skill_name=skill_name,
        mastery_tier=tier,
        countdown=countdown,
    )


def _settle_in_room(solver, max_iters=15) -> int:
    """把场景稳定到房内可判定状态（TRAIN_MAIN / TRAIN_FINISH / 其他房内场景）。

    瞬态场景（未连接/未知/基建首页/详情浮层）循环收敛；稳定房内场景立即返回。
    """
    transient = (
        Scene.INFRA_MAIN,
        Scene.INFRA_DETAILS,
        Scene.CONNECTING,
        Scene.UNKNOWN,
    )
    for _ in range(max_iters):
        scene = solver.train_scene()
        if scene not in transient:
            return scene
        if scene == Scene.INFRA_MAIN:
            solver.enter_room("train")
        elif scene == Scene.INFRA_DETAILS:
            solver.back()
        else:
            solver.sleep()
    return solver.train_scene()


def read_room_state(solver, enter=True) -> RoomState:
    """进房读全部状态。enter=False 表示已在房内（排班 gate 用）。

    房间停留在 TRAIN_MAIN / TRAIN_FINISH；返回 RoomState（截图权威）。
    """
    if enter:
        solver.enter_room("train")
    scene = _settle_in_room(solver)
    if scene == Scene.TRAIN_FINISH:
        return RoomState("waiting_collect", _safe_read_panel(solver))
    if scene == Scene.TRAIN_MAIN:
        panel = read_main_panel(solver)
        state = classify_room_state(Scene.TRAIN_MAIN, panel.countdown)
        if state == "empty" and solver.find("training_completed"):
            # "刚完成"的 TRAIN_MAIN（训练完成横幅）→ 🟡 待收取
            state = "waiting_collect"
        return RoomState(state, panel)
    # 其他房内场景（技能选择/确认/未知）→ 保守视为占用，面板尽力读
    return RoomState("training", _safe_read_panel(solver))


def _safe_read_panel(solver) -> RoomPanel:
    try:
        return read_main_panel(solver)
    except Exception as e:
        logger.debug(f"面板读取失败: {e}")
        return RoomPanel()


# --- 计划匹配（截图权威） ---


def _plan_operator_matches(plan, operator_name: str) -> bool:
    if not operator_name:
        return False
    return operator_name == plan.get("char_name") or operator_name == plan.get(
        "char_id"
    )


def _plan_matches_room(plan, room: RoomState) -> bool:
    """active 计划与截图是否一致：干员名必须匹配；技能名可读时须 ⊂ 计划 skill_name。

    干员名/技能名不可读（OCR 失败）时不判不一致，防误重置（铁律：截图为准，稳为先）。
    """
    if not room.panel.operator_name:
        return True
    if not _plan_operator_matches(plan, room.panel.operator_name):
        return False
    sk = room.panel.skill_name
    if not sk:
        return True
    return panel_skill_matches(sk, plan.get("skill_name"))


def _match_plan(plans, room: RoomState):
    """截图 (干员,技能) → 非终态计划命中；未命中返回 None。"""
    op = room.panel.operator_name
    if not op:
        return None
    sk = room.panel.skill_name
    for p in plans:
        if p["status"] in ("completed", "failed"):
            continue
        if not _plan_operator_matches(p, op):
            continue
        if sk and not panel_skill_matches(sk, p.get("skill_name")):
            continue
        return p
    return None


def _plan_label(plan) -> str:
    name = plan.get("char_name") or plan.get("char_id")
    return f"{name} {plan.get('skill_name') or format_skill_label(plan.get('skill_index', 0))}"


# --- 调度原语 ---


def _upsert_skill_upgrade_task(solver, target_time, meta_data="", plan_key=None):
    """入队/改期一条 SKILL_UPGRADE 任务，队列恒 ≤1 条同形任务（#62 Q3 收敛）。

    - plan_key=None：占用重检 / 重启恢复保活（meta_data 留空，任务列表仅显示类型名）；
    - plan_key=计划ID：某计划到点收取任务（meta_data=描述性标签，去重按 plan_key）。
    """
    current = getattr(solver, "task", None)
    task = next(
        (
            t
            for t in solver.tasks
            if t.type == TaskTypes.SKILL_UPGRADE
            and t is not current
            and getattr(t, "plan_key", None) == plan_key
        ),
        None,
    )
    if task is None:
        task = SchedulerTask(
            time=target_time, task_type=TaskTypes.SKILL_UPGRADE, meta_data=meta_data
        )
        task.plan_key = plan_key
        solver.tasks.append(task)
    else:
        task.time = target_time
        if meta_data:
            task.meta_data = meta_data


def _target_label(level: int) -> str:
    """专精等级中文标签：1→专一、2→专二、3→专三。"""
    return ("", "专一", "专二", "专三")[level]


def _schedule_collect(solver, plan, execute_time):
    """安排某计划到点收取任务；同计划已有一条时原地改时间（#62 Q3 收敛：统一入队原语）。

    去重按 plan_key=计划ID；meta_data 存描述性标签（技能名 + 目标专精等级），
    替代原 plan_id 数字。图标亮灯数即目标等级，与标签中目标冗余，故不在标签展示。
    """
    label = f"{_plan_label(plan)} → {_target_label(plan['target_level'])}"
    _upsert_skill_upgrade_task(
        solver, execute_time, meta_data=label, plan_key=str(plan["id"])
    )


# --- 矩阵动作 ---


def _reset_to_idle(solver, plan):
    """重置计划为 idle。退出训练室由调用方统一处理（dispatch 或排班 gate）。"""
    from arknights_mower.utils.mastery_db import update_plan_status

    logger.warning(f"Plan {plan['id']} 异常状态，重置为 idle")
    update_plan_status(plan["id"], "idle")


def _reset_fake(solver, plan, room):
    """假记录：DB active 与截图不一致 → 重置该计划 idle + 通知②。"""
    from arknights_mower.utils.email import send_message
    from arknights_mower.utils.mastery_db import should_notify, update_plan_status

    update_plan_status(plan["id"], "idle")
    if should_notify("fake_reset", str(plan["id"])):
        msg = (
            f"专精计划 {_plan_label(plan)} 与训练室实际状态不符，"
            f"已重置为待执行（截图：{room.panel.operator_name or '空房'}）"
        )
        send_message(msg, level="WARNING")


def _update_expiry(solver, plan, room):
    """training×🔴 一致：静默重读倒计时、更新 expires_at、重排收取。"""
    from arknights_mower.utils.mastery_db import update_plan_status

    countdown = room.panel.countdown
    if countdown is None:
        return
    expires_at = countdown.strftime("%Y-%m-%d %H:%M:%S")
    update_plan_status(plan["id"], "training", expires_at=expires_at)
    _schedule_collect(solver, plan, countdown)


def _wait_for_training(solver, room):
    """idle×🔴 命中：保持 idle，静默等它练完（重排到倒计时+2min），级联靠后续收取。"""
    countdown = room.panel.countdown
    if countdown is None:
        return
    logger.info(
        f"训练室使用中，计划保持待执行，任务重排到 {countdown + ARRANGING_RETRY_BUFFER}"
    )
    _upsert_skill_upgrade_task(solver, countdown + ARRANGING_RETRY_BUFFER)


def _notify_blocked(solver, room):
    """① 队列被计划外训练阻塞至X + mower会帮忙收取（各一次）。"""
    from arknights_mower.utils.email import send_message
    from arknights_mower.utils.mastery_db import should_notify

    countdown = room.panel.countdown
    if countdown is None:
        key = "unknown"
        tail = ""
    else:
        key = countdown.strftime("%Y-%m-%d %H:%M:%S")
        tail = f"至 {key}"
    if should_notify("blocked", key):
        op = room.panel.operator_name or "未知干员"
        msg = (
            f"训练室被计划外训练占用{tail}（{op}），"
            "mower 会在其完成后帮忙收取，期间队列保持待执行"
        )
        send_message(msg, level="WARNING")


# --- 收取流程（#61 定死） ---


def _tap_finish_mark(solver):
    """点左下角完成标记进收取页：优先模板定位，兜底旧坐标。

    旧坐标 (0.05w,0.95h) 实机疑似打不中（#63 待实现细节），模板命中时优先。
    """
    for tpl in ("skill_collect_confirm", "training_completed"):
        pos = solver.find(tpl)
        if pos:
            solver.tap(pos, interval=0.5)
            return
    solver.tap((solver.recog.w * 0.05, solver.recog.h * 0.95), interval=0.5)


def _tap_collect_confirm(solver):
    """收取后点勾确认收尾：优先 confirm_train 模板。位置实机校准待办。"""
    pos = solver.find("confirm_train")
    if pos:
        solver.tap(pos, interval=0.5)
    else:
        solver.tap((solver.recog.w * 0.5, solver.recog.h * 0.85), interval=0.5)
    for _ in range(6):
        scene = solver.train_scene()
        if scene in (Scene.TRAIN_MAIN, Scene.INFRA_MAIN):
            return
        solver.sleep(1)


def collect_flow(solver, plan, panel: RoomPanel):
    """#61 定死收取流程。plan 可为 None（未命中纯收取）。返回收集页截图。

    1. 主页面已读（panel，全部信息源）
    2. 点左下角完成标记 → 进收取页（动画）
    3. sleep ~2s
    4. 点任意处 → 跳过动画 → 稳定页
    5. 截图（收集页不读文本）
    6. 档位==专3 → 邮件（截图 + 第1步信息）
    7. 对账（用第1步档位）：N≥target completed级联 / <target 继续
    8. 点勾确认
    """
    from arknights_mower.utils.email import send_message
    from arknights_mower.utils.mastery_db import should_notify

    _tap_finish_mark(solver)
    solver.sleep(2)
    solver.tap((solver.recog.w * 0.5, solver.recog.h * 0.5), interval=1)
    solver.recog.update()
    screenshot = solver.recog.img

    tier = panel.mastery_tier
    if tier == 3 and plan is not None:
        if should_notify("m3_collect", str(plan["id"])):
            body = (
                f"{_plan_label(plan)} 专精三级完成收取\n"
                f"干员：{panel.operator_name}｜技能：{panel.skill_name}｜档位：专{tier}"
            )
            send_message(body, level="INFO", attach_image=screenshot)
    # 8. 点勾确认收尾
    _tap_collect_confirm(solver)
    return screenshot


def _reconcile_after_collect(solver, plan, panel: RoomPanel):
    """收集后对账：N≥target completed级联 / <target 继续。返回需要开始的计划或 None。"""
    from arknights_mower.utils.mastery_db import get_next_idle_plan, update_plan_status

    if plan is None:
        return None
    tier = panel.mastery_tier
    if tier >= plan["target_level"]:
        logger.info(
            f"{_plan_label(plan)} 专{plan['target_level']} 完成（收集档位 专{tier}）"
        )
        update_plan_status(plan["id"], "completed")
        return get_next_idle_plan()
    logger.info(
        f"{_plan_label(plan)} 收集档位 专{tier} < 目标专{plan['target_level']}，继续下一级"
    )
    update_plan_status(plan["id"], "idle")
    return plan


def _collect_plan(solver, plan, room: RoomState):
    """命中计划：收集 + 对账。返回级联/继续需要开始的计划或 None。"""
    collect_flow(solver, plan, room.panel)
    return _reconcile_after_collect(solver, plan, room.panel)


def _collect_silent(solver, room: RoomState):
    """未命中计划：纯收取静默（不通知不对账）。"""
    collect_flow(solver, None, room.panel)


def _next_idle_to_start(solver):
    from arknights_mower.utils.mastery_db import get_next_idle_plan

    return get_next_idle_plan()


# --- 矩阵对账（#61） ---


def reconcile_and_act(solver):
    """共享读取器主入口：进房读全部 + 矩阵对账执行。

    返回 (start_plan, arrange_support)：
    - start_plan：需要开始训练的计划（长动作由 SKILL_UPGRADE dispatch 执行），无则 None；
    - arrange_support：False 表示是「收取→下一次开始」边界（减半守卫：不重排协助位）。
    一次进房做完全部动作；无开始计划时保证离开训练室。
    """
    from arknights_mower.utils.mastery_db import get_active_plan, get_all_plans

    if not config.conf.enable_mastery:
        return None, True
    room = read_room_state(solver)
    active = get_active_plan()
    plans = get_all_plans()
    plan, arrange_support = _reconcile(solver, room, active, plans)
    if plan is None:
        # 各矩阵路径已 back 的不会重复退出；收集后无级联 / 空房无计划时在此退出
        try:
            scene = solver.train_scene()
            if scene in (Scene.TRAIN_MAIN, Scene.TRAIN_FINISH):
                solver.back()
        except Exception:
            pass
    return plan, arrange_support


def _reconcile(solver, room: RoomState, active, plans):
    """#61 恢复矩阵。行=DB 状态，列=截图房间状态。

    返回 (start_plan, arrange_support)：start_plan 为需要开始训练的计划或 None；
    arrange_support=False 表示收集级联（跨「收取→下一次开始」边界不动协助位）。
    """
    from arknights_mower.utils.mastery_db import update_plan_status

    # arranging × 任何列 → 重置 idle
    if active is not None and active["status"] == "arranging":
        _reset_to_idle(solver, active)
        active = None

    if room.state == "empty":
        # training/waiting_collect × ⚪ → 截图权威：DB 说在练但房空 → 重置 idle 重开。
        # 可能是收取后未确认/用户手动收取/假记录，统一重开（含已到target检测），
        # 不误报「假记录」通知②（空房无从比对截图）。
        if active is not None:
            logger.info(
                f"训练室为空但计划 {active['id']} 显示 {active['status']}，重置 idle 重开"
            )
            update_plan_status(active["id"], "idle")
        return _next_idle_to_start(solver), True

    hit = _match_plan(plans, room)

    if active is not None:
        if _plan_matches_room(active, room):
            if room.state == "training":
                _update_expiry(solver, active, room)
                return None, True
            return _collect_plan(solver, active, room), False  # 收集级联
        # active 与截图不一致 → 假记录 → 重置 + 通知②
        _reset_fake(solver, active, room)

    if hit is not None:
        if hit["status"] == "idle":
            if room.state == "training":
                # idle×🔴 命中：静默等它练完（级联靠后续收取），不打断
                _wait_for_training(solver, room)
                return None, True
            return _collect_plan(solver, hit, room), False  # idle×🟡 帮收+对账
        # hit 为另一条 active 状态计划（active 重置后）
        if room.state == "training":
            _update_expiry(solver, hit, room)
            return None, True
        return _collect_plan(solver, hit, room), False

    if room.state == "training":
        # 计划外训练 → 通知①。干员名不可读（OCR 失败）时不判计划外，静默等待。
        if room.panel.operator_name:
            _notify_blocked(solver, room)
        else:
            logger.debug("训练室占用但面板干员名不可读，静默等待")
        return None, True
    _collect_silent(solver, room)  # 未命中纯收取静默
    return None, True


def reconcile_short(solver, room_state: RoomState):
    """排班路径顺路短动作（#61）：核实/帮收/重置/对账，不开始训练、不退出房间。

    供 agent_arrange_room 的 gate 在锁定确认后调用；开始训练（长动作）留给
    SKILL_UPGRADE dispatch。退出训练室由调用方（gate）统一负责。
    """
    from arknights_mower.utils.mastery_db import get_active_plan, get_all_plans

    _reconcile(solver, room_state, get_active_plan(), get_all_plans())


# --- 排班 gate 复用（#59） ---


def train_slot_locked(solver) -> bool:
    """训练位是否锁定（choose_train D4 用）。

    详情开着时按确定化流程：确认详情渲染完成后关回 TRAIN_MAIN 读倒计时，
    再重开详情，防止动画中误退房（#59）。
    """
    scene = solver.train_scene()
    if scene == Scene.INFRA_DETAILS:
        solver.back(interval=0.5)
        scene = solver.train_scene()
    if scene == Scene.TRAIN_FINISH:
        return True
    if scene == Scene.TRAIN_MAIN:
        countdown = _read_train_countdown(solver)
        locked = countdown is not None and countdown > datetime.now()
        if not locked and solver.find("training_completed"):
            locked = True
        # 重开详情供调用方继续（仅当原本在详情里）
        solver.turn_on_room_detail("train")
        return locked
    # 其他房内场景保守视为锁定
    return True
