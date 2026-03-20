from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Set, Any
import time
import random
from datetime import datetime

# ==================== Models ====================

class Author(BaseModel):
    name: str
    avatar: str

class Stats(BaseModel):
    likes: int
    comments: int
    shares: int

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

class Video(BaseModel):
    id: str
    author: Author
    caption: str
    hashtags: List[str]
    video_url: str
    thumbnail: str
    stats: Stats
    timestamp: Optional[int] = None

class PaginatedResponse(BaseModel):
    videos: List[Video]
    next_cursor: Optional[str]
    has_more: bool

# ==================== App Setup ====================

app = FastAPI(title="Viral API", version="1.0.0")

# CORS - Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
TOTAL_VIDEOS = 10000
CURRENT_USER_ID = "user_001"

# Storage
likes_storage: Dict[str, Set[str]] = {}
comments_storage: Dict[str, List[Comment]] = {}

# Google video URLs (10 videos)
VIDEO_POOL = [
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerJoyrides.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerEscapes.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerFun.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerMeltdowns.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/SubaruOutbackOnStreetAndDirt.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/TearsOfSteel.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WhatCar.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/WeAreGoingOnBullrun.mp4",
    "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/HisDayIsComing.mp4"
]

# Caption templates
CAPTIONS = [
    "Check this out! 🔥",
    "This is amazing! ✨",
    "You won't believe this! 😱",
    "Best moment ever! 🎉",
    "Can't stop watching! 👀",
    "This made my day! ❤️",
    "So satisfying! 😌",
    "Mind = blown! 🤯",
    "Pure gold! 🏆",
    "This is everything! 💯",
    "Had to share this! 📱",
    "So funny! 😂",
    "Absolutely incredible! 🌟",
    "Watch till the end! 👇",
    "This is the content we need! 🙌"
]

# Author (same for all videos)
AUTHOR = Author(
    name="@tiktok_user",
    avatar="https://randomuser.me/api/portraits/women/8.jpg"
)

# ==================== Helper Functions ====================

def generate_video_id(index: int) -> str:
    """Generate video ID with timestamp and index"""
    timestamp = int(time.time() * 1000) - (index * 86400000)  # 1 day = 86400000 ms
    return f"{timestamp}_{index:05d}"

def generate_videos(start_index: int, limit: int) -> List[dict]:
    """Generate videos on demand"""
    videos = []
    for i in range(start_index, min(start_index + limit, TOTAL_VIDEOS)):
        # Deterministic but varied data based on index
        random.seed(i)
        
        video = {
            "id": generate_video_id(i),
            "author": AUTHOR,
            "caption": CAPTIONS[i % len(CAPTIONS)],
            "hashtags": ["fyp", "viral", "trending", "explore", f"tag{i % 100}"][:random.randint(3, 5)],
            "video_url": VIDEO_POOL[i % len(VIDEO_POOL)],
            "thumbnail": f"https://picsum.photos/400/800?random={i}",
            "stats": {
                "likes": random.randint(1000, 5000000),
                "comments": random.randint(100, 50000),
                "shares": random.randint(500, 200000)
            },
            "timestamp": int(time.time() * 1000) - (i * 86400000)
        }
        videos.append(video)
    
    random.seed()  # Reset seed
    return videos

# ==================== API Endpoints ====================

