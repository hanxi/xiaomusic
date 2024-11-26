import json

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


class Crontab:
    def __init__(self, log):
        self.log = log
        self.scheduler = AsyncIOScheduler()

    def start(self):
        self.scheduler.start()

    def add_job(self, expression, job):
        try:
            trigger = CronTrigger.from_crontab(expression)
            self.scheduler.add_job(job, trigger)
        except ValueError as e:
            self.log.error(f"Invalid crontab expression {e}")
        except Exception as e:
            self.log.exception(f"Execption {e}")

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
                f"crontab add_job_cron ok. did:{did}, name:{name}, arg1:{arg1}"
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
