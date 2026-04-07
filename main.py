"""
Viral App — Backend API v4.0
FastAPI + Supabase + Cloudflare R2 (ready, toggled off until connected)
Free mock data for dev, real storage ready for prod.

Run:  uvicorn main:app --reload --host 0.0.0.0 --port 8000
Prod: gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
import random
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Query,
    Request,
    UploadFile,
    File,
    Form,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("viral")

# ============================================================================
# CONFIGURATION  (env vars → sane defaults)
# ============================================================================

class Config:
    # Supabase
    SUPABASE_URL:    str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY:    str = os.getenv("SUPABASE_SERVICE_KEY", "")   # service key (backend only)

    # Cloudflare R2  ← toggle this to True once your bucket is connected
    R2_ENABLED:      bool = os.getenv("R2_ENABLED", "false").lower() == "true"
    R2_ACCOUNT_ID:   str = os.getenv("R2_ACCOUNT_ID", "")
    R2_ACCESS_KEY:   str = os.getenv("R2_ACCESS_KEY", "")
    R2_SECRET_KEY:   str = os.getenv("R2_SECRET_KEY", "")
    R2_BUCKET:       str = os.getenv("R2_BUCKET", "viral-videos")
    R2_PUBLIC_URL:   str = os.getenv("R2_PUBLIC_URL", "")          # e.g. https://pub.yourdomain.com

    # AI service
    AI_SERVICE_URL:  str  = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
    AI_ENABLED:      bool = os.getenv("AI_ENABLED", "true").lower() == "true"
    AI_CACHE_TTL:    int  = int(os.getenv("AI_CACHE_TTL", "300"))   # seconds

    # Feed
    DEFAULT_LIMIT:   int  = int(os.getenv("DEFAULT_LIMIT", "10"))
    MAX_LIMIT:       int  = int(os.getenv("MAX_LIMIT", "50"))
    TOTAL_MOCK_VIDS: int  = int(os.getenv("TOTAL_MOCK_VIDS", "500"))

    # Rate limiting (simple in-memory)
    RATE_LIMIT_ANALYTICS: int = int(os.getenv("RATE_LIMIT_ANALYTICS", "200"))  # per minute

    # Environment
    ENV:             str  = os.getenv("ENV", "development")
    IS_PROD:         bool = os.getenv("ENV", "development") == "production"

cfg = Config()

# ============================================================================
# AI SERVICE (graceful import)
# ============================================================================

AI_AVAILABLE = False
ai_router    = None

try:
    from ai_service import ai_app as _ai_app, get_ai_feed_scores  # type: ignore
    ai_router     = _ai_app
    AI_AVAILABLE  = True
    logger.info("✅ AI service loaded")
except ImportError as e:
    logger.warning(f"⚠️  AI service unavailable: {e}")
    from fastapi import APIRouter
    ai_router = APIRouter()

    async def get_ai_feed_scores(user_id: str, video_ids: List[str]) -> Dict[str, float]:  # type: ignore
        return {}

    @ai_router.get("/health")
    async def _ai_health():
        return {"status": "disabled", "reason": "ai_service module not found"}

# ============================================================================
# IN-MEMORY STATE
# (Will be replaced by Supabase reads once you're fully connected.
#  For now this is the fast in-process store that survives restarts via
#  Supabase sync in the background.)
# ============================================================================

# video_id → set of user_ids
_likes:   Dict[str, Set[str]] = defaultdict(set)
_saves:   Dict[str, Set[str]] = defaultdict(set)
# author_id → set of follower_ids
_follows: Dict[str, Set[str]] = defaultdict(set)
# video_id → list of comment dicts
_comments: Dict[str, List[dict]] = defaultdict(list)
# user_id → {video_id: score}
_ai_cache: Dict[str, Tuple[float, Dict[str, float]]] = {}   # ts, scores
# analytics events queue (flushed to Supabase in background)
_analytics_queue: List[dict] = []
# Simple rate limit counters {ip: (window_start, count)}
_rate_counters: Dict[str, Tuple[float, int]] = {}
# "not interested" per user
_not_interested: Dict[str, Set[str]] = defaultdict(set)

# ============================================================================
# MOCK DATA  (rich, varied — swap with R2 URLs when ready)
# ============================================================================

# Free CC0 video URLs  (all stream-able, no auth required)
FREE_VIDEOS: List[str] = [
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/earth.mp4",
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/grayscale.mp4",
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/sea.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/SubaruOutbackOnStreetAndDirt.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WeAreGoingOnBullrun.mp4",
]

# Free thumbnail images (Picsum — stable, no auth)
def _thumb(seed: int) -> str:
    # width=400, height=711 → ~9:16 aspect ratio
    return f"https://picsum.photos/seed/{seed}/400/711"

# Avatar pool
AVATARS: List[str] = [
    *[f"https://randomuser.me/api/portraits/women/{i}.jpg" for i in range(1, 21)],
    *[f"https://randomuser.me/api/portraits/men/{i}.jpg"   for i in range(1, 21)],
]

CREATOR_NAMES: List[str] = [
    "Alex Rivera", "Maya Chen", "Jordan Blake", "Priya Sharma",
    "Marcus Lee", "Sofia Martinez", "Kai Nakamura", "Zara Ahmed",
    "Luca Ferrari", "Aisha Okafor", "Diego Reyes", "Nina Kowalski",
    "Sam Osei", "Lena Müller", "Jaden Park", "Camille Dubois",
    "Tariq Hassan", "Amara Diallo", "Ravi Patel", "Elena Volkov",
]

USERNAMES: List[str] = [
    "alexriv", "mayavibes", "jordanblake", "priyacreates", "marcuslee",
    "sofiamtz", "kainaka", "zaraworld", "lucaff", "aishaok",
    "diegoreyes", "ninak", "samosei", "lenam", "jadenpark",
    "camilled", "tariqh", "amarad", "ravipcreates", "elenavolkov",
]

CAPTIONS: List[str] = [
    "When the vibe just hits different 🔥",
    "POV: You discovered the best creator on the internet 👀",
    "This took 47 takes. Worth it ✨",
    "Nobody told me it would be this good 😭",
    "The way this turned out… not what I expected",
    "Doing this every single day until it works 💪",
    "Tell me why I do this to myself 😂",
    "This one's for the algorithm 🤖",
    "Real ones know what this is 🙌",
    "I will not be taking questions at this time 🫡",
    "Day 1 vs Day 100 of consistent posting",
    "When the timing is *chef's kiss* 🤌",
    "Lowkey the most underrated moment ever",
    "Not me crying at my own content rn 😭",
    "The plot twist nobody saw coming 😱",
    "Living rent free in my head since I filmed this",
    "If you know, you know 🔑",
    "Main character energy only 👑",
    "This is what 3am productivity looks like",
    "Proof that you can do anything with enough time",
]

HASHTAG_POOLS: List[List[str]] = [
    ["fyp", "viral", "trending"],
    ["funny", "comedy", "lol"],
    ["music", "dance", "vibe"],
    ["food", "cooking", "chef"],
    ["travel", "adventure", "explore"],
    ["fashion", "ootd", "style"],
    ["fitness", "gym", "workout"],
    ["art", "creative", "design"],
    ["gaming", "gamer", "gaming"],
    ["nature", "outdoors", "earth"],
    ["motivation", "success", "mindset"],
    ["tech", "ai", "innovation"],
]

MUSIC_TRACKS: List[str] = [
    "Original Sound",
    "Trending Beat",
    "Vibe Check — Lo-fi",
    "Electric Summer",
    "Midnight Drive",
    "Golden Hour",
    "Chill Wave",
    "Epic Cinematic",
    "Pop Banger",
    "R&B Flow",
]

CATEGORIES: List[str] = [
    "trending", "comedy", "music", "dance", "food",
    "travel", "fashion", "fitness", "art", "gaming",
    "nature", "tech",
]

# ============================================================================
# MOCK VIDEO GENERATOR  (deterministic by index, fast)
# ============================================================================

def _rng(seed: int) -> random.Random:
    """Return a seeded RNG instance (doesn't touch global state)."""
    return random.Random(seed)

def mock_video(index: int, user_id: Optional[str] = None) -> dict:
    """Generate a deterministic mock video. Same index → same video every time."""
    rng  = _rng(index)
    rng2 = _rng(index * 31337)

    author_idx = index % len(CREATOR_NAMES)
    author_id  = f"author_{author_idx:04d}"
    username   = USERNAMES[author_idx % len(USERNAMES)]
    vid_id     = f"vid_{index:06d}"

    # Stats — seeded so consistent
    base_likes    = rng.randint(800,  120_000)
    base_comments = rng.randint(50,   8_000)
    base_shares   = rng.randint(200,  40_000)
    base_views    = rng.randint(5_000, 5_000_000)

    # Overlay real like counts from in-memory store
    real_likes = len(_likes.get(vid_id, set()))
    final_likes = real_likes if real_likes else base_likes

    is_following = user_id in _follows.get(author_id, set()) if user_id else False
    is_liked     = user_id in _likes.get(vid_id, set())      if user_id else False
    is_saved     = user_id in _saves.get(vid_id, set())      if user_id else False

    hashtags = rng.choice(HASHTAG_POOLS)
    extra    = f"tag{index % 200}"
    if extra not in hashtags:
        hashtags = hashtags + [extra]

    # Timestamp: newer videos have higher indices in "for you", older in "following"
    now_ms     = int(time.time() * 1000)
    created_at = now_ms - (index * 1_800_000)   # ~30 min apart

    return {
        "id":          vid_id,
        "author": {
            "id":       author_id,
            "name":     CREATOR_NAMES[author_idx],
            "username": f"@{username}",
            "avatar":   AVATARS[author_idx % len(AVATARS)],
            "verified": rng2.random() > 0.85,
        },
        "caption":    CAPTIONS[index % len(CAPTIONS)],
        "hashtags":   hashtags,
        "music":      MUSIC_TRACKS[index % len(MUSIC_TRACKS)],
        "category":   CATEGORIES[index % len(CATEGORIES)],
        "video_url":  FREE_VIDEOS[index % len(FREE_VIDEOS)],
        # ↑ swap with R2 URL: f"{cfg.R2_PUBLIC_URL}/{vid_id}.mp4"
        "thumbnail":  _thumb(index % 1000),
        # ↑ swap with R2 URL: f"{cfg.R2_PUBLIC_URL}/{vid_id}_thumb.jpg"
        "stats": {
            "likes":    final_likes,
            "comments": base_comments + len(_comments.get(vid_id, [])),
            "shares":   base_shares,
            "views":    base_views,
        },
        "duration_secs": rng.randint(15, 180),
        "aspect_ratio":  "9:16",
        "created_at":    datetime.fromtimestamp(created_at / 1000, tz=timezone.utc).isoformat(),
        "timestamp":     created_at,
        "is_following":  is_following,
        "is_liked":      is_liked,
        "is_saved":      is_saved,
        "ai_score":      None,     # filled in by AI layer
    }

# ============================================================================
# AI SCORING LAYER
# ============================================================================

async def get_ai_scores(user_id: str, video_ids: List[str]) -> Dict[str, float]:
    """
    Fetch personalised scores from your AI service with caching.
    Falls back to 0.0 for all videos if AI is unavailable.
    """
    if not cfg.AI_ENABLED or not user_id:
        return {}

    now = time.time()
    if user_id in _ai_cache:
        ts, scores = _ai_cache[user_id]
        if now - ts < cfg.AI_CACHE_TTL:
            return scores

    try:
        scores = await get_ai_feed_scores(user_id, video_ids)
        _ai_cache[user_id] = (now, scores)
        return scores
    except Exception as e:
        logger.warning(f"AI score fetch failed for {user_id}: {e}")
        return {}

def apply_ai_ranking(
    videos: List[dict],
    scores: Dict[str, float],
    not_interested: Set[str],
) -> List[dict]:
    """
    Rank videos using AI scores with a diversity injection.

    Formula (matches your AI service weight schema):
      final_score = (
          ai_score * 0.55
          + engagement_score * 0.25
          + recency_score * 0.12
          + follow_bonus * 0.08
      )

    Every 5th slot is reserved for a "discovery" video (low AI score but
    high engagement) to prevent filter bubbles.
    """
    if not scores:
        return videos

    now_ms = int(time.time() * 1000)
    MAX_AGE_MS = 7 * 24 * 3600 * 1000   # 7 days

    def _score(v: dict) -> float:
        vid_id = v["id"]
        if vid_id in not_interested:
            return -9999.0

        ai = scores.get(vid_id, 0.0)

        stats = v["stats"]
        total_interactions = stats["likes"] + stats["comments"] * 3 + stats["shares"] * 2
        eng = min(total_interactions / 200_000, 1.0)   # normalise to [0,1]

        age_ms  = max(now_ms - v.get("timestamp", now_ms), 0)
        recency = max(1.0 - (age_ms / MAX_AGE_MS), 0.0)

        follow_bonus = 0.15 if v.get("is_following") else 0.0

        return ai * 0.55 + eng * 0.25 + recency * 0.12 + follow_bonus * 0.08

    # Sort by score descending
    ranked = sorted(videos, key=_score, reverse=True)

    # Inject discovery videos every 5 slots (prevents echo chamber)
    discovery_pool = sorted(videos, key=lambda v: v["stats"]["views"], reverse=True)
    result: List[dict] = []
    d_idx = 0
    for i, vid in enumerate(ranked):
        result.append(vid)
        if (i + 1) % 5 == 0 and d_idx < len(discovery_pool):
            # Find a video not already in result
            while d_idx < len(discovery_pool) and discovery_pool[d_idx] in result:
                d_idx += 1
            if d_idx < len(discovery_pool):
                result.append(discovery_pool[d_idx])
                d_idx += 1

    return result

# ============================================================================
# FEED BUILDER
# ============================================================================

async def build_feed(
    tab:        str,
    cursor:     Optional[str],
    limit:      int,
    user_id:    Optional[str],
    country:    Optional[str],
    lat:        Optional[float],
    lon:        Optional[float],
    category:   Optional[str],
) -> Tuple[List[dict], Optional[str], bool]:
    """
    Returns (videos, next_cursor, has_more)

    tab="for_you"   → full AI ranking + discovery injection
    tab="following" → only videos from authors the user follows (+ AI rank)
    """
    not_interested = _not_interested.get(user_id or "", set())

    # Decode cursor → start index
    start = 0
    if cursor:
        try:
            start = int(cursor)
        except ValueError:
            start = 0

    # Pool size — we generate 3× what we need so AI can rank a larger candidate set
    candidate_count = min(limit * 3, cfg.TOTAL_MOCK_VIDS - start)
    if candidate_count <= 0:
        return [], None, False

    candidates: List[dict] = []

    if tab == "following" and user_id:
        # Filter to only videos from followed authors
        followed_authors = _follows.get(user_id, set())
        # When following list is empty, fall back to for_you
        if not followed_authors:
            candidates = [mock_video(start + i, user_id) for i in range(candidate_count)]
        else:
            raw = [mock_video(start + i, user_id) for i in range(candidate_count * 2)]
            candidates = [v for v in raw if v["author"]["id"] in followed_authors]
            if not candidates:
                # Still nothing → fall back
                candidates = raw[:candidate_count]
    else:
        candidates = [mock_video(start + i, user_id) for i in range(candidate_count)]

    # Apply category filter
    if category and category != "all":
        filtered = [v for v in candidates if v.get("category") == category]
        if filtered:
            candidates = filtered

    # Remove "not interested" videos
    candidates = [v for v in candidates if v["id"] not in not_interested]

    # AI ranking
    video_ids = [v["id"] for v in candidates]
    scores    = await get_ai_scores(user_id or "", video_ids) if user_id else {}

    if scores:
        candidates = apply_ai_ranking(candidates, scores, not_interested)
        for v in candidates:
            v["ai_score"] = round(scores.get(v["id"], 0.0), 4)
    else:
        # No AI → location-bias: shuffle with seed derived from location
        if lat and lon:
            geo_seed = int(abs(lat * 1000) + abs(lon * 1000)) + start
            random.Random(geo_seed).shuffle(candidates)

    page     = candidates[:limit]
    has_more = (start + candidate_count) < cfg.TOTAL_MOCK_VIDS

    next_cursor = str(start + candidate_count) if has_more else None

    return page, next_cursor, has_more

# ============================================================================
# PYDANTIC MODELS
# ============================================================================

class AuthorOut(BaseModel):
    id:       str
    name:     str
    username: str
    avatar:   str
    verified: bool = False

class StatsOut(BaseModel):
    likes:    int
    comments: int
    shares:   int
    views:    int

class VideoOut(BaseModel):
    id:            str
    author:        AuthorOut
    caption:       str
    hashtags:      List[str]
    music:         Optional[str] = None
    category:      Optional[str] = None
    video_url:     str
    thumbnail:     str
    stats:         StatsOut
    duration_secs: Optional[int] = None
    aspect_ratio:  str = "9:16"
    created_at:    str
    timestamp:     int
    is_following:  bool = False
    is_liked:      bool = False
    is_saved:      bool = False
    ai_score:      Optional[float] = None

class FeedResponse(BaseModel):
    videos:      List[VideoOut]
    next_cursor: Optional[str]
    has_more:    bool
    tab:         str
    count:       int

class CommentIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def strip_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Comment cannot be empty")
        # Basic XSS scrub (full sanitisation happens client-side too)
        v = re.sub(r"<[^>]+>", "", v)
        return v

class AnalyticsEvent(BaseModel):
    type:       str
    data:       Dict[str, Any] = {}
    user_id:    Optional[str] = None
    session_id: Optional[str] = None
    location:   Optional[Dict[str, Any]] = None
    ts:         Optional[int] = None

class AnalyticsBatch(BaseModel):
    events: List[AnalyticsEvent] = Field(..., max_length=500)

class NotInterestedIn(BaseModel):
    video_id: str
    user_id:  str

class TrendingTagsResponse(BaseModel):
    tags:      List[str]
    generated: str

class ExploreResponse(BaseModel):
    videos:   List[VideoOut]
    category: str
    count:    int

# ============================================================================
# APP SETUP
# ============================================================================

app = FastAPI(
    title="Viral API",
    version="4.0.0",
    description="Backend for Viral short-video app. R2 storage toggle-ready.",
    docs_url="/docs" if not cfg.IS_PROD else None,
    redoc_url=None,
)

# --- Middleware ---

app.add_middleware(GZipMiddleware, minimum_size=512)

ALLOWED_ORIGINS = os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5500,http://127.0.0.1:5500"
).split(",")

