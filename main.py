"""
Viral App - Backend API with AI Integration
FULL VERSION: All original features preserved + 20 Working CDN Links
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
import aiohttp

# ============================================================================
# AI Service Import (with graceful fallback)
# ============================================================================

try:
    from ai_service import ai_app
    AI_SERVICE_AVAILABLE = True
    print("✅ AI Service loaded successfully")
except ImportError as e:
    print(f"⚠️ AI Service not available: {e}")
    AI_SERVICE_AVAILABLE = False
    from fastapi import APIRouter
    ai_app = APIRouter()
    
    @ai_app.get("/health")
    async def ai_health_fallback():
        return {"status": "disabled", "message": "AI service not available"}

# ============================================================================
# Configuration
# ============================================================================

TOTAL_VIDEOS = 10000
VIDEOS_PER_PAGE = 10
AI_SERVICE_ENABLED = True
AI_CACHE_TTL = 300  # 5 minutes

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
# Storage (In-Memory)
# ============================================================================

likes_storage: Dict[str, Set[str]] = {}
saves_storage: Dict[str, Set[str]] = {}
follows_storage: Dict[str, Set[str]] = {}
comments_storage: Dict[str, List[Comment]] = {}

# Cache for AI-scored videos
ai_score_cache: Dict[str, Dict[str, float]] = {}
ai_score_cache_timestamp: Dict[str, float] = {}

# ============================================================================
# Video Data (Updated with 20 working high-speed CDN links)
# ============================================================================

VIDEO_POOL = [
    "https://player.vimeo.com/external/370331493.sd.mp4?s=72d4855dd7a304820dc4667e42dae66b72016338&profile_id=139",
    "https://player.vimeo.com/external/517090025.sd.mp4?s=f0227f42d20779774b968fc265b741031b671a5c&profile_id=164",
    "https://player.vimeo.com/external/434045526.sd.mp4?s=c130386653ef696d55734268e3170498b50209df&profile_id=139",
    "https://player.vimeo.com/external/459389137.sd.mp4?s=91083a23a3ef944749f7e53f1917b2b7337f7663&profile_id=139",
    "https://player.vimeo.com/external/403753177.sd.mp4?s=76d370f80928a6f376a911765c71124e4d6d7c88&profile_id=139",
    "https://player.vimeo.com/external/368744092.sd.mp4?s=d0092147f8976b5c32e0325d97e8ecf661df2591&profile_id=139",
    "https://player.vimeo.com/external/392040265.sd.mp4?s=34f3f0e060049e917d0563462551a37c89146f48&profile_id=139",
    "https://player.vimeo.com/external/394740214.sd.mp4?s=9b82811796d1945115c8e2259178be3e6e872b78&profile_id=139",
    "https://player.vimeo.com/external/442937061.sd.mp4?s=d46777098e945e48600c3b88a8d1154563a69a4c&profile_id=139",
    "https://player.vimeo.com/external/430014215.sd.mp4?s=91b10a454ca1b80410f993d07e6005230f3f6192&profile_id=139",
    "https://player.vimeo.com/external/340620310.sd.mp4?s=a7d30f782c5f118d047321e0691e847ae17c5b65&profile_id=139",
    "https://player.vimeo.com/external/324417380.sd.mp4?s=2544c77607a72667104b2c83d65b1d5d1112461b&profile_id=139",
    "https://player.vimeo.com/external/482815777.sd.mp4?s=8b776263595503049103e30f1d530e32d6645391&profile_id=139",
    "https://player.vimeo.com/external/510850877.sd.mp4?s=bd44607d7c67426338b0008405022e3ee44e39ec&profile_id=164",
    "https://player.vimeo.com/external/318356985.sd.mp4?s=1833d7b322a313e6a0d4c8313495f5778a546c10&profile_id=139",
    "https://player.vimeo.com/external/530514102.sd.mp4?s=a796677f4f699049e21143c7b64f9f7ba3b1d3d6&profile_id=165",
    "https://player.vimeo.com/external/520268571.sd.mp4?s=83d5a420b72186d061406607d6c8e3e4a2d8edb2&profile_id=164",
    "https://player.vimeo.com/external/540026827.sd.mp4?s=589e4726e855581b24131df332b50937c223c965&profile_id=165",
    "https://player.vimeo.com/external/401037805.sd.mp4?s=74f26a15e610d48f94e9f7823906f2e245a165b4&profile_id=139",
    "https://player.vimeo.com/external/393220478.sd.mp4?s=c855a00889270e5b7c7562089f2d192131bf218a&profile_id=139"
]

CAPTIONS = ["Check this out! 🔥", "This is amazing! ✨", "You won't believe this! 😱", "Best moment ever! 🎉", "Can't stop watching! 👀"]
AUTHOR_NAMES = ["@tiktok_star", "@viral_creator", "@trending_now", "@daily_vibes", "@content_king"]
AUTHOR_AVATARS = [f"https://api.dicebear.com/7.x/avataaars/svg?seed={i}" for i in range(5)]

# ============================================================================
# Logic Helpers
# ============================================================================

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
        "thumbnail": f"https://picsum.photos/seed/{index}/400/800",
        "stats": {
            "likes": random.randint(1000, 50000),
            "comments": random.randint(100, 5000),
            "shares": random.randint(500, 20000)
        },
        "timestamp": timestamp,
        "is_following": is_following,
        "ai_score": ai_score
    }
    
    if video["id"] in likes_storage:
        video["stats"]["likes"] = len(likes_storage[video["id"]])
    
    random.seed()
    return video

async def fetch_ai_scores(user_id: str) -> Dict[str, float]:
    if not AI_SERVICE_ENABLED:
        return {}
    
    now = time.time()
    if user_id in ai_score_cache_timestamp:
        if now - ai_score_cache_timestamp[user_id] < AI_CACHE_TTL:
            return ai_score_cache.get(user_id, {})
    
    try:
        ai_url = os.environ.get('AI_SERVICE_URL', 'http://localhost:8000')
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ai_url}/ai/feed/{user_id}?limit=100", timeout=2) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    scores = {item['video_id']: item['score'] for item in data.get('feed', [])}
                    ai_score_cache[user_id] = scores
                    ai_score_cache_timestamp[user_id] = now
                    return scores
    except Exception as e:
        logger.error(f"AI Score Fetch Error: {e}")
    
    return {}

# ============================================================================
# App Setup & Endpoints
# ============================================================================

app = FastAPI(title="Viral API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if AI_SERVICE_AVAILABLE:
    app.mount("/ai", ai_app)
else:
    app.include_router(ai_app)

@app.get("/")
async def root():
    return {
        "message": "Viral API is running",
        "status": "healthy",
        "video_pool_count": len(VIDEO_POOL),
        "ai_enabled": AI_SERVICE_ENABLED,
        "endpoints": ["/videos", "/stats", "/health"]
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
    
    # 1. Fetch AI scores asynchronously (non-blocking)
    ai_scores = await fetch_ai_scores(user_id) if user_id else {}
    
    # 2. Determine start index based on cursor
    start_index = 0
    if cursor_timestamp:
        for i in range(TOTAL_VIDEOS):
            # Reverse-engineer timestamp based on generate_video logic
            if (int(time.time() * 1000) - (i * 3600000)) < cursor_timestamp:
                start_index = i
                break
    
    # 3. Generate videos
    videos_raw = []
    # Fetch extra to allow for AI reordering room
    fetch_limit = limit * 2 if ai_scores else limit
    for i in range(start_index, min(start_index + fetch_limit, TOTAL_VIDEOS)):
        v = generate_video(i, user_id)
        if ai_scores and v['id'] in ai_scores:
            v['ai_score'] = ai_scores[v['id']]
        videos_raw.append(v)
    
    # 4. Sort by AI Score if available
    if ai_scores:
        videos_raw.sort(key=lambda x: x.get('ai_score', 0), reverse=True)
    
    # 5. Paginate and validate
    paginated_data = videos_raw[:limit]
    videos = [Video(**v) for v in paginated_data]
    
    next_cursor = str(videos[-1].timestamp) if videos and len(videos) == limit else None
    
    return PaginatedResponse(
        videos=videos,
        next_cursor=next_cursor,
        has_more=len(videos) == limit
    )

@app.post("/videos/{video_id}/like")
async def like_video(video_id: str, action: LikeAction, user_id: str = Query(...)):
    if video_id not in likes_storage:
        likes_storage[video_id] = set()
    
    if action.action == "like":
        likes_storage[video_id].add(user_id)
    else:
        likes_storage[video_id].discard(user_id)
        
    return {"success": True, "likes_count": len(likes_storage[video_id])}

@app.post("/videos/{video_id}/save")
async def save_video(video_id: str, action: SaveAction, user_id: str = Query(...)):
    if video_id not in saves_storage:
        saves_storage[video_id] = set()
    
    if action.action == "save":
        saves_storage[video_id].add(user_id)
    else:
        saves_storage[video_id].discard(user_id)
        
    return {"success": True}

@app.post("/users/{target_user_id}/follow")
async def follow_user(target_user_id: str, action: FollowAction, follower_id: str = Query(...)):
    if target_user_id not in follows_storage:
        follows_storage[target_user_id] = set()
        
    if action.action == "follow":
        follows_storage[target_user_id].add(follower_id)
    else:
        follows_storage[target_user_id].discard(follower_id)
        
    return {"success": True, "followers_count": len(follows_storage[target_user_id])}

@app.post("/videos/{video_id}/comments")
async def add_comment(
    video_id: str, 
    comment: CommentCreate, 
    user_id: str = Query(...), 
    user_name: str = None, 
    user_avatar: str = None
):
    new_comment = Comment(
        id=f"cmt_{int(time.time() * 1000)}",
        user=CommentUser(
            name=user_name or f"@{user_id[:8]}",
            avatar=user_avatar or "https://api.dicebear.com/7.x/avataaars/svg?seed=fallback"
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

@app.get("/user/saved")
async def get_saved_videos(user_id: str = Query(...)):
    saved_video_ids = [vid for vid, users in saves_storage.items() if user_id in users]
    saved_videos = []
    for video_id in saved_video_ids[:20]:
        try:
            # Reconstruct video from ID suffix
            index = int(video_id.split('_')[1])
            saved_videos.append(Video(**generate_video(index, user_id)))
        except: continue
    return {"saved_videos": saved_videos}

@app.get("/stats")
async def get_stats():
    return {
        "total_videos": TOTAL_VIDEOS,
        "total_likes": sum(len(u) for u in likes_storage.values()),
        "total_saves": sum(len(u) for u in saves_storage.values()),
        "total_follows": sum(len(u) for u in follows_storage.values()),
        "total_comments": sum(len(c) for c in comments_storage.values()),
        "ai_enabled": AI_SERVICE_ENABLED
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
