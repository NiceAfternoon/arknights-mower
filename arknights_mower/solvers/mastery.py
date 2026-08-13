import json
from datetime import datetime, timedelta

from arknights_mower.solvers.mastery_reader import (
    RoomPanel,
    RoomState,
    _count_lit_mastery_icons,
    _plan_label,
    _plan_matches_room,
    _read_panel_text,
    _read_train_countdown,
    _schedule_collect,
    _target_label,
    _wait_for_training,
)
from arknights_mower.utils.log import logger
from arknights_mower.utils.scene import Scene

ARRANGING_DEADLINE = timedelta(minutes=10)
ARRANGING_RETRY_BUFFER = timedelta(minutes=2)

DEFAULT_ROUTES = {
    "先锋": {
        "level_1": {
            "operator": "夜半",
            "efficiency": 75,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_2": {
            "operator": "缄默德克萨斯",
            "efficiency": 80,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_3": {
            "operator": "凛御银灰",
            "efficiency": 80,
            "job_match": False,
            "swap_target": None,
        },
    },
    "近卫": {
        "level_1": {
            "operator": "赤冬",
            "efficiency": 75,
            "job_match": True,
            "swap_target": "艾丽妮",
        },
        "level_2": {
            "operator": "燧石",
            "efficiency": 75,
            "job_match": True,
            "swap_target": "艾丽妮",
        },
        "level_3": {
            "operator": "百炼嘉维尔",
            "efficiency": 95,
            "job_match": True,
            "swap_target": None,
        },
    },
    "重装": {
        "level_1": {
            "operator": "极光",
            "efficiency": 75,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_2": {
            "operator": "暴雨",
            "efficiency": 75,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_3": {
            "operator": "星熊",
            "efficiency": 60,
            "job_match": False,
            "swap_target": None,
        },
    },
    "狙击": {
        "level_1": {
            "operator": "假日威龙陈",
            "efficiency": 95,
            "job_match": True,
            "swap_target": "艾丽妮",
        },
        "level_2": {
            "operator": "埃拉托",
            "efficiency": 75,
            "job_match": True,
            "swap_target": "艾丽妮",
        },
        "level_3": {
            "operator": "W",
            "efficiency": 95,
            "job_match": True,
            "swap_target": None,
        },
    },
    "术师": {
        "level_1": {
            "operator": "特米米",
            "efficiency": 75,
            "job_match": True,
            "swap_target": "逻各斯",
        },
        "level_2": {
            "operator": "薄绿",
            "efficiency": 75,
            "job_match": True,
            "swap_target": "逻各斯",
        },
        "level_3": {
            "operator": "死芒",
            "efficiency": 95,
            "job_match": True,
            "swap_target": None,
        },
    },
    "医疗": {
        "level_1": {
            "operator": "阿",
            "efficiency": 60,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_2": {
            "operator": "濯尘芙蓉",
            "efficiency": 75,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_3": {
            "operator": "阿",
            "efficiency": 60,
            "job_match": False,
            "swap_target": None,
        },
    },
    "辅助": {
        "level_1": {
            "operator": "铃兰",
            "efficiency": 60,
            "job_match": True,
            "swap_target": "逻各斯",
        },
        "level_2": {
            "operator": "铃兰",
            "efficiency": 60,
            "job_match": True,
            "swap_target": "逻各斯",
        },
        "level_3": {
            "operator": "浊心斯卡蒂",
            "efficiency": 95,
            "job_match": True,
            "swap_target": None,
        },
    },
    "特种": {
        "level_1": {
            "operator": "罗宾",
            "efficiency": 75,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_2": {
            "operator": "缄默德克萨斯",
            "efficiency": 80,
            "job_match": False,
            "swap_target": "逻各斯",
        },
        "level_3": {
            "operator": "归溟幽灵鲨",
            "efficiency": 95,
            "job_match": False,
            "swap_target": None,
        },
    },
}