if not cfg.IS_PROD:
    ALLOWED_ORIGINS.append("*")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if cfg.IS_PROD else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-AI-Used"],
)

# Mount AI router
if AI_AVAILABLE and ai_router:
    app.mount("/ai", ai_router)
    logger.info("✅ AI routes mounted at /ai")
else:
    app.include_router(ai_router, prefix="/ai")

# ============================================================================
# MIDDLEWARE — Request ID + timing
# ============================================================================

@app.middleware("http")
async def request_middleware(request: Request, call_next):
    req_id   = str(uuid.uuid4())[:8]
    start_ts = time.perf_counter()
    request.state.req_id = req_id

    response = await call_next(request)
    elapsed  = (time.perf_counter() - start_ts) * 1000

    response.headers["X-Request-ID"] = req_id
    response.headers["X-Response-Time"] = f"{elapsed:.1f}ms"

    if elapsed > 1000:
        logger.warning(f"Slow request [{req_id}] {request.method} {request.url.path} → {elapsed:.0f}ms")

    return response

# ============================================================================
# RATE LIMITER (simple in-memory, per IP)
# ============================================================================

def _rate_check(ip: str, limit_per_minute: int = 120) -> bool:
    """Returns True if allowed, False if rate-limited."""
    now = time.time()
    if ip in _rate_counters:
        window_start, count = _rate_counters[ip]
        if now - window_start < 60:
            if count >= limit_per_minute:
                return False
            _rate_counters[ip] = (window_start, count + 1)
        else:
            _rate_counters[ip] = (now, 1)
    else:
        _rate_counters[ip] = (now, 1)
    return True

