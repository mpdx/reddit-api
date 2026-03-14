"""
Playwright scraping logic — ported from scraper/index.js.

Selectors and DOM traversal mirror the original JS exactly.
"""

import time
from datetime import datetime, timezone

import structlog
from playwright.sync_api import sync_playwright, Page, ElementHandle

import publisher

log = structlog.get_logger()

BLOCKED_RESOURCE_TYPES = {"image", "font", "stylesheet", "media"}


def _add_interceptors(page: Page):
    def handle_route(route):
        if route.request.resource_type in BLOCKED_RESOURCE_TYPES:
            route.abort()
        else:
            route.continue_()

    page.route("**/*", handle_route)


def _get_attributes(handle: ElementHandle) -> dict:
    return handle.evaluate(
        """element => {
            const map = {};
            for (const attr of element.attributes) {
                map[attr.name] = attr.value;
            }
            return map;
        }"""
    )


def _parse_comment(element: ElementHandle) -> list:
    """Recursively parse comment tree — mirrors parseComment() in index.js."""
    things = element.query_selector_all("> .sitetable > .thing")
    comments = []

    for thing in things:
        attrs = _get_attributes(thing)
        thing_class = attrs.get("class", "")
        comment_id = attrs.get("data-fullname", "")

        child_el = thing.query_selector(".child")
        children = _parse_comment(child_el) if child_el else []

        is_deleted = "deleted" in thing_class
        is_collapsed = "collapsed" in thing_class
        author = "" if is_deleted else attrs.get("data-author", "")

        try:
            time_val = thing.eval_on_selector("time", "el => el.getAttribute('datetime')")
        except Exception:
            time_val = None

        comment_text = ""
        points = 0

        if not is_deleted:
            try:
                comment_text = thing.eval_on_selector(
                    "div.md", "el => el.innerText.trim()"
                )
            except Exception:
                pass

            try:
                points_text = thing.eval_on_selector(
                    "span.score", "el => el.innerText.trim().split(' ')[0]"
                )
                points = int(points_text)
            except (Exception, ValueError):
                points = 0

        comments.append(
            {
                "id": comment_id,
                "author": author,
                "time": time_val,
                "comment": comment_text,
                "points": points,
                "children": children,
                "isDeleted": is_deleted,
                "isCollapsed": is_collapsed,
            }
        )

    return comments


def _get_post_data(page: Page, post: dict) -> dict:
    """Fetch a single post page and extract all data — mirrors getPostData() in index.js."""
    log.info("getting details for post", post_id=post["id"])

    page.goto(post["url"], wait_until="domcontentloaded")

    # Detect redirect away from old Reddit (e.g. to new.reddit.com)
    if "old.reddit.com" not in page.url:
        log.warning("redirected away from old Reddit, retrying", redirected_to=page.url)
        page.context.add_cookies([
            {"name": "redesign_optout", "value": "true", "domain": ".reddit.com", "path": "/"}
        ])
        page.goto(post["url"], wait_until="domcontentloaded")

    try:
        page.wait_for_selector("div.sitetable", timeout=15_000)
    except Exception:
        log.warning("sitetable not found, backing off and retrying", post_id=post["id"])
        time.sleep(10)
        page.goto(post["url"], wait_until="domcontentloaded")
        page.wait_for_selector("div.sitetable", timeout=30_000)

    sitetable = page.query_selector("div.sitetable")
    thing = sitetable.query_selector(".thing")
    attrs = _get_attributes(thing)

    data_type = attrs.get("data-type", "")
    data_url = attrs.get("data-url", "")
    is_promoted = attrs.get("data-promoted") == "true"
    is_gallery = attrs.get("data-gallery") == "true"

    title = page.eval_on_selector("a.title", "el => el.innerText")

    try:
        points_text = sitetable.eval_on_selector(
            ".score.unvoted", "el => el.innerText"
        )
        points = int(points_text)
    except (Exception, ValueError):
        points = 0

    try:
        text = sitetable.eval_on_selector(
            "div.usertext-body", "el => el.innerText"
        )
    except Exception:
        text = ""

    comments = []
    try:
        comment_area = page.query_selector("div.commentarea")
        if comment_area:
            comments = _parse_comment(comment_area)
    except Exception:
        log.exception("error parsing comments", post_id=post["id"])

    log.info("got details for post", post_id=post["id"])

    return {
        "id": post["id"],
        "subreddit": post["subreddit"],
        "dataType": data_type,
        "dataURL": data_url,
        "isPromoted": is_promoted,
        "isGallery": is_gallery,
        "flair": post.get("flair"),
        "title": title,
        "timestamp": post["dt"],
        "timestamp_millis": post["timestamp"],
        "author": post["author"],
        "url": post["url"],
        "points": points,
        "text": text,
        "comments": comments,
    }


