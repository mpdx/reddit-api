import structlog
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config_loader
import scraper

log = structlog.get_logger()


def run_scrape():
    subreddits = config_loader.get_subreddits()
    lookback = config_loader.get_lookback_hours()

    if not subreddits:
        log.warning("no subreddits configured, skipping run")
        return

    log.info("starting scheduled scrape", subreddits=subreddits)
    for sub in subreddits:
        try:
            scraper.scrape_subreddit(sub, lookback_hours=lookback)
        except Exception:
            log.exception("error scraping subreddit", subreddit=sub)

    log.info("scheduled scrape complete")


def main():
    config_loader.start()

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_scrape,
        CronTrigger(hour="*"),
        max_instances=1,
        next_run_time=datetime.now(),  # run immediately on start
        id="scrape",
    )

    log.info("scheduler starting")
    scheduler.start()


if __name__ == "__main__":
    main()