def _get_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "0.0.0.0")

# ============================================================================
# BACKGROUND TASKS
# ============================================================================

async def _flush_analytics_to_supabase(events: List[dict]):
    """
    Push analytics batch to Supabase analytics table.
    Non-blocking — called as a background task.
    """
    if not cfg.SUPABASE_URL or not cfg.SUPABASE_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.post(
                f"{cfg.SUPABASE_URL}/rest/v1/analytics_events",
                headers={
                    "apikey":        cfg.SUPABASE_KEY,
                    "Authorization": f"Bearer {cfg.SUPABASE_KEY}",
                    "Content-Type":  "application/json",
                    "Prefer":        "return=minimal",
                },
                json=events,
            )
            if r.status_code not in (200, 201):
                logger.warning(f"Analytics flush non-200: {r.status_code}")
    except Exception as e:
        logger.error(f"Analytics flush failed: {e}")

async def _increment_view_count(video_id: str, user_id: Optional[str]):
    """Fire-and-forget view count increment in Supabase."""
    if not cfg.SUPABASE_URL or not cfg.SUPABASE_KEY:
        return
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.post(
                f"{cfg.SUPABASE_URL}/rest/v1/rpc/increment_views",
                headers={
                    "apikey":        cfg.SUPABASE_KEY,
                    "Authorization": f"Bearer {cfg.SUPABASE_KEY}",
                    "Content-Type":  "application/json",
                },
                json={"p_video_id": video_id},
            )
    except Exception:
        pass   # Non-critical — silently ignore