PROF_MAP = {
    "PIONEER": "先锋",
    "WARRIOR": "近卫",
    "TANK": "重装",
    "SNIPER": "狙击",
    "CASTER": "术师",
    "MEDIC": "医疗",
    "SUPPORT": "辅助",
    "SPECIAL": "特种",
}


def get_route_config(profession_cn: str, level: int) -> dict | None:
    from arknights_mower.utils.mastery_db import get_route

    route_data = get_route(profession_cn)
    if route_data:
        parsed = json.loads(route_data["supports"])
        level_key = f"level_{level}"
        if level_key in parsed:
            config_entry = dict(parsed[level_key])
            config_entry["central_bonus"] = parsed.get("central_bonus", 5)
            return config_entry

    default = DEFAULT_ROUTES.get(profession_cn)
    if default:
        entry = default.get(f"level_{level}")
        if entry:
            config_entry = dict(entry)
            config_entry["central_bonus"] = 5
            return config_entry
    return None


def get_char_name(char_id: str) -> str:
    """从 char_id 获取干员显示名"""
    try:
        from arknights_mower.utils.mastery_recommendation import get_skill_data

        char_table = get_skill_data().get("characters", {})
        return char_table.get(char_id, {}).get("name", char_id)
    except Exception:
        return char_id


def _plan_char_label(plan) -> str:
    """邮件/日志里的干员标识：优先库里的 char_name，回退 get_char_name(char_id)。

    #53 根因3：旧文案用 skill_name（技能名，如「战地秘闻」）冒充干员名，
    邮件读不出练谁。计划经 add_mastery_plan 工具新增时 char_name 为 NULL，
    需要 get_char_name 兜底。
    """
    return plan.get("char_name") or get_char_name(plan["char_id"])


def calc_swap_threshold(
    current_efficiency: int,
    swap_job_match: bool,
    central_bonus: int,
    remaining_minutes: float,
    buffer: int = 10,
) -> tuple[bool, float]:
    """计算是否应该换入减半对象。

    Args:
        current_efficiency: 当前协助位效率百分比 (如 75)
        swap_job_match: 减半对象是否有职业匹配加成 (+30%)
        central_bonus: 中枢加成 (0 或 5)
        remaining_minutes: 当前倒计时剩余分钟数
        buffer: 缓冲时间(分钟)

    Returns:
        (should_swap, threshold_minutes)
        should_swap: 是否应该换人
        threshold_minutes: 换人阈值（倒计时降到这个值时执行换人）
    """
    target_minutes = 300 + buffer  # 5小时 + 缓冲

    swap_match_bonus = 30 if swap_job_match else 0
    swap_total = 100 + 5 + swap_match_bonus + central_bonus
    current_total = 100 + current_efficiency + 5 + central_bonus

    threshold = target_minutes * swap_total / current_total

    real_time_after_swap = remaining_minutes * current_total / swap_total
    if real_time_after_swap < 300:
        return False, threshold

    return remaining_minutes <= threshold, threshold


def _log_transition(plan, to_status, trigger, **fields):
    """#17 埋点①：状态机转换的结构化日志（统一 [mastery] 前缀）。

    仅记录不改变行为；真实状态更新仍走 update_plan_status。
    """
    parts = [
        f"id={plan['id']}",
        f"{plan.get('status')}→{to_status}",
        f"触发源={trigger}",
    ]
    parts.extend(f"{k}={v}" for k, v in fields.items())
    logger.info(f"[mastery] 状态转换 {' '.join(parts)}")


