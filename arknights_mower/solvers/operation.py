from datetime import datetime, timedelta
from typing import Optional

import cv2

from arknights_mower.models import secret_front
from arknights_mower.utils import config
from arknights_mower.utils import typealias as tp
from arknights_mower.utils.datetime import get_server_weekday
from arknights_mower.utils.graph import SceneGraphSolver
from arknights_mower.utils.image import cropimg, thres2
from arknights_mower.utils.log import logger
from arknights_mower.utils.recognize import Scene


class OperationSolver(SceneGraphSolver):
    def run(self, stop_time: datetime):
        logger.info("Start: 代理作战")
        self.stop_time = stop_time - timedelta(minutes=5)
        self.sanity_drain = False
        self.auto_repeat = True
        self.repeat_button_attempts = 0
        super().run()
        return self.sanity_drain

    def number(self, scope: tp.Scope, height: Optional[int] = None):
        img = cropimg(self.recog.gray, scope)
        if height:
            scale = 25 / height
            img = cv2.resize(img, None, None, scale, scale)
        img = thres2(img, 127)
        contours, _ = cv2.findContours(img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rect = [cv2.boundingRect(c) for c in contours]
        rect.sort(key=lambda c: c[0])

        value = 0

        for x, y, w, h in rect:
            if w < 5 or h < 5:
                continue
            digit = cropimg(img, ((x, y), (x + w, y + h)))
            digit = cv2.copyMakeBorder(
                digit, 10, 10, 10, 10, cv2.BORDER_CONSTANT, None, (0,)
            )
            score = []
            for i in range(10):
                im = secret_front[i]
                result = cv2.matchTemplate(digit, im, cv2.TM_SQDIFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                score.append(min_val)
            value = value * 10 + score.index(min(score))

        return value

    def repeat_slot_scope(self, repeat_times: int) -> tp.Scope:
        y = 291 + (6 - repeat_times) * 93
        return (1445, y), (1555, y + 90)

    def best_repeat_option(self) -> tuple[int, tp.Scope]:
        for repeat_times in range(6, 0, -1):
            scope = self.repeat_slot_scope(repeat_times)
            if repeat_times > 1 and self.find("operation/+", scope=scope):
                continue
            img = cropimg(self.recog.gray, scope)
            img = thres2(img, 200)
            if repeat_times > 1 and cv2.countNonZero(img) < 60:
                continue
            return repeat_times, scope
        return 1, self.repeat_slot_scope(1)

    def transition(self):
        if (scene := self.scene()) == Scene.OPERATOR_BEFORE:
            # Let the caller decide whether there is enough time before the next task.
            # if datetime.now() > self.stop_time:
            #     return True
            if self.recog.gray[907][1600] < 127:
                self.tap((1776, 908))
                return
            if self.auto_repeat:
                if self.repeat_button_attempts == 0:
                    self.repeat_button_attempts += 1
                    self.tap((1501, 891), interval=0.5)
                    return
                if self.find("operation/x3") or self.find("operation/x4"):
                    repeat_times, scope = self.best_repeat_option()
                    logger.info(f"选择连战次数：{repeat_times}次")
                    self.tap(self.get_pos(scope), interval=0.5)
                    self.auto_repeat = False
                    self.repeat_button_attempts = 0
                    return
                repeat = self.number(((1520, 890), (1545, 930)), 28)
                logger.debug(
                    f"operation repeat_status: {repeat=}, {self.auto_repeat=}, {self.repeat_button_attempts=}"
                )
                if repeat > 1:
                    logger.info(
                        f"repeat panel fallback triggered, selecting legacy option: {repeat}"
                    )
                    self.tap((1500, 910), interval=0.5)
                    self.tap((1500, 801), interval=0.5)
                    self.auto_repeat = False
                    self.repeat_button_attempts = 0
                    return
                self.auto_repeat = False
                self.repeat_button_attempts = 0
            self.tap_element("ope_start", interval=2)
        elif scene == Scene.OPERATOR_SELECT:
            self.tap((1655, 781))
        elif scene == Scene.OPERATOR_FINISH:
            # TODO: 掉落识别
            self.tap((310, 330))
        elif scene == Scene.OPERATOR_FAILED:
            self.tap((310, 330))
        elif scene == Scene.OPERATOR_ONGOING:
            if self.find("ope_agency_fail"):
                self.tap((121, 79))
            else:
                self.sleep(10)
        elif scene == Scene.OPERATOR_GIVEUP:
            self.tap_element("double_confirm/main", x_rate=1)
        elif scene == Scene.OPERATOR_RECOVER_POTION:
            use_medicine = False
            # 先看设置是否吃药
            if config.conf.maa_expiring_medicine:
                if config.conf.exipring_medicine_on_weekend:
                    use_medicine = get_server_weekday() >= 5
                else:
                    use_medicine = True
            # 再看是否有药可吃
            if use_medicine:
                img = cropimg(self.recog.img, ((1015, 515), (1170, 560)))
                img = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
                img = cv2.inRange(img, (170, 0, 0), (174, 255, 255))
                count = cv2.countNonZero(img)
                logger.debug(f"{count=}")
                use_medicine = count > 3000
            if use_medicine:
                logger.info("使用即将过期的理智药")
                self.tap((1635, 865))
                return
            else:
                self.sanity_drain = True
                return True
        elif scene == Scene.OPERATOR_RECOVER_ORIGINITE:
            self.sanity_drain = True
            return True
        elif scene == Scene.OPERATOR_ELIMINATE:
            if self.find("ope_agency_lock"):
                logger.error("无法代理当期剿灭")
                self.sanity_drain = True
                return True
            if self.find("1800"):
                logger.info("本周剿灭已完成")
                self.sanity_drain = True
                return True
            if pos := self.find("ope_elimi_agency"):
                self.tap(pos)
                return
            self.tap_element("ope_start", interval=2)
        elif scene == Scene.OPERATOR_ELIMINATE_AGENCY:
            self.tap_element("ope_elimi_agency_confirm", interval=2)
        elif scene in self.waiting_scene:
            self.waiting_solver()
        else:
            self.sanity_drain = False
            return True