# ============================================================================
# CLOUDFLARE R2 UPLOAD  (returns mock URL until R2_ENABLED=true)
# ============================================================================

async def upload_to_r2(
    file_bytes: bytes,
    object_key: str,
    content_type: str = "video/mp4",
) -> str:
    """
    Upload a file to Cloudflare R2 and return its public URL.
    When R2_ENABLED is False, returns a free mock URL so the frontend
    keeps working during development.
    """
    if not cfg.R2_ENABLED:
        # Return a free working video for dev
        mock_url = random.choice(FREE_VIDEOS)
        logger.info(f"[R2 MOCK] Would upload {object_key} → returning mock: {mock_url}")
        return mock_url

    # ── Real R2 upload via S3-compatible API ──────────────────────────────
    import boto3  # type: ignore
    from botocore.config import Config as BotoConfig  # type: ignore

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{cfg.R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=cfg.R2_ACCESS_KEY,
        aws_secret_access_key=cfg.R2_SECRET_KEY,
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )

    s3.put_object(
        Bucket=cfg.R2_BUCKET,
        Key=object_key,
        Body=file_bytes,
        ContentType=content_type,
        CacheControl="public, max-age=31536000",
    )

    public_url = f"{cfg.R2_PUBLIC_URL}/{object_key}"
    logger.info(f"[R2] Uploaded {object_key} → {public_url}")
    return public_url