def run_mastery_task(solver):
    """SKILL_UPGRADE dispatch：共享读取器进房读全部 + #61 矩阵对账执行。

    读取器返回需要开始训练的计划时，由本入口执行开始（长动作）。
    不再依赖 DB 状态预判（铁律：先读房，截图为准）。
    """
    from arknights_mower.utils import config

    if not config.conf.enable_mastery:
        logger.debug("[mastery] 全自动专精已关闭，跳过训练室动作")
        return
    from arknights_mower.solvers.mastery_reader import reconcile_and_act

    logger.debug("[mastery] 训练室动作 触发源=定时任务 动作=dispatch")
    plan, arrange_support = reconcile_and_act(solver)
    if plan:
        _start_new_training(solver, plan, arrange_support=arrange_support)


def _training_slots(solver):
    """读训练室两个槽位的干员名，返回 (协助位, 训练位)。

    槽位约定（与 choose_train 基类一致，#53 从实机 log 佐证）：
    - scan[0] = 上排 = 协助位；scan[1] = 下排 = 训练位
      （get_agent_from_room 与 operator_list_train 的 name_y 均为 上→下）
    - choose_train 内部 idx==0 走 choose_agent（协助位）、idx==1 走
      choose_train_ope（训练位），get_agent_from_room 的 scan 与之同序
    - 现有调用佐证：_arrange_support / run_swap_support 传
      choose_train([协助干员, "Current"])，都把 idx0 当协助位
    读不到名字的槽位返回 ""。
    """
    scan = solver.get_agent_from_room("train")
    if len(scan) < 2:
        return "", ""
    return scan[0].get("agent", ""), scan[1].get("agent", "")


def _swap_into_wrong_slot(solver, plan):
    """无倒计时 + 训练位坐错人：复用 choose_train 换人。

    #16 决议「协助位不动」：只换训练位，传 ["Current", 训练位目标]
    （idx0=Current 保持协助位原样，idx1=训练位换入计划干员）；
    开始训练前不改协助位（设计规范 §8）。
    以 choose_train 异常为唯一失败信号；失败由调用方统一走失败出口。
    """
    solver.choose_train(["Current", _plan_char_label(plan)])


def _exit_failed(solver, plan, reason):
    """ARRANGING 失败统一出口：标记 failed + 一次通知 + 退出训练室，不在 ARRANGING 内重试。"""
    from arknights_mower.utils.email import send_message
    from arknights_mower.utils.mastery_db import update_plan_status

    update_plan_status(plan["id"], "failed", failed_reason=reason)
    label = f"{_plan_char_label(plan)} 技能{plan['skill_index'] + 1} 专{plan['target_level']}"
    send_message(f"{label} {reason}", level="ERROR")
    solver.back()


def _exit_arranging_timeout(solver, plan, stats, stuck_scene):
    """#15 决议的统一超时出口：标记 failed + 可读失败原因 + 一次通知 + 结构化轨迹诊断。

    用户已定案（#19 实现时与 #15「置 idle」矛盾）：置 failed，避免 infra 主循环
    （base_schedule.py:705 对 idle 计划立即重派）导致每 10 分钟重复超时刷屏；
    等仓库扫描 retry_failed_plans() 重置。
    """
    from arknights_mower.utils.email import send_message
    from arknights_mower.utils.mastery_db import update_plan_status

    scene_name = _scene_name(stuck_scene) if stuck_scene is not None else "无"
    reason = "开始训练超时，未能确认训练是否开始"
    # #17 埋点⑤：超时兜底记录（#15 定纯墙钟、无加载豁免，字段恒 false 保留）
    logger.warning(
        f"[mastery] ARRANGING超时 id={plan['id']} 豁免加载=False 卡在={scene_name} "
        f"原因={reason}"
    )
    update_plan_status(plan["id"], "failed", failed_reason=reason)
    label = f"{_plan_char_label(plan)} 技能{plan['skill_index'] + 1} 专{plan['target_level']}"
    logger.warning(
        f"ARRANGING 超时退出: {reason} | 诊断: 最后持续停留在『{scene_name}』页面 | "
        f"轨迹: {stats}"
    )
    send_message(
        f"{label}：开始训练超时，最后持续停留在『{scene_name}』页面，未能确认训练是否开始，"
        "已暂停，将在下次仓库扫描后重试",
        level="ERROR",
    )
    solver.back()


