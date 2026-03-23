"""
Viral App - Backend API with AI Integration
"""

import time
import random
import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Set
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ============================================================================
# Configuration
# ============================================================================

TOTAL_VIDEOS = 10000
VIDEOS_PER_PAGE = 10
AI_SERVICE_ENABLED = True

logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Models
# ============================================================================

class Author(BaseModel):
    id: str
    name: str
    avatar: str

class Stats(BaseModel):
    likes: int
    comments: int
    shares: int

class Video(BaseModel):
    id: str
    author: Author
    caption: str
    hashtags: List[str]
    video_url: str
    thumbnail: str
    stats: Stats
    timestamp: int
    is_following: bool = False
    ai_score: Optional[float] = None

class PaginatedResponse(BaseModel):
    videos: List[Video]
    next_cursor: Optional[str]
    has_more: bool

class CommentUser(BaseModel):
    name: str
    avatar: str

class Comment(BaseModel):
    id: str
    user: CommentUser
    text: str
    likes: int
    time: str

class CommentCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)

class LikeAction(BaseModel):
    action: str

class SaveAction(BaseModel):
    action: str

class FollowAction(BaseModel):
    action: str

# ============================================================================
# Storage
# ============================================================================

likes_storage: Dict[str, Set[str]] = {}
saves_storage: Dict[str, Set[str]] = {}
follows_storage: Dict[str, Set[str]] = {}
comments_storage: Dict[str, List[Comment]] = {}

# Cache for AI-scored videos
ai_score_cache: Dict[str, Dict[str, float]] = {}
ai_score_cache_timestamp: Dict[str, float] = {}
AI_CACHE_TTL = 300

# ============================================================================
# App Setup
# ============================================================================

app = FastAPI(title="Viral API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# AI Service Import and Mount (AFTER app is created)
# ============================================================================

try:
    from ai_service import ai_app
    app.mount("/ai", ai_app)
    print("✅ AI Service loaded and mounted at /ai")
    AI_SERVICE_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ AI Service not available: {e}")
    AI_SERVICE_AVAILABLE = False
    
    # Create fallback AI endpoints
    @app.get("/ai/health")
    async def ai_health_fallback():
        return {"status": "disabled", "message": "AI service not available"}
    
    @app.post("/ai/batch")
    async def ai_batch_fallback():
        return {"status": "disabled", "message": "AI service not available"}

# ============================================================================
# Video Data (Mock)
# ============================================================================

VIDEO_POOL = [
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerMeltdowns.mp4",
]

CAPTIONS = [
    "Check this out! 🔥",
    "This is amazing! ✨",
    "You won't believe this! 😱",
    "Best moment ever! 🎉",
    "Can't stop watching! 👀",
]

AUTHOR_NAMES = [
    "@tiktok_star", "@viral_creator", "@trending_now", "@daily_vibes", "@content_king",
]

AUTHOR_AVATARS = [
    "https://randomuser.me/api/portraits/women/1.jpg",
    "https://randomuser.me/api/portraits/men/2.jpg",
    "https://randomuser.me/api/portraits/women/3.jpg",
    "https://randomuser.me/api/portraits/men/4.jpg",
    "https://randomuser.me/api/portraits/women/5.jpg",
]

def generate_author(index: int) -> Author:
    author_index = index % len(AUTHOR_NAMES)
    return Author(
        id=f"author_{author_index:03d}",
        name=AUTHOR_NAMES[author_index],
        avatar=AUTHOR_AVATARS[author_index]
    )

def generate_video(index: int, current_user_id: Optional[str] = None, ai_score: Optional[float] = None) -> dict:
    current_time = int(time.time() * 1000)
    timestamp = current_time - (index * 3600000)
    
    random.seed(index)
    author = generate_author(index)
    
    is_following = False
    if current_user_id:
        is_following = current_user_id in follows_storage.get(author.id, set())
    
    video = {
        "id": f"{timestamp}_{index:05d}",
        "author": author.dict(),
        "caption": CAPTIONS[index % len(CAPTIONS)],
        "hashtags": ["fyp", "viral", f"tag{index % 100}"][:3],
        "video_url": VIDEO_POOL[index % len(VIDEO_POOL)],
        "thumbnail": f"https://picsum.photos/400/800?random={index}",
        "stats": {
            "likes": random.randint(1000, 50000),
            "comments": random.randint(100, 5000),
            "shares": random.randint(500, 20000)
        },
        "timestamp": timestamp,
        "is_following": is_following,
        "ai_score": ai_score
    }
    
    video_id = video["id"]
    if video_id in likes_storage:
        video["stats"]["likes"] = len(likes_storage[video_id])
    
    random.seed()
    return video

# ============================================================================
# AI Score Fetching (Fixed Event Loop Issue)
# ============================================================================

async def fetch_ai_scores_async(user_id: str) -> Dict[str, float]:
    """Async version of AI score fetching"""
    if not AI_SERVICE_ENABLED or not AI_SERVICE_AVAILABLE:
        return {}
    
    # Check cache
    now = time.time()
    if user_id in ai_score_cache_timestamp:
        if now - ai_score_cache_timestamp[user_id] < AI_CACHE_TTL:
            return ai_score_cache.get(user_id, {})
    
    try:
        import aiohttp
        ai_url = os.environ.get('AI_SERVICE_URL', 'http://localhost:8000')
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ai_url}/ai/feed/{user_id}?limit=100") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    scores = {}
                    for item in data.get('feed', []):
                        scores[item['video_id']] = item['score']
                    
                    ai_score_cache[user_id] = scores
                    ai_score_cache_timestamp[user_id] = now
                    return scores
    except Exception as e:
        logger.error(f"Failed to fetch AI scores: {e}")
    
    return {}