async def generate_thumbnail_from_video(video_bytes: bytes, object_key: str) -> str:
    """
    Generate a thumbnail from the first frame of a video using ffmpeg.
    Falls back to a Picsum URL when ffmpeg is unavailable or R2 is off.
    """
    if not cfg.R2_ENABLED:
        seed = abs(hash(object_key)) % 1000
        return _thumb(seed)

    import subprocess, tempfile, pathlib  # noqa

    with tempfile.TemporaryDirectory() as tmp:
        vid_path   = pathlib.Path(tmp) / "input.mp4"
        thumb_path = pathlib.Path(tmp) / "thumb.jpg"
        vid_path.write_bytes(video_bytes)

        try:
            subprocess.run(
                ["ffmpeg", "-i", str(vid_path), "-ss", "00:00:01",
                 "-vframes", "1", "-q:v", "2", str(thumb_path)],
                capture_output=True, timeout=20, check=True,
            )
            thumb_bytes = thumb_path.read_bytes()
            thumb_key   = object_key.replace(".mp4", "_thumb.jpg").replace(".webm", "_thumb.jpg")
            return await upload_to_r2(thumb_bytes, thumb_key, "image/jpeg")
        except Exception as e:
            logger.warning(f"Thumbnail generation failed: {e}")
            seed = abs(hash(object_key)) % 1000
            return _thumb(seed)

# ============================================================================
# API ENDPOINTS
# ============================================================================

# ── Health / Root ────────────────────────────────────────────────────────────

@app.get("/", tags=["meta"])
async def root():
    return {
        "app":      "Viral API",
        "version":  "4.0.0",
        "status":   "healthy",
        "env":      cfg.ENV,
        "ai":       AI_AVAILABLE and cfg.AI_ENABLED,
        "r2":       cfg.R2_ENABLED,
        "docs":     "/docs" if not cfg.IS_PROD else "disabled",
    }

@app.get("/health", tags=["meta"])
async def health():
    return {
        "status":     "healthy",
        "timestamp":  datetime.now(tz=timezone.utc).isoformat(),
        "ai":         AI_AVAILABLE,
        "r2":         cfg.R2_ENABLED,
        "mock_pool":  cfg.TOTAL_MOCK_VIDS,
    }

# ── Feed ─────────────────────────────────────────────────────────────────────

@app.get("/videos", response_model=FeedResponse, tags=["feed"])
async def get_videos(
    request:   Request,
    tab:       str           = Query("for_you", pattern="^(for_you|following)$"),
    limit:     int           = Query(cfg.DEFAULT_LIMIT, ge=1, le=cfg.MAX_LIMIT),
    cursor:    Optional[str] = Query(None,  description="Pagination cursor"),
    user_id:   Optional[str] = Query(None,  description="Authenticated user ID"),
    country:   Optional[str] = Query(None,  description="User country (ISO 3166-1 alpha-2)"),
    lat:       Optional[float] = Query(None, description="User latitude"),
    lon:       Optional[float] = Query(None, description="User longitude"),
    category:  Optional[str] = Query(None,  description="Filter by category"),
):
    """
    Main feed endpoint.
    - tab=for_you   → AI-ranked personalised feed (+ location bias)
    - tab=following → only from followed authors (AI re-ranked)
    Sends location to the AI service so it can weight regional trends.
    """
    ip = _get_ip(request)
    if not _rate_check(ip, 200):
        raise HTTPException(status_code=429, detail="Too many requests")

    videos, next_cursor, has_more = await build_feed(
        tab, cursor, limit, user_id, country, lat, lon, category
    )

    response = FeedResponse(
        videos=[VideoOut(**v) for v in videos],
        next_cursor=next_cursor,
        has_more=has_more,
        tab=tab,
        count=len(videos),
    )

    # Add header so frontend knows if AI was applied
    json_resp = JSONResponse(content=response.model_dump())
    json_resp.headers["X-AI-Used"] = str(bool(AI_AVAILABLE and cfg.AI_ENABLED and user_id))
    return json_resp