class _SceneTracker:
    """ARRANGING 超时诊断的廉价轨迹计数器（#15 决议）。"""

    def __init__(self):
        self.counts: dict[str, int] = {}
        self.last = None
        self.consecutive = {"scene": None, "count": 0}
        self.max_consecutive = {"scene": None, "count": 0}
        self.reenter_cnt = 0
        self.reached_upgrade = False

    def record(self, scene):
        name = _scene_name(scene)
        self.counts[name] = self.counts.get(name, 0) + 1
        if scene != self.last:
            self.consecutive = {"scene": name, "count": 0}
            self.last = scene
        self.consecutive["count"] += 1
        if self.consecutive["count"] > self.max_consecutive["count"]:
            self.max_consecutive = dict(self.consecutive)

    def mark_upgrade(self):
        self.reached_upgrade = True

    def reenter(self):
        self.reenter_cnt += 1

    def last_scene(self):
        return self.last

    def stuck_scene(self):
        """最长连续停留的场景名，用于「卡在哪」的诊断。"""
        return self.max_consecutive["scene"]

    def format_stats(self) -> str:
        dominant = max(self.counts, key=self.counts.get) if self.counts else "无"
        return (
            f"各场景次数 {self.counts} | 最后场景 {self.consecutive['scene']} | "
            f"最大连续 {self.max_consecutive['scene']}×{self.max_consecutive['count']} | "
            f"到过确认页 {self.reached_upgrade} | 重进房 {self.reenter_cnt} | 主导 {dominant}"
        )


def _scene_name(scene) -> str:
    for key, value in Scene.__dict__.items():
        if not key.startswith("_") and value == scene:
            return key
    return str(scene)


def _exit_occupied(solver, plan, countdown, trigger="训练室占用"):
    """训练室被占用 → 保持 idle + 重排 + 退出（#16/#69/B4/#70 共用）。

    countdown 可读时重排到倒计时+缓冲；不可读（面板归属与计划不符 / 已到target
    档位读取失败）时重排到 now+缓冲，避免占用期间每轮 dispatch 空转重试。
    trigger 写进状态转换日志，区分退出原因。
    """
    from arknights_mower.solvers.mastery_reader import _upsert_skill_upgrade_task
    from arknights_mower.utils.mastery_db import update_plan_status

    if countdown is not None and countdown > datetime.now():
        _wait_for_training(
            solver, RoomState("training", RoomPanel(countdown=countdown))
        )
        reschedule = countdown + ARRANGING_RETRY_BUFFER
    else:
        reschedule = datetime.now() + ARRANGING_RETRY_BUFFER
        _upsert_skill_upgrade_task(solver, reschedule)
    _log_transition(plan, "idle", trigger, 重排到=reschedule.strftime("%H:%M:%S"))
    update_plan_status(plan["id"], "idle")
    solver.back()


