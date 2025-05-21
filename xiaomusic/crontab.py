import json

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.base import BaseTrigger
from apscheduler.triggers.cron import CronTrigger

from xiaomusic.holiday import is_off_day, is_working_day


class CustomCronTrigger(BaseTrigger):
    """自定义触发器，支持workday/offday特殊值"""

    def __init__(self, cron_expression, holiday_checker=None):
        self.cron_expression = cron_expression
        self.holiday_checker = holiday_checker

        # 分离表达式和注释
        expr_parts = cron_expression.split("#", 1)
        self.base_expression = expr_parts[0].strip()
        self.annotation = expr_parts[1].strip().lower() if len(expr_parts) > 1 else ""

        # 检查注释中是否包含特殊值
        self.check_workday = "workday" in self.annotation
        self.check_offday = "offday" in self.annotation

        # 构建基础Cron触发器
        try:
            self.base_trigger = CronTrigger.from_crontab(self.base_expression)
        except Exception as e:
            raise ValueError(f"无效的Cron表达式: {self.base_expression}") from e

    def get_next_fire_time(self, previous_fire_time, now):
        # 获取基础Cron表达式的下一个触发时间
        next_time = self.base_trigger.get_next_fire_time(previous_fire_time, now)

        if not next_time:
            return None

        # 如果需要检查工作日/休息日
        if self.check_workday or self.check_offday:
            year = next_time.year
            month = next_time.month
            day = next_time.day

            if self.check_workday:
                valid = is_working_day(year, month, day)
            else:  # check_offday
                valid = is_off_day(year, month, day)

            # 如果日期有效，返回时间；否则寻找下一个有效时间
            if valid:
                return next_time
            else:
                return self.get_next_fire_time(next_time, next_time)

        return next_time


class Crontab:
    def __init__(self, log):
        self.log = log
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.start()

    def add_job(self, expression, job):
        try:
            # 检查表达式中是否包含注释标记
            if "#" in expression and (
                "workday" in expression.lower() or "offday" in expression.lower()
            ):
                trigger = CustomCronTrigger(expression)
            else:
                trigger = CronTrigger.from_crontab(expression)

            self.scheduler.add_job(job, trigger)
        except ValueError as e:
            self.log.error(f"Invalid crontab expression {e}")
        except Exception as e:
            self.log.exception(f"Exception {e}")

    # 添加关机任务
    def add_job_stop(self, expression, xiaomusic, did, **kwargs):
        async def job():
            await xiaomusic.stop(did, "notts")

        self.add_job(expression, job)

    # 添加播放任务
    def add_job_play(self, expression, xiaomusic, did, arg1, **kwargs):
        async def job():
            await xiaomusic.play(did, arg1)

        self.add_job(expression, job)

    # 添加播放列表任务
    def add_job_play_music_list(self, expression, xiaomusic, did, arg1, **kwargs):
        async def job():
            await xiaomusic.play_music_list(did, arg1)

        self.add_job(expression, job)

    # 添加语音播放任务
    def add_job_tts(self, expression, xiaomusic, did, arg1, **kwargs):
        async def job():
            await xiaomusic.do_tts(did, arg1)

        self.add_job(expression, job)

    # 刷新播放列表任务
    def add_job_refresh_music_list(self, expression, xiaomusic, **kwargs):
        async def job():
            await xiaomusic.gen_music_list()

        self.add_job(expression, job)

    # 设置音量任务
    def add_job_set_volume(self, expression, xiaomusic, did, arg1, **kwargs):
        async def job():
            await xiaomusic.set_volume(did, arg1)

        self.add_job(expression, job)

    # 设置播放类型任务
    def add_job_set_play_type(self, expression, xiaomusic, did, arg1, **kwargs):
        async def job():
            play_type = int(arg1)
            await xiaomusic.set_play_type(did, play_type, False)

        self.add_job(expression, job)

    # 开启或关闭获取对话记录
    def add_job_set_pull_ask(self, expression, xiaomusic, did, arg1, **kwargs):
        async def job():
            if arg1 == "enable":
                xiaomusic.config.enable_pull_ask = True
            else:
                xiaomusic.config.enable_pull_ask = False

        self.add_job(expression, job)

    # 重新初始化
    def add_job_reinit(self, expression, xiaomusic, did, arg1, **kwargs):
        async def job():
            xiaomusic.reinit()

        self.add_job(expression, job)

    def add_job_cron(self, xiaomusic, cron):
        expression = cron["expression"]  # cron 计划格式
        name = cron["name"]  # stop, play, play_music_list, tts
        did = cron.get("did", "")
        arg1 = cron.get("arg1", "")
        jobname = f"add_job_{name}"
        func = getattr(self, jobname, None)
        if callable(func):
            func(expression, xiaomusic, did=did, arg1=arg1)
            self.log.info(
                f"crontab add_job_cron ok. did:{did}, name:{name}, arg1:{arg1} expression:{expression}"
            )
        else:
            self.log.error(
                f"'{self.__class__.__name__}' object has no attribute '{jobname}'"
            )

    # 清空任务
    def clear_jobs(self):
        for job in self.scheduler.get_jobs():
            try:
                job.remove()
            except Exception as e:
                self.log.exception(f"Execption {e}")

    # 重新加载计划任务
    def reload_config(self, xiaomusic):
        self.clear_jobs()

        crontab_json = xiaomusic.config.crontab_json
        if not crontab_json:
            return

        try:
            cron_list = json.loads(crontab_json)
            for cron in cron_list:
                self.add_job_cron(xiaomusic, cron)
            self.log.info("crontab reload_config ok")
        except Exception as e:
            self.log.exception(f"Execption {e}")
