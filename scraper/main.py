import structlog
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config_loader
import scraper
import db as scraper_db

log = structlog.get_logger()
_pg_conn = None


def make_tier_job(lookback_hours: int):
    def run():
        subs = config_loader.get_subreddits()
        if not subs:
            log.warning("no subreddits configured, skipping")
            return
        log.info("starting tier scrape", lookback_hours=lookback_hours, subreddits=subs)
        for sub in subs:
            try:
                scraper.scrape_subreddit(sub, lookback_hours=lookback_hours)
            except Exception:
                log.exception("error scraping subreddit", subreddit=sub)
        log.info("tier scrape complete", lookback_hours=lookback_hours)
    return run


def run_viral_rescrape():
    global _pg_conn
    viral = config_loader.get_viral_config()
    if not viral["enabled"]:
        return
    try:
        post_rows, _pg_conn = scraper_db.get_watched_posts(_pg_conn)
        scraper.scrape_watched_posts(post_rows)
    except Exception:
        log.exception("error during viral re-scrape")


def main():
    global _pg_conn
    config_loader.start()
    scheduler = BlockingScheduler()

    for i, tier in enumerate(config_loader.get_tiers()):
        scheduler.add_job(
            make_tier_job(int(tier["lookback_hours"])),
            IntervalTrigger(hours=float(tier["interval_hours"])),
            max_instances=1,
            next_run_time=datetime.now(),
            id=f"scrape_tier_{i}",
        )
        log.info("registered tier", tier=i, **tier)

    viral = config_loader.get_viral_config()
    if viral["enabled"]:
        _pg_conn = scraper_db.get_connection()
        log.info("postgres connected for viral detection")
        scheduler.add_job(
            run_viral_rescrape,
            IntervalTrigger(hours=float(viral["rescrape_interval_hours"])),
            max_instances=1,
            id="viral_rescrape",
        )
        log.info("registered viral re-scrape job", interval_hours=viral["rescrape_interval_hours"])

    log.info("scheduler starting")
    scheduler.start()


if __name__ == "__main__":
    main()