def get_ai_scores_sync(user_id: str) -> Dict[str, float]:
# REPLACE the async fetch_ai_scores_async and get_ai_scores_sync with this:

def get_ai_scores_sync(user_id: str) -> Dict[str, float]:
    """Synchronous AI score fetching - no event loop issues"""
    if not AI_SERVICE_ENABLED:
        return {}
    
    try:
        import requests
        ai_url = os.environ.get('AI_SERVICE_URL', 'http://localhost:8000')
        
        # Use requests (synchronous) instead of aiohttp to avoid event loop issues
        response = requests.get(f"{ai_url}/ai/feed/{user_id}?limit=100", timeout=2)
        
        if response.status_code == 200:
            data = response.json()
            scores = {}
            for item in data.get('feed', []):
                scores[item['video_id']] = item['score']
            return scores
    except Exception as e:
        logger.error(f"Failed to fetch AI scores: {e}")
    
    return {}
    
def get_videos(cursor_timestamp: Optional[int], limit: int, current_user_id: Optional[str] = None) -> List[dict]:
    """Get videos, optionally reordered by AI scores"""
    videos = []
    
    if cursor_timestamp is None:
        start_index = 0
    else:
        start_index = 0
        for i in range(TOTAL_VIDEOS):
            video_timestamp = int(time.time() * 1000) - (i * 3600000)
            if video_timestamp < cursor_timestamp:
                start_index = i
                break
    
    # Generate base videos
    for i in range(start_index, min(start_index + limit * 2, TOTAL_VIDEOS)):
        videos.append(generate_video(i, current_user_id))
    
    # Try to reorder by AI scores
    if current_user_id and AI_SERVICE_ENABLED and AI_SERVICE_AVAILABLE:
        try:
            ai_scores = get_ai_scores_sync(current_user_id)
            if ai_scores:
                videos.sort(
                    key=lambda v: ai_scores.get(v['id'], 0),
                    reverse=True
                )
                for v in videos:
                    v['ai_score'] = ai_scores.get(v['id'])
        except Exception as e:
            logger.error(f"Error applying AI ordering: {e}")
    
    return videos[:limit]

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    return {
        "message": "Viral API is running",
        "status": "healthy",
        "ai_available": AI_SERVICE_AVAILABLE,
        "endpoints": {
            "videos": "GET /videos?limit=10&cursor=<timestamp>",
            "like": "POST /videos/{video_id}/like?user_id=xxx&action=like|unlike",
            "save": "POST /videos/{video_id}/save?user_id=xxx&action=save|unsave",
            "follow": "POST /users/{user_id}/follow?follower_id=xxx&action=follow|unfollow",
            "comments": "GET/POST /videos/{video_id}/comments?user_id=xxx",
            "ai": {
                "batch": "POST /ai/batch",
                "feed": "GET /ai/feed/{user_id}",
                "profile": "GET /ai/user/{user_id}/profile",
                "health": "GET /ai/health"
            }
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "ai_available": AI_SERVICE_AVAILABLE}

@app.get("/videos", response_model=PaginatedResponse)
async def get_videos_endpoint(
    limit: int = Query(VIDEOS_PER_PAGE, ge=1, le=50),
    cursor: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None)
):
    cursor_timestamp = int(cursor) if cursor else None
    videos_data = get_videos(cursor_timestamp, limit, user_id)
    
    if not videos_data:
        return PaginatedResponse(videos=[], next_cursor=None, has_more=False)
    
    videos = [Video(**v) for v in videos_data]
    
    last_video = videos[-1] if videos else None
    next_cursor = str(last_video.timestamp) if last_video and len(videos) == limit else None
    
    return PaginatedResponse(
        videos=videos,
        next_cursor=next_cursor,
        has_more=len(videos) == limit
    )