def _get_posts_on_page(page: Page) -> list[dict]:
    """Extract post metadata from a listing page — mirrors getPostsOnPage()."""
    try:
        # Wait up to 15 s for at least one post to appear
        page.wait_for_selector(".thing[data-fullname^='t3_']", timeout=15_000)
    except Exception:
        log.warning("timed out waiting for .thing elements", url=page.url)
        return []

    # Only select link/post things (t3_ = link, t1_ = comment)
    elements = page.query_selector_all(".thing[data-fullname^='t3_']")
    posts = []

    for element in elements:
        attrs = _get_attributes(element)
        post_id = attrs.get("data-fullname", "")
        subreddit = attrs.get("data-subreddit-prefixed", "")
        timestamp_ms = int(attrs.get("data-timestamp", 0))
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
        author = attrs.get("data-author", "")
        permalink = attrs.get("data-permalink", "")
        url = f"https://old.reddit.com{permalink}"

        flair_el = element.query_selector("span.linkflairlabel")
        flair = flair_el.get_attribute("title") if flair_el else None

        posts.append(
            {
                "id": post_id,
                "subreddit": subreddit,
                "dt": dt,
                "timestamp": timestamp_ms,
                "author": author,
                "url": url,
                "flair": flair or None,
            }
        )

    return posts


def scrape_subreddit(subreddit: str, lookback_hours: int = 24):
    """
    Scrape a subreddit's /new/ listing and publish each post to RabbitMQ.
    Mirrors the main() function in index.js.
    """
    log.info("starting scrape", subreddit=subreddit, lookback_hours=lookback_hours)

    cutoff_ms = int(time.time() * 1000) - lookback_hours * 60 * 60 * 1000

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.add_cookies([
            {"name": "redesign_optout", "value": "true", "domain": ".reddit.com", "path": "/"}
        ])
        page = context.new_page()
        _add_interceptors(page)

        url = f"https://old.reddit.com/{subreddit}/new/"
        page.goto(url, wait_until="domcontentloaded")
        log.info("connected to reddit", subreddit=subreddit, actual_url=page.url)

        all_posts: list[dict] = []
        earliest_ts = float("inf")

        while earliest_ts > cutoff_ms:
            page_posts = _get_posts_on_page(page)
            if not page_posts:
                break

            all_posts.extend(page_posts)
            earliest_ts = page_posts[-1]["timestamp"]

            if earliest_ts < cutoff_ms:
                break

            try:
                next_url = page.eval_on_selector(
                    ".next-button a", "el => el.href"
                )
                page.goto(next_url)
            except Exception:
                break

        # Filter to only posts within the lookback window
        all_posts = [p for p in all_posts if p["timestamp"] > cutoff_ms]
        log.info("collected posts", subreddit=subreddit, count=len(all_posts))

        scraped_at = datetime.now(tz=timezone.utc).isoformat()

        consecutive_failures = 0
        for post in all_posts:
            try:
                data = _get_post_data(page, post)
                data["scrapedAt"] = scraped_at
                publisher.publish_one(data)
                consecutive_failures = 0
                time.sleep(2)
            except Exception:
                log.exception("failed to scrape post", post_id=post["id"])
                consecutive_failures += 1
                backoff = min(10 * consecutive_failures, 60)
                log.warning("backing off after failure", seconds=backoff, consecutive=consecutive_failures)
                time.sleep(backoff)

        browser.close()

    log.info("scrape complete", subreddit=subreddit, count=len(all_posts))


def scrape_watched_posts(post_rows: list[dict]):
    if not post_rows:
        log.info("no watched posts to re-scrape")
        return

    log.info("starting viral re-scrape", count=len(post_rows))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.add_cookies([{"name": "redesign_optout", "value": "true", "domain": ".reddit.com", "path": "/"}])
        page = context.new_page()
        _add_interceptors(page)

        scraped_at = datetime.now(tz=timezone.utc).isoformat()
        consecutive_failures = 0

        for row in post_rows:
            raw = row["data"]
            post = {
                "id": raw["id"],
                "url": raw["url"],
                "subreddit": raw["subreddit"],
                "dt": raw["timestamp"],
                "timestamp": raw["timestamp_millis"],
                "author": raw.get("author", ""),
                "flair": raw.get("flair"),
            }
            try:
                data = _get_post_data(page, post)
                data["scrapedAt"] = scraped_at
                publisher.publish_one(data)
                consecutive_failures = 0
                time.sleep(2)
            except Exception:
                log.exception("failed to re-scrape watched post", post_id=post["id"])
                consecutive_failures += 1
                time.sleep(min(10 * consecutive_failures, 60))

        browser.close()

    log.info("viral re-scrape complete", count=len(post_rows))