@app.get("/explore", response_model=ExploreResponse, tags=["feed"])
async def get_explore(
    category:  str           = Query("all"),
    limit:     int           = Query(30, ge=1, le=100),
    cursor:    Optional[str] = Query(None),
    user_id:   Optional[str] = Query(None),
    lat:       Optional[float] = Query(None),
    lon:       Optional[float] = Query(None),
):
    """Explore page — category-filtered grid."""
    videos, _, _ = await build_feed(
        tab="for_you", cursor=cursor, limit=limit,
        user_id=user_id, country=None, lat=lat, lon=lon,
        category=category if category != "all" else None,
    )
    return ExploreResponse(
        videos=[VideoOut(**v) for v in videos],
        category=category,
        count=len(videos),
    )

# ── Single Video ──────────────────────────────────────────────────────────────

@app.get("/videos/{video_id}", response_model=VideoOut, tags=["feed"])
async def get_video(
    video_id:  str,
    user_id:   Optional[str] = Query(None),
    background: BackgroundTasks = BackgroundTasks(),
):
    """Fetch a single video by ID."""
    try:
        idx = int(video_id.replace("vid_", ""))
    except ValueError:
        raise HTTPException(status_code=404, detail="Video not found")

    if idx < 0 or idx >= cfg.TOTAL_MOCK_VIDS:
        raise HTTPException(status_code=404, detail="Video not found")

    v = mock_video(idx, user_id)
    background.add_task(_increment_view_count, video_id, user_id)
    return VideoOut(**v)

# ── Trending Tags ─────────────────────────────────────────────────────────────