@app.get("/")
async def root():
    return {
        "message": "Viral API is running!",
        "status": "healthy",
        "endpoints": {
            "videos": "GET /videos?limit=10&cursor=0",
            "like": "POST /videos/{video_id}/like",
            "comments": "GET/POST /videos/{video_id}/comments",
            "health": "GET /health"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/videos", response_model=PaginatedResponse)
async def get_videos(
    limit: int = Query(10, ge=1, le=50, description="Number of videos to return"),
    cursor: Optional[str] = Query(None, description="Cursor for pagination (video index)")
):
    """Get videos with cursor-based pagination. Use cursor=0 for first page."""
    
    # Parse cursor (just use the index from cursor)
    if cursor:
        try:
            start_index = int(cursor)
        except (ValueError, TypeError):
            start_index = 0
    else:
        start_index = 0
    
    # Generate videos
    videos_data = generate_videos(start_index, limit)
    
    if not videos_data:
        return PaginatedResponse(videos=[], next_cursor=None, has_more=False)
    
    # Convert to Video objects and update with actual like counts
    videos = []
    for video_dict in videos_data:
        video_id = video_dict["id"]
        
        # Update likes from storage if any
        like_count = len(likes_storage.get(video_id, set()))
        if like_count > 0:
            video_dict["stats"]["likes"] = like_count
        
        videos.append(Video(**video_dict))
    
    # Calculate next cursor
    next_cursor = str(start_index + limit) if start_index + limit < TOTAL_VIDEOS else None
    has_more = start_index + limit < TOTAL_VIDEOS
    
    return PaginatedResponse(
        videos=videos,
        next_cursor=next_cursor,
        has_more=has_more
    )

@app.post("/videos/{video_id}/like")
async def like_video(video_id: str, action: LikeAction):
    """Like or unlike a video"""
    
    # Validate video ID format
    try:
        index = int(video_id.split('_')[1])
        if index < 0 or index >= TOTAL_VIDEOS:
            raise HTTPException(status_code=404, detail="Video not found")
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Initialize storage
    if video_id not in likes_storage:
        likes_storage[video_id] = set()
    
    if action.action == "like":
        likes_storage[video_id].add(CURRENT_USER_ID)
        action_type = "liked"
    else:
        likes_storage[video_id].discard(CURRENT_USER_ID)
        action_type = "unliked"
    
    return {
        "success": True,
        "action": action_type,
        "video_id": video_id,
        "likes_count": len(likes_storage[video_id])
    }

@app.post("/videos/{video_id}/comments")
async def add_comment(video_id: str, comment: CommentCreate):
    """Add a comment to a video"""
    
    # Validate video ID
    try:
        index = int(video_id.split('_')[1])
        if index < 0 or index >= TOTAL_VIDEOS:
            raise HTTPException(status_code=404, detail="Video not found")
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Create new comment
    new_comment = Comment(
        id=f"cmt_{int(time.time() * 1000)}_{random.randint(1000, 9999)}",
        user=CommentUser(
            name="@current_user",
            avatar="https://randomuser.me/api/portraits/women/8.jpg"
        ),
        text=comment.text,
        likes=0,
        time="Just now"
    )
    
    # Store comment
    if video_id not in comments_storage:
        comments_storage[video_id] = []
    comments_storage[video_id].append(new_comment)
    
    return {
        "success": True,
        "comment": new_comment
    }

@app.get("/videos/{video_id}/comments")
async def get_comments(video_id: str):
    """Get comments for a video"""
    
    # Validate video ID
    try:
        index = int(video_id.split('_')[1])
        if index < 0 or index >= TOTAL_VIDEOS:
            raise HTTPException(status_code=404, detail="Video not found")
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Get comments from storage or generate mock
    if video_id in comments_storage:
        comments = comments_storage[video_id]
    else:
        # Generate mock comments
        comments = []
        mock_comments = [
            "This is amazing! 🔥",
            "Great content! 👏",
            "Love this video! ❤️",
            "So funny! 😂",
            "Can't stop watching!"
        ]
        for i, text in enumerate(mock_comments[:random.randint(0, 3)]):
            comment = Comment(
                id=f"cmt_{video_id}_{i}",
                user=CommentUser(
                    name=f"@user_{random.randint(100, 999)}",
                    avatar=f"https://randomuser.me/api/portraits/{random.choice(['men', 'women'])}/{random.randint(1, 50)}.jpg"
                ),
                text=text,
                likes=random.randint(0, 500),
                time=f"{random.randint(1, 24)}h ago"
            )
            comments.append(comment)
        comments_storage[video_id] = comments
    
    return {"comments": comments}

@app.get("/stats")
async def get_stats():
    """Get API statistics"""
    total_likes = sum(len(users) for users in likes_storage.values())
    total_comments = sum(len(comments) for comments in comments_storage.values())
    
    return {
        "total_videos": TOTAL_VIDEOS,
        "videos_with_likes": len(likes_storage),
        "total_likes": total_likes,
        "videos_with_comments": len(comments_storage),
        "total_comments": total_comments
    }