@app.get("/user/likes")
async def get_user_likes(user_id: str = Query(..., description="Current user ID")):
    """Get videos liked by user"""
    liked_video_ids = [vid for vid, users in likes_storage.items() if user_id in users]
    
    liked_videos = []
    for video_id in liked_video_ids[:20]:
        try:
            index = int(video_id.split('_')[1])
            video = generate_video(index, user_id)
            liked_videos.append(Video(**video))
        except:
            continue
    
    return {"liked_videos": liked_videos}

@app.get("/user/saved")
async def get_saved_videos(user_id: str = Query(..., description="Current user ID")):
    """Get saved videos for user"""
    saved_video_ids = [vid for vid, users in saves_storage.items() if user_id in users]
    
    saved_videos = []
    for video_id in saved_video_ids[:20]:
        try:
            index = int(video_id.split('_')[1])
            video = generate_video(index, user_id)
            saved_videos.append(Video(**video))
        except:
            continue
    
    return {"saved_videos": saved_videos}

@app.post("/videos/{video_id}/like")
async def like_video(
    video_id: str,
    action: LikeAction,
    user_id: str = Query(..., description="Current user ID")
):
    if not video_id:
        raise HTTPException(400, "Invalid video ID")
    
    if action.action == "like":
        if video_id not in likes_storage:
            likes_storage[video_id] = set()
        likes_storage[video_id].add(user_id)
        return {"success": True, "action": "liked", "likes_count": len(likes_storage[video_id])}
    else:
        if video_id in likes_storage:
            likes_storage[video_id].discard(user_id)
        return {"success": True, "action": "unliked", "likes_count": len(likes_storage.get(video_id, set()))}

@app.post("/videos/{video_id}/save")
async def save_video(
    video_id: str,
    action: SaveAction,
    user_id: str = Query(..., description="Current user ID")
):
    if action.action == "save":
        if video_id not in saves_storage:
            saves_storage[video_id] = set()
        saves_storage[video_id].add(user_id)
        return {"success": True, "action": "saved"}
    else:
        if video_id in saves_storage:
            saves_storage[video_id].discard(user_id)
        return {"success": True, "action": "unsaved"}

@app.post("/users/{target_user_id}/follow")
async def follow_user(
    target_user_id: str,
    action: FollowAction,
    follower_id: str = Query(..., description="Current user ID")
):
    if target_user_id == follower_id:
        raise HTTPException(400, "You cannot follow yourself")
    
    if action.action == "follow":
        if target_user_id not in follows_storage:
            follows_storage[target_user_id] = set()
        follows_storage[target_user_id].add(follower_id)
        return {"success": True, "action": "followed", "followers_count": len(follows_storage[target_user_id])}
    else:
        if target_user_id in follows_storage:
            follows_storage[target_user_id].discard(follower_id)
        return {"success": True, "action": "unfollowed", "followers_count": len(follows_storage.get(target_user_id, set()))}

@app.post("/videos/{video_id}/comments")
async def add_comment(
    video_id: str,
    comment: CommentCreate,
    user_id: str = Query(..., description="Current user ID"),
    user_name: Optional[str] = Query(None),
    user_avatar: Optional[str] = Query(None)
):
    new_comment = Comment(
        id=f"cmt_{int(time.time() * 1000)}",
        user=CommentUser(
            name=user_name or f"@{user_id[:8]}",
            avatar=user_avatar or "https://randomuser.me/api/portraits/women/8.jpg"
        ),
        text=comment.text,
        likes=0,
        time="Just now"
    )
    
    if video_id not in comments_storage:
        comments_storage[video_id] = []
    comments_storage[video_id].insert(0, new_comment)
    
    return {"success": True, "comment": new_comment}

@app.get("/videos/{video_id}/comments")
async def get_comments(video_id: str):
    return {"comments": comments_storage.get(video_id, [])}

@app.get("/stats")
async def get_stats():
    return {
        "total_videos": TOTAL_VIDEOS,
        "total_likes": sum(len(u) for u in likes_storage.values()),
        "total_saves": sum(len(u) for u in saves_storage.values()),
        "total_follows": sum(len(u) for u in follows_storage.values()),
        "total_comments": sum(len(c) for c in comments_storage.values()),
        "ai_available": AI_SERVICE_AVAILABLE
    }