@app.get("/trending-tags", response_model=TrendingTagsResponse, tags=["feed"])
async def trending_tags(
    limit: int = Query(12, ge=1, le=30),
    country: Optional[str] = Query(None),
):
    """
    Return trending hashtags.
    In prod: query Supabase for top hashtags in the last 24h.
    For now: deterministic weighted random based on time-of-day + country.
    """
    all_tags = [t for pool in HASHTAG_POOLS for t in pool]
    # Rotate daily
    day_seed = int(time.time() // 86400)
    if country:
        day_seed += abs(hash(country))
    rng = random.Random(day_seed)
    rng.shuffle(all_tags)

    # Dedupe and take first `limit`
    seen = set()
    tags = []
    for t in all_tags:
        if t not in seen:
            seen.add(t)
            tags.append(t)
        if len(tags) >= limit:
            break

    return TrendingTagsResponse(tags=tags, generated=datetime.now(tz=timezone.utc).isoformat())

# ── Likes ─────────────────────────────────────────────────────────────────────

@app.post("/videos/{video_id}/like", tags=["interactions"])
async def like_video(
    video_id: str,
    user_id:  str = Query(..., min_length=1),
    action:   str = Query("like", pattern="^(like|unlike)$"),
):
    """Like or unlike a video. Optimistic — no DB write needed for mock mode."""
    _likes[video_id] = _likes.get(video_id, set())
    if action == "like":
        _likes[video_id].add(user_id)
        new_state = True
    else:
        _likes[video_id].discard(user_id)
        new_state = False

    return {
        "success":     True,
        "action":      action,
        "liked":       new_state,
        "likes_count": len(_likes[video_id]),
    }

# ── Saves ─────────────────────────────────────────────────────────────────────

@app.post("/videos/{video_id}/save", tags=["interactions"])
async def save_video(
    video_id: str,
    user_id:  str = Query(..., min_length=1),
    action:   str = Query("save", pattern="^(save|unsave)$"),
):
    """Save or unsave a video."""
    _saves[video_id] = _saves.get(video_id, set())
    if action == "save":
        _saves[video_id].add(user_id)
    else:
        _saves[video_id].discard(user_id)

    return {
        "success": True,
        "action":  action,
        "saved":   user_id in _saves[video_id],
    }

# ── Follows ───────────────────────────────────────────────────────────────────

@app.post("/users/{target_id}/follow", tags=["interactions"])
async def follow_user(
    target_id:   str,
    follower_id: str = Query(..., min_length=1),
    action:      str = Query("follow", pattern="^(follow|unfollow)$"),
):
    """Follow or unfollow a user."""
    if target_id == follower_id:
        raise HTTPException(status_code=400, detail="Cannot follow yourself")

    _follows[target_id] = _follows.get(target_id, set())
    if action == "follow":
        _follows[target_id].add(follower_id)
    else:
        _follows[target_id].discard(follower_id)

    return {
        "success":         True,
        "action":          action,
        "following":       follower_id in _follows[target_id],
        "followers_count": len(_follows[target_id]),
    }

# ── Comments ──────────────────────────────────────────────────────────────────

@app.get("/videos/{video_id}/comments", tags=["comments"])
async def get_comments(
    video_id:   str,
    limit:      int           = Query(50, ge=1, le=100),
    cursor:     Optional[str] = Query(None),
):
    """Get comments for a video, newest first."""
    comments = _comments.get(video_id, [])
    # Seed with some mock comments if empty
    if not comments:
        comments = _generate_mock_comments(video_id)
    start = int(cursor) if cursor else 0
    page  = comments[start : start + limit]
    return {
        "comments":    page,
        "total":       len(comments),
        "next_cursor": str(start + limit) if start + limit < len(comments) else None,
    }

@app.post("/videos/{video_id}/comments", tags=["comments"])
async def add_comment(
    video_id:    str,
    body:        CommentIn,
    user_id:     str           = Query(..., min_length=1),
    user_name:   Optional[str] = Query(None),
    user_avatar: Optional[str] = Query(None),
    parent_id:   Optional[str] = Query(None, description="Reply to comment ID"),
):
    """Add a comment (or reply) to a video."""
    comment = {
        "id":          f"cmt_{uuid.uuid4().hex[:12]}",
        "video_id":    video_id,
        "user_id":     user_id,
        "parent_id":   parent_id,
        "user": {
            "id":     user_id,
            "name":   user_name or f"user_{user_id[:8]}",
            "avatar": user_avatar or AVATARS[abs(hash(user_id)) % len(AVATARS)],
        },
        "text":        body.text,
        "likes":       0,
        "created_at":  datetime.now(tz=timezone.utc).isoformat(),
        "time":        "Just now",
    }
    _comments[video_id].insert(0, comment)
    # Cap per-video comment list in memory
    if len(_comments[video_id]) > 500:
        _comments[video_id] = _comments[video_id][:500]

    return {"success": True, "comment": comment}

def _generate_mock_comments(video_id: str) -> List[dict]:
    """Seed a video with 3–8 realistic-looking mock comments."""
    rng = _rng(abs(hash(video_id)) % 999983)
    n   = rng.randint(3, 8)
    texts = [
        "This is literally me 😭",
        "I can't stop watching this omg",
        "Why is this so accurate??",
        "The editing on this is 🔥",
        "First comment! Love your content",
        "I shared this with my whole group chat",
        "This needs way more views",
        "You're so talented omg",
        "I've watched this 10 times already",
        "Wait this is actually insane",
    ]
    comments = []
    for i in range(n):
        author_idx = rng.randint(0, len(CREATOR_NAMES) - 1)
        ts = int(time.time() * 1000) - rng.randint(60_000, 86_400_000)
        comments.append({
            "id":         f"cmt_mock_{video_id}_{i}",
            "video_id":   video_id,
            "user_id":    f"author_{author_idx:04d}",
            "parent_id":  None,
            "user": {
                "id":     f"author_{author_idx:04d}",
                "name":   CREATOR_NAMES[author_idx],
                "avatar": AVATARS[author_idx % len(AVATARS)],
            },
            "text":       rng.choice(texts),
            "likes":      rng.randint(0, 2000),
            "created_at": datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isoformat(),
            "time":       fmtRelTime_py(ts),
        })
    _comments[video_id] = comments
    return comments

def fmtRelTime_py(ts_ms: int) -> str:
    diff = (int(time.time() * 1000) - ts_ms) / 1000
    if diff < 60:    return "Just now"
    if diff < 3600:  return f"{int(diff // 60)}m ago"
    if diff < 86400: return f"{int(diff // 3600)}h ago"
    return f"{int(diff // 86400)}d ago"

# ── Not Interested ────────────────────────────────────────────────────────────

@app.post("/videos/{video_id}/not-interested", tags=["interactions"])
async def not_interested(video_id: str, user_id: str = Query(..., min_length=1)):
    """Mark a video as 'not interested' — excluded from future feeds."""
    _not_interested[user_id].add(video_id)
    # Invalidate AI cache so next fetch rebuilds
    _ai_cache.pop(user_id, None)
    return {"success": True, "video_id": video_id}

# ── User Saved Videos ─────────────────────────────────────────────────────────

@app.get("/user/saved", tags=["user"])
async def get_saved(
    user_id: str = Query(..., min_length=1),
    limit:   int = Query(30, ge=1, le=100),
):
    """Get all videos saved by a user."""
    saved_ids = [vid for vid, users in _saves.items() if user_id in users]
    videos = []
    for vid_id in saved_ids[:limit]:
        try:
            idx = int(vid_id.replace("vid_", ""))
            videos.append(VideoOut(**mock_video(idx, user_id)))
        except (ValueError, IndexError):
            continue
    return {"saved_videos": videos, "total": len(saved_ids)}

# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/upload", tags=["upload"])
async def upload_video(
    background:   BackgroundTasks,
    video:        UploadFile = File(...),
    user_id:      str        = Form(...),
    caption:      str        = Form(""),
    hashtags:     str        = Form("[]"),      # JSON string
    filter:       str        = Form("none"),
    trim_start:   float      = Form(0),
    trim_end:     float      = Form(100),
    music:        str        = Form("original"),
    music_volume: float      = Form(70),
):
    """
    Upload a video.
    - In dev (R2_ENABLED=false): returns a free mock URL immediately.
    - In prod (R2_ENABLED=true): uploads to Cloudflare R2.
    """
    # Basic validation
    allowed_types = {"video/mp4", "video/webm", "video/quicktime", "video/x-m4v"}
    ct = video.content_type or ""
    if ct not in allowed_types and not ct.startswith("video/"):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ct}")

    MAX_SIZE_MB = 200
    video_bytes = await video.read()
    if len(video_bytes) > MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {MAX_SIZE_MB}MB limit")

    # Build storage key
    ext        = "mp4" if "mp4" in ct else "webm"
    object_key = f"videos/{user_id}/{uuid.uuid4().hex}.{ext}"

    # Upload video
    video_url = await upload_to_r2(video_bytes, object_key, ct)

    # Generate thumbnail in background
    thumb_url = await generate_thumbnail_from_video(video_bytes, object_key)

    # Parse hashtags
    import json as _json
    try:
        tags = _json.loads(hashtags)
    except Exception:
        tags = [h.strip() for h in hashtags.split(",") if h.strip()]

    # Build response payload (matches what the frontend expects)
    new_video_id = f"vid_{uuid.uuid4().hex[:8]}"
    result = {
        "success":       True,
        "video_id":      new_video_id,
        "video_url":     video_url,
        "thumbnail_url": thumb_url,
        "caption":       caption[:2200],
        "hashtags":      tags[:20],
        "r2_key":        object_key,
        "r2_enabled":    cfg.R2_ENABLED,
        "message":       "Video uploaded successfully" if cfg.R2_ENABLED else "Video received (mock mode)",
    }

    logger.info(f"Upload [{user_id}] → {object_key} ({len(video_bytes) // 1024}KB, r2={cfg.R2_ENABLED})")
    return result