def _start_new_training(solver, plan, arrange_support=True):
    """开始新一级训练：IDLE → ARRANGING → TRAINING

    #16 决议：进房先读倒计时定分支，不盲点技能按钮。
    #15 决议：全程纯墙钟 10 分钟 deadline，各分支短处理、超时走统一退出路径。
    #63 减半守卫：跨「收取→下一次开始」边界不动协助位（保留驻留/激活），
    由 cascade 调用传 arrange_support=False（收取后级联不重新安排协助位）。
    """
    from arknights_mower.solvers.mastery_reader import _read_slot_mastery_tier
    from arknights_mower.utils.mastery_db import get_next_idle_plan, update_plan_status

    _log_transition(
        plan,
        "arranging",
        "定时任务",
        技能=plan["skill_index"] + 1,
        目标=plan["target_level"],
    )
    update_plan_status(plan["id"], "arranging")

    skill_index = plan["skill_index"] + 1  # 0-indexed to 1-indexed for display
    deadline = datetime.now() + ARRANGING_DEADLINE
    unknown_cnt = 0
    # #15 诊断粒度：各场景次数 / 最后场景 / 是否到过确认页 / 重进房次数 / 最大连续同场景
    tracker = _SceneTracker()
    checked_slot = False
    checked_target = False
    # #72：数星星前的身份/归属确认。只在 TRAIN_MAIN 训练位校验通过并主动点开技能
    # 选择页时置位；未置位就出现 219（运行页被误判成 219 等）→ 219 分支保守退出。
    identity_confirmed = False

    solver.enter_room("train")

    while True:
        scene = solver.train_scene()
        tracker.record(scene)

        if scene == Scene.UNKNOWN:
            unknown_cnt += 1
            if unknown_cnt > 5:
                unknown_cnt = 0
                solver.back_to_infrastructure()
                solver.enter_room("train")
                tracker.reenter()
            else:
                solver.sleep()
        elif scene == Scene.CONNECTING:
            solver.sleep()
        elif scene == Scene.INFRA_MAIN:
            solver.enter_room("train")
        elif scene == Scene.INFRA_DETAILS:
            # 房间详情浮层（get_agent_from_room 会打开它）→ 关掉回房间主界面
            solver.back()
        elif scene == Scene.TRAIN_FINISH:
            solver.tap((solver.recog.w * 0.05, solver.recog.h * 0.95), interval=0.5)
        elif scene == Scene.TRAIN_MAIN:
            execute_time = _read_train_countdown(solver)
            if execute_time is not None and execute_time > datetime.now():
                # 训练室使用中（#16 决议）：保持 idle，重排到倒计时+缓冲，退出
                _exit_occupied(solver, plan, execute_time)
                return
            if not checked_slot:
                # 无倒计时：检查训练位是否坐错人（#16 决议）。
                # get_agent_from_room 会打开房间详情浮层，读完后关掉再回主界面。
                support_slot, trainer_slot = _training_slots(solver)
                checked_slot = True
                char_name = _plan_char_label(plan)
                if trainer_slot and trainer_slot != char_name:
                    # 无倒计时 + 训练位坐错人 → 换人；失败统一以 choose_train 异常为判据
                    logger.info(f"训练位坐着 {trainer_slot}，换入 {char_name}")
                    try:
                        _swap_into_wrong_slot(solver, plan)
                    except Exception as e:
                        logger.warning(f"换人失败: {e}")
                        _exit_failed(solver, plan, "训练位被占用且换人失败")
                        return
                solver.back()  # 关闭房间详情浮层，回到训练室主界面
                continue
            # 训练位已确认（空/已是计划干员）→ 身份确认成立，点开技能选择页。
            # #72：数星星前唯一合法的身份/归属确认点——经训练位校验后主动进入技能
            # 选择页；运行页被误判成 219（不经此路径）在 219 分支直接保守退出。
            identity_confirmed = True
            solver.tap((solver.recog.w * 0.05, solver.recog.h * 0.95), interval=0.5)
        elif scene == Scene.TRAIN_SKILL_SELECT:
            if not identity_confirmed:
                # #72：真技能选择页只有 SKILL_SLOT_PIPS 星星可读，没有倒计时、读不到
                # `[干员名]技能名`——不能在 219 上读主面板区域（COUNTDOWN/PANEL）当占用
                # 探针（那只在"运行页被误判成 219"时才成立）。未经过 TRAIN_MAIN 训练位
                # 校验就出现 219 → 数星星前无法确认干员身份，星星可能误读非零值
                # （误开训练/误判完成，#70 只挡 None）→ 保守保持 idle 重排退出。
                logger.info(
                    f"{_plan_char_label(plan)} 技能选择页未经过训练位确认，"
                    "无法确认星星归属，保持 idle 重排"
                )
                _exit_occupied(solver, plan, None, trigger="技能选择页归属未确认")
                return
            if not checked_target:
                # #63 已到target检测：读目标技能槽亮灯，≥target → 判 completed 级联（防 false-fail）
                checked_target = True
                tier = _read_slot_mastery_tier(solver, plan["skill_index"])
                if tier is not None and tier >= plan["target_level"]:
                    logger.info(
                        f"{_plan_char_label(plan)} 技能{skill_index} 已在专{tier}，无需训练，判定完成"
                    )
                    _log_transition(plan, "completed", "已到target检测", 档位=tier)
                    update_plan_status(plan["id"], "completed")
                    next_plan = get_next_idle_plan()
                    if next_plan:
                        _start_new_training(solver, next_plan, arrange_support=False)
                    solver.back()
                    return
                if tier is None:
                    # #70/B5：档位读失败（无法判是否已到 target）→ 保守处理：保持
                    # idle 重排退出，绝不盲点技能行（可能重训已完成的档位）。
                    logger.info(
                        f"{_plan_char_label(plan)} 技能{skill_index} 专精档位读取失败，"
                        "无法确认是否已到目标档位，保持 idle 重排"
                    )
                    _exit_occupied(solver, plan, None, trigger="档位读取失败")
                    return
            height = (skill_index - 1) * 0.3 + 0.32
            solver.ctap((solver.recog.w * 0.33, solver.recog.h * height))
        elif scene == Scene.TRAIN_SKILL_UPGRADE:
            tracker.mark_upgrade()
            # #53 实机：确认按钮在 (1574,896)-(1870,968)，旧坐标 (0.87w,0.9h)=(1670,972)
            # 会点到按钮下方、把弹窗关掉退回技能选择页死循环。用 skill_confirm 模板
            # 定位按钮中心再点；找不到时退回旧坐标兜底。
            confirm = solver.find("skill_confirm")
            if confirm:
                solver.tap(confirm)
            else:
                solver.tap((solver.recog.w * 0.87, solver.recog.h * 0.9))
            solver.sleep(2)
            result = _confirm_training_started(solver, plan, deadline, arrange_support)
            if result == "started":
                return
            if result == "failed":
                return
        elif scene == Scene.TRAIN_SKILL_UPGRADE_ERROR:
            msg = f"{_plan_char_label(plan)} 技能{skill_index} 专{plan['target_level']} 材料不足"
            logger.warning(msg)
            _log_transition(plan, "failed", "材料不足")
            update_plan_status(plan["id"], "failed", failed_reason="材料不足")
            from arknights_mower.utils.email import send_message

            send_message(msg, level="ERROR")
            solver.back()
            return
        else:
            solver.sleep()

        if datetime.now() > deadline:
            _exit_arranging_timeout(
                solver, plan, tracker.format_stats(), tracker.stuck_scene()
            )
            return


