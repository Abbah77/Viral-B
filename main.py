from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Set, Any
import time
import random
from datetime import datetime
import bisect

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
    timestamp: int  # Unix timestamp in milliseconds

class PaginatedResponse(BaseModel):
    videos: List[Video]
    next_cursor: Optional[str]  # This is a timestamp string
    has_more: bool

# ==================== App Setup ====================

app = FastAPI(title="Viral API", version="1.0.0")

# CORS
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

# Storage
likes_storage: Dict[str, Set[str]] = {}
comments_storage: Dict[str, List[Comment]] = {}

# Google video URLs
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

# Author
AUTHOR = Author(
    name="@tiktok_user",
    avatar="https://randomuser.me/api/portraits/women/8.jpg"
)

# ==================== Video Generation with Real Timestamps ====================

def generate_video(index: int) -> dict:
    """
    Generate a single video with deterministic data.
    Timestamp decreases with index (older videos have smaller timestamps)
    """
    # Timestamp: newer videos (smaller index) have LARGER timestamps
    # This ensures chronological order when sorting by timestamp DESC
    current_time = int(time.time() * 1000)
    timestamp = current_time - (index * 3600000)  # Subtract 1 hour per video
    
    # Deterministic but varied data
    random.seed(index)
    
    video = {
        "id": f"{timestamp}_{index:05d}",  # ID format: timestamp_index
        "author": AUTHOR,
        "caption": CAPTIONS[index % len(CAPTIONS)],
        "hashtags": ["fyp", "viral", "trending", f"tag{index % 100}"][:random.randint(3, 5)],
        "video_url": VIDEO_POOL[index % len(VIDEO_POOL)],
        "thumbnail": f"https://picsum.photos/400/800?random={index}",
        "stats": {
            "likes": random.randint(1000, 5000000),
            "comments": random.randint(100, 50000),
            "shares": random.randint(500, 200000)
        },
        "timestamp": timestamp
    }
    
    random.seed()  # Reset seed
    return video

def get_videos_before_timestamp(timestamp: Optional[int], limit: int) -> List[dict]:
    """
    Get videos with timestamp < cursor timestamp.
    This is true cursor-based pagination - stable even with new videos.
    """
    videos = []
    
    if timestamp is None:
        # First page: start from newest (largest timestamp)
        start_index = 0
    else:
        # Find index where timestamp < cursor
        # Binary search to find the right starting point
        start_index = 0
        # Simple linear search for now (optimized for mock data)
        # In production with DB, this would be a SQL query
        for i in range(TOTAL_VIDEOS):
            video_timestamp = int(time.time() * 1000) - (i * 3600000)
            if video_timestamp < timestamp:
                start_index = i
                break
        else:
            start_index = TOTAL_VIDEOS
    
    # Generate videos starting from this index
    for i in range(start_index, min(start_index + limit, TOTAL_VIDEOS)):
        video = generate_video(i)
        videos.append(video)
    
    return videos

# ==================== API Endpoints ====================

@app.get("/")
async def root():
    return {
        "message": "Viral API is running with timestamp-based cursor pagination",
        "status": "healthy",
        "endpoints": {
            "videos": "GET /videos?limit=10&cursor=<timestamp>",
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
    limit: int = Query(VIDEOS_PER_PAGE, ge=1, le=50, description="Number of videos to return"),
    cursor: Optional[str] = Query(None, description="Timestamp cursor (last video's timestamp)")
):
    """
    Get videos with true timestamp-based cursor pagination.
    Use the timestamp from the last video as cursor for next page.
    
    Example:
    - First request: GET /videos?limit=10
    - Response includes next_cursor (timestamp of last video)
    - Next request: GET /videos?limit=10&cursor=1700000000000
    """
    
    # Parse cursor as timestamp
    cursor_timestamp = None
    if cursor:
        try:
            cursor_timestamp = int(cursor)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid cursor format. Use timestamp integer.")
    
    # Get videos before this timestamp
    videos_data = get_videos_before_timestamp(cursor_timestamp, limit)
    
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
    
    # Next cursor is the timestamp of the last video in this batch
    last_video = videos[-1] if videos else None
    next_cursor = str(last_video.timestamp) if last_video and len(videos) == limit else None
    
    # Determine if there are more videos
    has_more = False
    if last_video:
        # Check if there's at least one more video with timestamp < last_video.timestamp
        for i in range(TOTAL_VIDEOS):
            video_timestamp = int(time.time() * 1000) - (i * 3600000)
            if video_timestamp < last_video.timestamp:
                has_more = True
                break
    
    return PaginatedResponse(
        videos=videos,
        next_cursor=next_cursor,
        has_more=has_more
    )

@app.post("/videos/{video_id}/like")
async def like_video(video_id: str, action: LikeAction):
    """Like or unlike a video"""
    
    # Validate video ID exists (don't parse index, just check format)
    if not video_id or len(video_id.split('_')) != 2:
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
    if not video_id or len(video_id.split('_')) != 2:
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
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Get comments from storage or generate mock
    if video_id in comments_storage:
        comments = comments_storage[video_id]
    else:
        # Generate mock comments (max 3)
        comments = []
        mock_texts = [
            "This is amazing! 🔥",
            "Great content! 👏",
            "Love this video! ❤️",
            "So funny! 😂",
            "Can't stop watching!"
        ]
        for i, text in enumerate(mock_texts[:random.randint(0, 3)]):
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
    
    # Get first 5 videos to show cursor example
    sample_videos = []
    for i in range(min(5, TOTAL_VIDEOS)):
        video = generate_video(i)
        sample_videos.append({
            "id": video["id"],
            "timestamp": video["timestamp"],
            "caption": video["caption"][:30] + "..."
        })
    
    return {
        "total_videos": TOTAL_VIDEOS,
        "videos_with_likes": len(likes_storage),
        "total_likes": total_likes,
        "videos_with_comments": len(comments_storage),
        "total_comments": total_comments,
        "pagination_type": "timestamp-based cursor",
        "cursor_format": "Use timestamp from last video as cursor",
        "sample_videos": sample_videos
    }