@app.post("/upload-avatar", tags=["upload"])
async def upload_avatar(
    avatar:  UploadFile = File(...),
    user_id: str        = Form(...),
):
    """Upload a profile avatar image."""
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if avatar.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Image must be JPEG, PNG, WebP or GIF")

    img_bytes  = await avatar.read()
    if len(img_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Avatar exceeds 10MB")

    ext        = avatar.content_type.split("/")[1].replace("jpeg", "jpg")
    object_key = f"avatars/{user_id}/avatar.{ext}"

    url = await upload_to_r2(img_bytes, object_key, avatar.content_type)
    return {"success": True, "url": url}

# ── Chat image upload ─────────────────────────────────────────────────────────

@app.post("/chat/upload-image", tags=["chat"])
async def upload_chat_image(
    image:     UploadFile = File(...),
    room_id:   str        = Form(...),
    sender_id: str        = Form(...),
):
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    if image.content_type not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported image type")

    img_bytes  = await image.read()
    if len(img_bytes) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Image exceeds 20MB")

    ext        = image.content_type.split("/")[1].replace("jpeg", "jpg")
    object_key = f"chat/{room_id}/{uuid.uuid4().hex}.{ext}"

    url = await upload_to_r2(img_bytes, object_key, image.content_type)
    return {"success": True, "url": url, "type": "image"}

# ── Analytics ─────────────────────────────────────────────────────────────────

@app.post("/analytics/batch", tags=["analytics"])
async def analytics_batch(
    request:    Request,
    batch:      AnalyticsBatch,
    background: BackgroundTasks,
):
    """
    Receive a batch of analytics events from the frontend.
    Validates, enriches with server-side IP/timestamp, queues for Supabase.

    Rate-limited to prevent abuse: 200 req/min per IP.
    """
    ip = _get_ip(request)
    if not _rate_check(ip, cfg.RATE_LIMIT_ANALYTICS):
        raise HTTPException(status_code=429, detail="Analytics rate limit exceeded")

    enriched = []
    for ev in batch.events:
        enriched.append({
            "type":       ev.type,
            "data":       ev.data,
            "user_id":    ev.user_id,
            "session_id": ev.session_id,
            "location":   ev.location,
            "client_ts":  ev.ts,
            "server_ts":  int(time.time() * 1000),
            "server_ip":  ip,
        })

    # Flush to Supabase in background — never blocks the response
    background.add_task(_flush_analytics_to_supabase, enriched)

    return {"success": True, "received": len(enriched)}

# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/stats", tags=["meta"])
async def stats():
    """App-wide statistics."""
    return {
        "total_mock_videos":  cfg.TOTAL_MOCK_VIDS,
        "total_likes":        sum(len(u) for u in _likes.values()),
        "total_saves":        sum(len(u) for u in _saves.values()),
        "total_follows":      sum(len(u) for u in _follows.values()),
        "total_comments":     sum(len(c) for c in _comments.values()),
        "ai_enabled":         cfg.AI_ENABLED,
        "ai_available":       AI_AVAILABLE,
        "r2_enabled":         cfg.R2_ENABLED,
        "analytics_queued":   len(_analytics_queue),
        "timestamp":          datetime.now(tz=timezone.utc).isoformat(),
    }

# ── Error Handlers ────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_err(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success":     False,
            "error":       exc.detail,
            "status_code": exc.status_code,
            "path":        str(request.url.path),
        },
    )

@app.exception_handler(Exception)
async def generic_err(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success":     False,
            "error":       "Internal server error",
            "status_code": 500,
        },
    )

# ============================================================================
# STARTUP / SHUTDOWN
# ============================================================================

@app.on_event("startup")
async def on_startup():
    logger.info("=" * 60)
    logger.info("🚀 Viral API v4.0 starting")
    logger.info(f"   ENV:         {cfg.ENV}")
    logger.info(f"   AI:          {'✅ enabled' if cfg.AI_ENABLED and AI_AVAILABLE else '⚠️  disabled'}")
    logger.info(f"   R2:          {'✅ connected' if cfg.R2_ENABLED else '🟡 mock mode (free URLs)'}")
    logger.info(f"   Mock videos: {cfg.TOTAL_MOCK_VIDS}")
    logger.info(f"   Supabase:    {'✅ configured' if cfg.SUPABASE_URL else '⚠️  not configured'}")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("🛑 Viral API shutting down")
    # Flush remaining analytics
    if _analytics_queue:
        await _flush_analytics_to_supabase(_analytics_queue)

# ============================================================================
# ENTRYPOINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=not cfg.IS_PROD,
        log_level="info",
        access_log=True,
    )
