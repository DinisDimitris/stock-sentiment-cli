"""
Reddit ingestion using PRAW. Monitors relevant subreddits for ticker mentions.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from config.settings import settings
from ingestion.base_source import BaseSource

logger = logging.getLogger(__name__)

SUBREDDIT_CONFIGS = [
    {"subreddit": "stocks", "source_name": "reddit_stocks", "limit": 50},
    {"subreddit": "investing", "source_name": "reddit_stocks", "limit": 50},
    {"subreddit": "valueinvesting", "source_name": "reddit_stocks", "limit": 30},
    {"subreddit": "wallstreetbets", "source_name": "reddit_wsb", "limit": 100},
]


class RedditSource(BaseSource):
    source_name: str  # set per-subreddit in subclasses

    def __init__(self, subreddit: str, source_name: str):
        super().__init__()
        self.subreddit = subreddit
        self.source_name = source_name

    async def fetch(self, ticker: str) -> list[dict[str, Any]]:
        if not (settings.reddit_client_id and settings.reddit_client_secret):
            return []

        try:
            import praw
        except ImportError:
            logger.warning("praw not installed; skipping Reddit")
            return []

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_sync, ticker)

    def _fetch_sync(self, ticker: str) -> list[dict[str, Any]]:
        import praw

        reddit = praw.Reddit(
            client_id=settings.reddit_client_id,
            client_secret=settings.reddit_client_secret,
            user_agent=settings.reddit_user_agent,
        )
        sub = reddit.subreddit(self.subreddit)
        results = []
        search_query = f"${ticker} OR {ticker}"
        for post in sub.search(search_query, sort="new", limit=100, time_filter="week"):
            results.append({
                "_subreddit": self.subreddit,
                "id": post.id,
                "title": post.title,
                "selftext": post.selftext,
                "url": f"https://www.reddit.com{post.permalink}",
                "score": post.score,
                "num_comments": post.num_comments,
                "created_utc": post.created_utc,
                "author": str(post.author),
            })
        return results

    def parse(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        pub_at = None
        if raw_item.get("created_utc"):
            pub_at = datetime.fromtimestamp(raw_item["created_utc"], tz=timezone.utc)

        return {
            "url": raw_item.get("url", ""),
            "title": raw_item.get("title", ""),
            "body": raw_item.get("selftext", ""),
            "published_at": pub_at,
            "source_subtype": "reddit_post",
            "fast_lane": False,
        }


def build_reddit_sources() -> list[RedditSource]:
    return [
        RedditSource(subreddit=cfg["subreddit"], source_name=cfg["source_name"])
        for cfg in SUBREDDIT_CONFIGS
    ]
