# main.py - Complete backend in one file
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
    original_likes: Optional[int] = None

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
    action: str = Field(..., pattern="^(like|unlike)$")

class Video(BaseModel):
    id: str
    author: Author
    caption: str
    hashtags: List[str]
    video_url: str
    thumbnail: str
    stats: Stats
    comments: List[Any] = []
    timestamp: Optional[int] = None

class PaginatedResponse(BaseModel):
    videos: List[Video]
    next_cursor: Optional[str]
    has_more: bool

# ==================== Configuration ====================

app = FastAPI(title="Viral API", version="1.0.0")

# CORS - Allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
TOTAL_VIDEOS = 10000
VIDEOS_PER_PAGE = 10
CURRENT_USER_ID = "user_001"

# In-memory storage
likes_storage: Dict[str, Set[str]] = {}
comments_storage: Dict[str, List[Comment]] = {}

# Google video URLs pool
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
CAPTION_TEMPLATES = [
    "Check this out! {} 🔥",
    "This is amazing! {} ✨",
    "You won't believe this! {} 😱",
    "Best moment ever! {} 🎉",
    "Can't stop watching this! {} 👀",
    "This made my day! {} ❤️",
    "So satisfying! {} 😌",
    "Mind = blown! {} 🤯",
    "Pure gold! {} 🏆",
    "This is everything! {} 💯",
    "Had to share this! {} 📱",
    "So funny! {} 😂",
    "Absolutely incredible! {} 🌟",
    "Watch till the end! {} 👇",
    "This is the content we need! {} 🙌"
]

# Hashtag pools
HASHTAG_POOLS = [
    ["fyp", "viral", "trending", "explore"],
    ["comedy", "funny", "humor", "lol"],
    ["dance", "challenge", "trending", "music"],
    ["beauty", "makeup", "fashion", "style"],
    ["travel", "adventure", "wanderlust", "nature"],
    ["sports", "fitness", "workout", "gym"],
    ["food", "cooking", "delicious", "yummy"],
    ["art", "creative", "design", "inspiration"],
    ["pets", "dogs", "cats", "animals"],
    ["lifehack", "tips", "tutorial", "diy"]
]

# Author (same for all videos)
AUTHOR = {
    "name": "@tiktok_user",
    "avatar": "https://randomuser.me/api/portraits/women/8.jpg"
}

# ==================== Helper Functions ====================

def generate_timestamp(index: int) -> int:
    """Generate deterministic timestamp for video"""
    base_time = int(time.time() * 1000)
    return base_time - (index * 1000 * 60 * 60 * 24)

def generate_video_id(index: int) -> str:
    """Generate deterministic video ID"""
    timestamp = generate_timestamp(index)
    return f"{timestamp}_{index:05d}"

def generate_caption(index: int) -> str:
    """Generate deterministic caption"""
    template = CAPTION_TEMPLATES[index % len(CAPTION_TEMPLATES)]
    emojis = ["😂", "🔥", "✨", "😱", "🎉", "❤️", "🤯", "💯", "👀", "🌟"]
    suffix = emojis[index % len(emojis)]
    return template.format(suffix)

def generate_hashtags(index: int) -> List[str]:
    """Generate deterministic hashtags"""
    pool = HASHTAG_POOLS[index % len(HASHTAG_POOLS)]
    trending = ["fyp", "viral"]
    result = pool.copy()
    result.extend(trending[:random.randint(1, 2)])
    return result[:5]

def generate_likes(index: int) -> int:
    """Generate deterministic likes"""
    random.seed(index)
    likes = random.randint(1000, 5000000)
    random.seed()
    return likes

def generate_comments(index: int) -> int:
    """Generate deterministic comments"""
    random.seed(index + 10000)
    comments = random.randint(100, 50000)
    random.seed()
    return comments

def generate_shares(index: int) -> int:
    """Generate deterministic shares"""
    random.seed(index + 20000)
    shares = random.randint(500, 200000)
    random.seed()
    return shares