def _confirm_training_started(solver, plan, deadline, arrange_support=True):
    """确认训练已开始（读到有效倒计时）→ 转入 TRAINING，然后安排协助位。

    并入 #15 的全局 10 分钟 deadline（由调用方传入），不单独分段计时。
    返回 "started" / "failed" / "timeout"：
    - started: 已转入 TRAINING 并完成协助位/收取安排
    - failed: 材料不足 或 #69/B2 面板干员/技能与计划不符，已标记 failed + 通知 + 退出训练室
    - timeout: deadline 内未确认训练开始（含面板不可读无法校验归属），由调用方走统一超时出口
    #63 减半守卫：arrange_support=False（收取后级联）不重新安排协助位。
    """
    from arknights_mower.utils.email import send_message
    from arknights_mower.utils.mastery_db import update_plan_status

    while datetime.now() < deadline:
        scene = solver.train_scene()
        # #53 实机：确认升级后训练已开始，但训练运行页会被识别成 TRAIN_SKILL_SELECT
        # （页面含协助位 training_support、不匹配 train_main）。#72 页面模型：这里出现
        # 的 219 是「运行页被误判」（物理上仍是主页面，倒计时/面板可读）——读倒计时是确认
        # 训练开始的正当读取，不是探针；真技能选择页无倒计时，读不到返回 now，
        # >now+30min 判定必为假 → 继续等（训练未开始），直到 deadline 走统一失败出口。
        if scene in (Scene.TRAIN_MAIN, Scene.TRAIN_SKILL_SELECT):
            execute_time = _read_train_countdown(solver)
            if execute_time and execute_time > datetime.now() + timedelta(minutes=30):
                # #69/B2 归属校验：写入 training 前，面板干员/技能必须与计划一致。
                # - 面板可读且不符 → 本次开始失败（绝不把陌生人的倒计时写进计划）；
                # - 面板可读且匹配 → 确认训练开始；
                # - 面板不可读（OCR 失败）→ 不写 training，继续等到 deadline（超时走
                #   统一失败出口），避免在无法确认归属时宣布"错误干员开始训练"。
                panel = _read_panel_text(solver)
                if panel.operator_name and not _plan_matches_room(
                    plan, RoomState("training", panel)
                ):
                    _exit_failed(solver, plan, "训练室面板干员/技能与计划不符，未开始训练")
                    return "failed"
                if not panel.operator_name:
                    logger.debug(
                        "训练室已出有效倒计时但面板干员名不可读，暂不写入 training，等待归属可读"
                    )
                    solver.sleep(1)
                    continue
                expires_at = execute_time.strftime("%Y-%m-%d %H:%M:%S")
                _log_transition(plan, "training", "倒计时确认", 完成时间=expires_at)
                update_plan_status(
                    plan["id"],
                    "training",
                    expires_at=expires_at,
                    swap_frozen=0,
                )
                remaining_hours = (execute_time - datetime.now()).total_seconds() / 3600
                msg = (
                    f"{_plan_char_label(plan)} 技能{plan['skill_index'] + 1} "
                    f"专{plan['target_level']} 开始训练，预计 {remaining_hours:.1f} 小时后完成"
                )
                logger.info(msg)
                send_message(msg, level="INFO")

                if arrange_support:
                    _arrange_support(solver, plan)
                _schedule_swap_if_needed(solver, plan, execute_time)
                tier = None
                if scene == Scene.TRAIN_MAIN:
                    try:
                        tier = _count_lit_mastery_icons(solver)
                    except Exception:
                        tier = None
                _schedule_collect(solver, plan, execute_time, tier=tier)
                return "started"
        elif scene == Scene.TRAIN_SKILL_UPGRADE_ERROR:
            msg = f"{_plan_char_label(plan)} 技能{plan['skill_index'] + 1} 专{plan['target_level']} 材料不足"
            _log_transition(plan, "failed", "材料不足")
            update_plan_status(plan["id"], "failed", failed_reason="材料不足")
            logger.warning(msg)
            send_message(msg, level="ERROR")
            solver.back()
            return "failed"
        solver.sleep(1)

    return "timeout"


