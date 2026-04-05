"""
Viral App - Backend API with AI Integration
No JWT required - just pass user ID from frontend
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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

# ============================================================================
# AI Service Import (with graceful fallback)
# ============================================================================

AI_SERVICE_AVAILABLE = False
ai_app = None

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

# Setup logging
logging.basicConfig(level=logging.INFO)
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
    
    @validator('text')
    def validate_text(cls, v):
        if not v or not v.strip():
            raise ValueError('Comment cannot be empty')
        return v.strip()

class LikeAction(BaseModel):
    action: str
    
    @validator('action')
    def validate_action(cls, v):
        if v not in ['like', 'unlike']:
            raise ValueError('Action must be "like" or "unlike"')
        return v

class SaveAction(BaseModel):
    action: str
    
    @validator('action')
    def validate_action(cls, v):
        if v not in ['save', 'unsave']:
            raise ValueError('Action must be "save" or "unsave"')
        return v

class FollowAction(BaseModel):
    action: str
    
    @validator('action')
    def validate_action(cls, v):
        if v not in ['follow', 'unfollow']:
            raise ValueError('Action must be "follow" or "unfollow"')
        return v

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
AI_CACHE_TTL = 300  # 5 minutes

# ============================================================================
# App Setup
# ============================================================================

app = FastAPI(
    title="Viral API", 
    version="1.0.0",
    description="Backend API for Viral App with AI integration"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Mount AI app at /ai
if AI_SERVICE_AVAILABLE and ai_app:
    app.mount("/ai", ai_app)
    print("✅ AI routes mounted at /ai")
else:
    app.include_router(ai_app)
    print("⚠️ AI fallback routes mounted")

# ============================================================================
# Video Data (Working Public URLs)
# ============================================================================

VIDEO_POOL = [
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4",
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/earth.mp4",
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/grayscale.mp4",
    "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/sea.mp4",
    "https://mdn.github.io/learning-area/html/multimedia-and-embedding/video-and-audio-content/pexels-koolshooters-7324441%20(small).mp4",
    "https://mdn.github.io/learning-area/html/multimedia-and-embedding/video-and-audio-content/pexels-mikhail-nilov-7538714%20(small).mp4",
]

# Fallback video URL in case primary fails
FALLBACK_VIDEO_URL = "https://interactive-examples.mdn.mozilla.net/media/cc0-videos/flower.mp4"

CAPTIONS = [
    "Check this out! 🔥",
    "This is amazing! ✨",
    "You won't believe this! 😱",
    "Best moment ever! 🎉",
    "Can't stop watching! 👀",
    "This is too good! 🔥",
    "Watch till the end! 🎬",
    "Mind-blowing content! 💫",
]

AUTHOR_NAMES = [
    "@tiktok_star", "@viral_creator", "@trending_now", "@daily_vibes", "@content_king",
    "@video_master", "@fun_clips", "@amazing_vids", "@must_watch", "@viral_hits"
]

AUTHOR_AVATARS = [
    "https://randomuser.me/api/portraits/women/1.jpg",
    "https://randomuser.me/api/portraits/men/2.jpg",
    "https://randomuser.me/api/portraits/women/3.jpg",
    "https://randomuser.me/api/portraits/men/4.jpg",
    "https://randomuser.me/api/portraits/women/5.jpg",
    "https://randomuser.me/api/portraits/men/6.jpg",
    "https://randomuser.me/api/portraits/women/7.jpg",
    "https://randomuser.me/api/portraits/men/8.jpg",
]

# ============================================================================
# Helper Functions
# ============================================================================

def generate_author(index: int) -> Author:
    """Generate author data deterministically based on index"""
    author_index = index % len(AUTHOR_NAMES)
    return Author(
        id=f"author_{author_index:03d}",
        name=AUTHOR_NAMES[author_index],
        avatar=AUTHOR_AVATARS[author_index]
    )

def get_video_url(index: int) -> str:
    """Get video URL with fallback"""
    try:
        url = VIDEO_POOL[index % len(VIDEO_POOL)]
        # Validate URL format
        if url.startswith(('http://', 'https://')):
            return url
        return FALLBACK_VIDEO_URL
    except Exception:
        return FALLBACK_VIDEO_URL

def generate_video(index: int, current_user_id: Optional[str] = None, ai_score: Optional[float] = None) -> dict:
    """Generate a single video object"""
    current_time = int(time.time() * 1000)
    timestamp = current_time - (index * 3600000)
    
    # Use seed for deterministic but varied content
    random.seed(index)
    
    author = generate_author(index)
    
    is_following = False
    if current_user_id and author.id:
        is_following = current_user_id in follows_storage.get(author.id, set())
    
    # Generate random but consistent stats based on index
    random.seed(index * 7)
    likes_count = random.randint(1000, 50000)
    comments_count = random.randint(100, 5000)
    shares_count = random.randint(500, 20000)
    
    video = {
        "id": f"{timestamp}_{index:05d}",
        "author": author.dict(),
        "caption": CAPTIONS[index % len(CAPTIONS)],
        "hashtags": ["fyp", "viral", f"trending{index % 100}"][:3],
        "video_url": get_video_url(index),
        "thumbnail": f"https://picsum.photos/id/{index % 1000}/400/800",
        "stats": {
            "likes": likes_count,
            "comments": comments_count,
            "shares": shares_count
        },
        "timestamp": timestamp,
        "is_following": is_following,
        "ai_score": ai_score
    }
    
    # Override likes count if there are stored likes
    video_id = video["id"]
    if video_id in likes_storage:
        video["stats"]["likes"] = len(likes_storage[video_id])
    
    # Reset random seed
    random.seed()
    
    return video

async def fetch_ai_scores(user_id: str) -> Dict[str, float]:
    """Fetch personalized video scores from AI service"""
    if not AI_SERVICE_ENABLED or not user_id:
        return {}
    
    # Check cache
    now = time.time()
    if user_id in ai_score_cache_timestamp:
        if now - ai_score_cache_timestamp[user_id] < AI_CACHE_TTL:
            return ai_score_cache.get(user_id, {})
    
    try:
        import aiohttp
        # Use environment variable for AI service URL
        ai_url = os.environ.get('AI_SERVICE_URL', 'http://localhost:8000')
        
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{ai_url}/ai/feed/{user_id}?limit=100") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    scores = {}
                    for item in data.get('feed', []):
                        if 'video_id' in item and 'score' in item:
                            scores[item['video_id']] = item['score']
                    
                    ai_score_cache[user_id] = scores
                    ai_score_cache_timestamp[user_id] = now
                    return scores
    except asyncio.TimeoutError:
        logger.warning(f"AI service timeout for user {user_id}")
    except Exception as e:
        logger.error(f"Failed to fetch AI scores for {user_id}: {e}")
    
    return {}

def get_videos(cursor_timestamp: Optional[int], limit: int, current_user_id: Optional[str] = None) -> List[dict]:
    """Get videos, optionally reordered by AI scores"""
    videos = []
    
    # Calculate start index based on cursor
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
    end_index = min(start_index + limit * 2, TOTAL_VIDEOS)
    for i in range(start_index, end_index):
        videos.append(generate_video(i, current_user_id))
    
    # Try to reorder by AI scores if user is authenticated
    if current_user_id and AI_SERVICE_ENABLED:
        try:
            # Run async function in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                ai_scores = loop.run_until_complete(fetch_ai_scores(current_user_id))
            finally:
                loop.close()
            
            if ai_scores:
                # Sort videos by AI score (higher score first)
                videos.sort(
                    key=lambda v: ai_scores.get(v['id'], 0),
                    reverse=True
                )
                # Add AI score to video objects
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
    """Root endpoint with API information"""
    return {
        "message": "Viral API is running",
        "status": "healthy",
        "version": "1.0.0",
        "ai_enabled": AI_SERVICE_ENABLED,
        "ai_available": AI_SERVICE_AVAILABLE,
        "endpoints": {
            "videos": "GET /videos?limit=10&cursor=<timestamp>&user_id=<user_id>",
            "like": "POST /videos/{video_id}/like?user_id=xxx",
            "save": "POST /videos/{video_id}/save?user_id=xxx",
            "follow": "POST /users/{user_id}/follow?follower_id=xxx",
            "comments": "GET/POST /videos/{video_id}/comments",
            "stats": "GET /stats",
            "health": "GET /health"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ai_available": AI_SERVICE_AVAILABLE,
        "videos_count": TOTAL_VIDEOS
    }

@app.get("/videos", response_model=PaginatedResponse)
async def get_videos_endpoint(
    limit: int = Query(VIDEOS_PER_PAGE, ge=1, le=50, description="Number of videos to return"),
    cursor: Optional[str] = Query(None, description="Pagination cursor (timestamp)"),
    user_id: Optional[str] = Query(None, description="Current user ID for personalization")
):
    """Get videos - pass user_id to get personalized ordering"""
    
    try:
        cursor_timestamp = int(cursor) if cursor else None
        videos_data = get_videos(cursor_timestamp, limit, user_id)
        
        if not videos_data:
            return PaginatedResponse(videos=[], next_cursor=None, has_more=False)
        
        videos = [Video(**v) for v in videos_data]
        
        last_video = videos[-1] if videos else None
        next_cursor = str(last_video.timestamp) if last_video and len(videos) == limit else None
        has_more = len(videos) == limit and (cursor_timestamp is not None or len(videos) == limit)
        
        return PaginatedResponse(
            videos=videos,
            next_cursor=next_cursor,
            has_more=has_more
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid cursor format: {str(e)}")
    except Exception as e:
        logger.error(f"Error in get_videos_endpoint: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/videos/{video_id}/like")
async def like_video(
    video_id: str,
    action: LikeAction,
    user_id: str = Query(..., description="Current user ID", min_length=1)
):
    """Like or unlike a video"""
    
    if not video_id or not video_id.strip():
        raise HTTPException(status_code=400, detail="Invalid video ID")
    
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="User ID is required")
    
    try:
        if action.action == "like":
            if video_id not in likes_storage:
                likes_storage[video_id] = set()
            likes_storage[video_id].add(user_id)
            return {
                "success": True, 
                "action": "liked", 
                "likes_count": len(likes_storage[video_id])
            }
        else:  # unlike
            if video_id in likes_storage:
                likes_storage[video_id].discard(user_id)
            return {
                "success": True, 
                "action": "unliked", 
                "likes_count": len(likes_storage.get(video_id, set()))
            }
    except Exception as e:
        logger.error(f"Error in like_video: {e}")
        raise HTTPException(status_code=500, detail="Failed to process like")

@app.post("/videos/{video_id}/save")
async def save_video(
    video_id: str,
    action: SaveAction,
    user_id: str = Query(..., description="Current user ID", min_length=1)
):
    """Save or unsave a video"""
    
    if not video_id or not video_id.strip():
        raise HTTPException(status_code=400, detail="Invalid video ID")
    
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="User ID is required")
    
    try:
        if action.action == "save":
            if video_id not in saves_storage:
                saves_storage[video_id] = set()
            saves_storage[video_id].add(user_id)
            return {"success": True, "action": "saved"}
        else:  # unsave
            if video_id in saves_storage:
                saves_storage[video_id].discard(user_id)
            return {"success": True, "action": "unsaved"}
    except Exception as e:
        logger.error(f"Error in save_video: {e}")
        raise HTTPException(status_code=500, detail="Failed to process save")

@app.post("/users/{target_user_id}/follow")
async def follow_user(
    target_user_id: str,
    action: FollowAction,
    follower_id: str = Query(..., description="Current user ID", min_length=1)
):
    """Follow or unfollow a user"""
    
    if not target_user_id or not target_user_id.strip():
        raise HTTPException(status_code=400, detail="Invalid target user ID")
    
    if not follower_id or not follower_id.strip():
        raise HTTPException(status_code=400, detail="Follower ID is required")
    
    if target_user_id == follower_id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself")
    
    try:
        if action.action == "follow":
            if target_user_id not in follows_storage:
                follows_storage[target_user_id] = set()
            follows_storage[target_user_id].add(follower_id)
            return {
                "success": True, 
                "action": "followed", 
                "followers_count": len(follows_storage[target_user_id])
            }
        else:  # unfollow
            if target_user_id in follows_storage:
                follows_storage[target_user_id].discard(follower_id)
            return {
                "success": True, 
                "action": "unfollowed", 
                "followers_count": len(follows_storage.get(target_user_id, set()))
            }
    except Exception as e:
        logger.error(f"Error in follow_user: {e}")
        raise HTTPException(status_code=500, detail="Failed to process follow")

@app.post("/videos/{video_id}/comments")
async def add_comment(
    video_id: str,
    comment: CommentCreate,
    user_id: str = Query(..., description="Current user ID", min_length=1),
    user_name: Optional[str] = Query(None, description="User's display name"),
    user_avatar: Optional[str] = Query(None, description="User's avatar URL")
):
    """Add a comment to a video"""
    
    if not video_id or not video_id.strip():
        raise HTTPException(status_code=400, detail="Invalid video ID")
    
    try:
        new_comment = Comment(
            id=f"cmt_{int(time.time() * 1000)}_{random.randint(1000, 9999)}",
            user=CommentUser(
                name=user_name or f"user_{user_id[:8]}",
                avatar=user_avatar or "https://randomuser.me/api/portraits/lego/1.jpg"
            ),
            text=comment.text,
            likes=0,
            time="Just now"
        )
        
        if video_id not in comments_storage:
            comments_storage[video_id] = []
        comments_storage[video_id].insert(0, new_comment)
        
        # Keep only last 100 comments per video
        if len(comments_storage[video_id]) > 100:
            comments_storage[video_id] = comments_storage[video_id][:100]
        
        return {"success": True, "comment": new_comment.dict()}
    except Exception as e:
        logger.error(f"Error in add_comment: {e}")
        raise HTTPException(status_code=500, detail="Failed to add comment")

@app.get("/videos/{video_id}/comments")
async def get_comments(
    video_id: str,
    limit: int = Query(50, ge=1, le=100, description="Number of comments to return")
):
    """Get comments for a video"""
    
    if not video_id or not video_id.strip():
        raise HTTPException(status_code=400, detail="Invalid video ID")
    
    try:
        comments = comments_storage.get(video_id, [])
        # Return most recent comments first
        return {
            "comments": [c.dict() for c in comments[:limit]],
            "total": len(comments)
        }
    except Exception as e:
        logger.error(f"Error in get_comments: {e}")
        raise HTTPException(status_code=500, detail="Failed to get comments")

@app.get("/user/saved")
async def get_saved_videos(
    user_id: str = Query(..., description="Current user ID", min_length=1),
    limit: int = Query(20, ge=1, le=50, description="Number of saved videos to return")
):
    """Get saved videos for user"""
    
    if not user_id or not user_id.strip():
        raise HTTPException(status_code=400, detail="User ID is required")
    
    try:
        saved_video_ids = [vid for vid, users in saves_storage.items() if user_id in users]
        
        saved_videos = []
        for video_id in saved_video_ids[:limit]:
            try:
                # Extract index from video ID (format: timestamp_index)
                parts = video_id.split('_')
                if len(parts) >= 2:
                    index = int(parts[1])
                    video = generate_video(index, user_id)
                    saved_videos.append(Video(**video))
            except (ValueError, IndexError) as e:
                logger.warning(f"Failed to parse video ID {video_id}: {e}")
                continue
        
        return {"saved_videos": saved_videos, "total": len(saved_video_ids)}
    except Exception as e:
        logger.error(f"Error in get_saved_videos: {e}")
        raise HTTPException(status_code=500, detail="Failed to get saved videos")

@app.get("/stats")
async def get_stats():
    """Get app statistics"""
    try:
        return {
            "total_videos": TOTAL_VIDEOS,
            "total_likes": sum(len(u) for u in likes_storage.values()),
            "total_saves": sum(len(u) for u in saves_storage.values()),
            "total_follows": sum(len(u) for u in follows_storage.values()),
            "total_comments": sum(len(c) for c in comments_storage.values()),
            "ai_enabled": AI_SERVICE_ENABLED,
            "ai_available": AI_SERVICE_AVAILABLE,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error in get_stats: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stats")

# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": exc.detail, "status_code": exc.status_code}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error", "status_code": 500}
    )

# ============================================================================
# Run with: uvicorn main:app --reload --port 8000 --host 0.0.0.0
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