def generate_videos_batch(start_index: int, limit: int) -> List[dict]:
    """Generate a batch of videos"""
    videos = []
    
    for i in range(start_index, start_index + limit):
        if i >= TOTAL_VIDEOS:
            break
            
        video_id = generate_video_id(i)
        
        video = {
            "id": video_id,
            "author": AUTHOR,
            "caption": generate_caption(i),
            "hashtags": generate_hashtags(i),
            "video_url": VIDEO_POOL[i % len(VIDEO_POOL)],
            "thumbnail": f"https://picsum.photos/400/800?random={i}",
            "stats": {
                "likes": generate_likes(i),
                "comments": generate_comments(i),
                "shares": generate_shares(i),
                "original_likes": generate_likes(i)
            },
            "timestamp": generate_timestamp(i)
        }
        videos.append(video)
    
    return videos

def generate_mock_comments(video_id: str, count: int = 3) -> List[Comment]:
    """Generate mock comments for a video"""
    comments = []
    comment_templates = [
        "This is amazing! 🔥",
        "Great content! 👏",
        "Love this video! ❤️",
        "So funny! 😂",
        "Can't stop watching!",
        "Best video ever!",
        "Keep up the good work!",
        "This made my day! ✨"
    ]
    
    for i in range(min(count, len(comment_templates))):
        comment = Comment(
            id=f"cmt_{video_id}_{i}",
            user=CommentUser(
                name=f"@user_{random.randint(100, 999)}",
                avatar=f"https://randomuser.me/api/portraits/{random.choice(['men', 'women'])}/{random.randint(1, 50)}.jpg"
            ),
            text=comment_templates[i % len(comment_templates)],
            likes=random.randint(0, 1000),
            time=f"{random.randint(1, 24)}h ago"
        )
        comments.append(comment)
    
    return comments

# ==================== API Endpoints ====================

@app.get("/")
async def root():
    return {"message": "Viral API is running", "status": "healthy"}

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "total_videos": TOTAL_VIDEOS
    }

@app.get("/api/videos", response_model=PaginatedResponse)
async def get_videos(
    limit: int = Query(VIDEOS_PER_PAGE, ge=1, le=50),
    cursor: Optional[str] = Query(None)
):
    """Get paginated videos with cursor-based pagination"""
    
    # Parse cursor to get starting index
    if cursor:
        try:
            start_index = int(cursor.split('_')[1]) + 1
        except (ValueError, IndexError):
            start_index = 0
    else:
        start_index = 0
    
    # Generate videos
    videos_data = generate_videos_batch(start_index, limit)
    
    if not videos_data:
        return PaginatedResponse(
            videos=[],
            next_cursor=None,
            has_more=False
        )
    
    # Convert to Video objects and add like counts
    videos = []
    for video_dict in videos_data:
        video_id = video_dict["id"]
        
        # Get actual like count from storage
        like_count = len(likes_storage.get(video_id, set()))
        if like_count > 0:
            video_dict["stats"]["likes"] = like_count
        
        videos.append(Video(**video_dict))
    
    # Determine next cursor
    last_video = videos[-1] if videos else None
    next_cursor = last_video.id if last_video and len(videos) == limit else None
    
    # Check if more videos exist
    has_more = start_index + limit < TOTAL_VIDEOS
    
    return PaginatedResponse(
        videos=videos,
        next_cursor=next_cursor,
        has_more=has_more
    )

@app.post("/api/videos/{video_id}/like")
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

@app.post("/api/videos/{video_id}/comments")
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
        "comment": new_comment.dict()
    }

@app.get("/api/videos/{video_id}/comments")
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
        comments = generate_mock_comments(video_id, random.randint(0, 5))
        comments_storage[video_id] = comments
    
    return {"comments": [c.dict() for c in comments]}

@app.get("/api/stats")
async def get_stats():
    """Get API statistics (debug)"""
    total_likes = sum(len(users) for users in likes_storage.values())
    total_comments = sum(len(comments) for comments in comments_storage.values())
    
    return {
        "total_videos": TOTAL_VIDEOS,
        "videos_with_likes": len(likes_storage),
        "total_likes": total_likes,
        "videos_with_comments": len(comments_storage),
        "total_comments": total_comments
    }