def _arrange_support(solver, plan):
    """训练确认开始后，安排协助位干员（复用 choose_train）"""
    from arknights_mower.utils import config

    if config.conf.assistant_follows_schedule:
        return
    route = _get_plan_route(plan)
    if not route or not route.get("operator"):
        return
    support_name = route["operator"]
    logger.info(f"安排协助位：{support_name}")
    logger.debug(f"[mastery] 协助位判定 id={plan['id']} 期望={support_name} 动作=安排")
    try:
        solver.choose_train([support_name, "Current"])
        logger.debug(f"[mastery] 协助位判定 id={plan['id']} 结果=ok")
    except Exception as e:
        logger.warning(f"安排协助位失败: {e}")
        logger.debug(f"[mastery] 协助位判定 id={plan['id']} 结果=失败 err={e}")


def _schedule_swap_if_needed(solver, plan, execute_time):
    """训练开始后计算是否需要换人，如果需要则插入 SWAP_SUPPORT 任务"""
    from arknights_mower.utils import config

    if config.conf.assistant_follows_schedule:
        return
    if plan["target_level"] == 3:
        return

    route = _get_plan_route(plan)
    if not route or not route.get("swap_target"):
        return

    from arknights_mower.utils import config

    central_bonus = route.get("central_bonus", 5)
    buffer = config.conf.mastery_swap_buffer

    remaining = (execute_time - datetime.now()).total_seconds() / 60
    should_swap, threshold = calc_swap_threshold(
        route["efficiency"],
        route.get("job_match", False),
        central_bonus,
        remaining,
        buffer,
    )
    logger.info(
        f"[mastery] 换人公式 id={plan['id']} 效率={route['efficiency']} "
        f"匹配={route.get('job_match', False)} 加成={central_bonus} "
        f"剩余分钟={remaining:.0f} 阈值={threshold:.0f} 换人={should_swap}"
    )

    if not should_swap and remaining > threshold:
        from arknights_mower.utils.scheduler_task import SchedulerTask, TaskTypes

        swap_delay_seconds = (remaining - threshold) * 60
        if swap_delay_seconds > 0:
            swap_time = datetime.now() + timedelta(seconds=swap_delay_seconds)
            solver.tasks.append(
                SchedulerTask(
                    time=swap_time,
                    task_type=TaskTypes.SWAP_SUPPORT,
                    meta_data=(
                        f"{_plan_label(plan)} → {_target_label(plan['target_level'])} "
                        f"换入{route['swap_target']}"
                    ),
                )
            )
            logger.info(f"已安排换人任务，预计 {swap_time.strftime('%H:%M:%S')} 执行")


def run_swap_support(solver):
    """被 SWAP_SUPPORT 任务触发：换入减半对象"""
    from arknights_mower.utils import config
    from arknights_mower.utils.mastery_db import get_active_plan, update_plan_status

    logger.debug("[mastery] 训练室动作 触发源=定时任务 动作=swap")
    if not config.conf.enable_mastery:
        logger.debug("[mastery] 全自动专精已关闭，跳过换协助位")
        return
    if config.conf.assistant_follows_schedule:
        return

    plan = get_active_plan()
    if not plan or plan["status"] != "training":
        return
    if plan["swap_frozen"]:
        return
    if plan["target_level"] == 3:
        return

    route = _get_plan_route(plan)
    if not route or not route.get("swap_target"):
        return

    swap_target = route["swap_target"]
    logger.info(f"执行换人：协助位换入 {swap_target}")
    logger.debug(
        f"[mastery] 协助位判定 id={plan['id']} 期望={swap_target} 动作=换入减半对象"
    )

    try:
        solver.choose_train([swap_target, "Current"])
        update_plan_status(plan["id"], "training", swap_frozen=1)
        logger.info("换人完成，协助位已冻结")
        logger.debug(f"[mastery] 协助位判定 id={plan['id']} 结果=ok")
    except Exception as e:
        logger.warning(f"换人失败: {e}")
        logger.debug(f"[mastery] 协助位判定 id={plan['id']} 结果=失败 err={e}")


def _get_plan_route(plan) -> dict | None:
    """获取计划对应的路线配置"""
    try:
        from arknights_mower.utils.mastery_recommendation import get_skill_data

        char_data = get_skill_data().get("characters", {}).get(plan["char_id"], {})
        prof_en = char_data.get("profession", "")
        prof_cn = PROF_MAP.get(prof_en, prof_en)
        return get_route_config(prof_cn, plan["target_level"])
    except Exception as e:
        logger.error(f"获取路线配置失败: {e}")
        return None
