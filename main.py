from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Set, Any
import time
import random
from datetime import datetime

# ==================== Models ====================

class Author(BaseModel):
    id: str
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

class SaveAction(BaseModel):
    action: str

class FollowAction(BaseModel):
    action: str

class Video(BaseModel):
    id: str
    author: Author
    caption: str
    hashtags: List[str]
    video_url: str
    thumbnail: str
    stats: Stats
    timestamp: int

class PaginatedResponse(BaseModel):
    videos: List[Video]
    next_cursor: Optional[str]
    has_more: bool

# ==================== App Setup ====================

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

# Storage
likes_storage: Dict[str, Set[str]] = {}
saves_storage: Dict[str, Set[str]] = {}
follows_storage: Dict[str, Set[str]] = {}
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

# Author names pool
AUTHOR_NAMES = [
    "@tiktok_star", "@viral_creator", "@trending_now", "@daily_vibes", "@content_king",
    "@viral_girl", "@funny_moments", "@dance_lord", "@music_lover", "@travel_bug"
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
    "https://randomuser.me/api/portraits/women/9.jpg",
    "https://randomuser.me/api/portraits/men/10.jpg"
]

# ==================== Video Generation ====================

def generate_author(index: int) -> Author:
    """Generate a deterministic author based on index"""
    author_index = index % len(AUTHOR_NAMES)
    author_id = f"author_{author_index:03d}"
    
    return Author(
        id=author_id,
        name=AUTHOR_NAMES[author_index],
        avatar=AUTHOR_AVATARS[author_index]
    )

def generate_video(index: int) -> dict:
    """Generate a single video with deterministic data"""
    current_time = int(time.time() * 1000)
    timestamp = current_time - (index * 3600000)
    
    random.seed(index)
    
    author = generate_author(index)
    author_id = author.id
    
    # Check if current user follows this author
    is_following = author_id in follows_storage and CURRENT_USER_ID in follows_storage[author_id]
    
    video = {
        "id": f"{timestamp}_{index:05d}",
        "author": author.dict(),
        "caption": CAPTIONS[index % len(CAPTIONS)],
        "hashtags": ["fyp", "viral", "trending", f"tag{index % 100}"][:random.randint(3, 5)],
        "video_url": VIDEO_POOL[index % len(VIDEO_POOL)],
        "thumbnail": f"https://picsum.photos/400/800?random={index}",
        "stats": {
            "likes": random.randint(1000, 5000000),
            "comments": random.randint(100, 50000),
            "shares": random.randint(500, 200000)
        },
        "timestamp": timestamp,
        "is_following": is_following
    }
    
    random.seed()
    return video

def get_videos_before_timestamp(timestamp: Optional[int], limit: int) -> List[dict]:
    """Get videos with timestamp < cursor timestamp"""
    videos = []
    
    if timestamp is None:
        start_index = 0
    else:
        start_index = 0
        for i in range(TOTAL_VIDEOS):
            video_timestamp = int(time.time() * 1000) - (i * 3600000)
            if video_timestamp < timestamp:
                start_index = i
                break
        else:
            start_index = TOTAL_VIDEOS
    
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
            "save": "POST /videos/{video_id}/save",
            "follow": "POST /users/{user_id}/follow",
            "comments": "GET/POST /videos/{video_id}/comments",
            "health": "GET /health"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/videos", response_model=PaginatedResponse)
async def get_videos(
    limit: int = Query(VIDEOS_PER_PAGE, ge=1, le=50),
    cursor: Optional[str] = Query(None)
):
    """Get videos with timestamp-based cursor pagination"""
    
    cursor_timestamp = None
    if cursor:
        try:
            cursor_timestamp = int(cursor)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid cursor format")
    
    videos_data = get_videos_before_timestamp(cursor_timestamp, limit)
    
    if not videos_data:
        return PaginatedResponse(videos=[], next_cursor=None, has_more=False)
    
    videos = []
    for video_dict in videos_data:
        video_id = video_dict["id"]
        author_id = video_dict["author"]["id"]
        
        # Update likes from storage
        like_count = len(likes_storage.get(video_id, set()))
        if like_count > 0:
            video_dict["stats"]["likes"] = like_count
        
        # Update is_following status
        video_dict["is_following"] = author_id in follows_storage and CURRENT_USER_ID in follows_storage[author_id]
        
        videos.append(Video(**video_dict))
    
    last_video = videos[-1] if videos else None
    next_cursor = str(last_video.timestamp) if last_video and len(videos) == limit else None
    
    has_more = False
    if last_video:
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
    
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
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

@app.post("/videos/{video_id}/save")
async def save_video(video_id: str, action: SaveAction):
    """Save or unsave a video"""
    
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if video_id not in saves_storage:
        saves_storage[video_id] = set()
    
    if action.action == "save":
        saves_storage[video_id].add(CURRENT_USER_ID)
        action_type = "saved"
    else:
        saves_storage[video_id].discard(CURRENT_USER_ID)
        action_type = "unsaved"
    
    return {
        "success": True,
        "action": action_type,
        "video_id": video_id,
        "saves_count": len(saves_storage[video_id])
    }

@app.post("/users/{user_id}/follow")
async def follow_user(user_id: str, action: FollowAction):
    """Follow or unfollow a user"""
    
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid user ID")
    
    if user_id not in follows_storage:
        follows_storage[user_id] = set()
    
    if action.action == "follow":
        follows_storage[user_id].add(CURRENT_USER_ID)
        action_type = "followed"
    else:
        follows_storage[user_id].discard(CURRENT_USER_ID)
        action_type = "unfollowed"
    
    return {
        "success": True,
        "action": action_type,
        "user_id": user_id,
        "followers_count": len(follows_storage[user_id])
    }

@app.get("/users/{user_id}/followers")
async def get_followers(user_id: str):
    """Get followers count for a user"""
    
    if user_id not in follows_storage:
        return {"user_id": user_id, "followers": 0}
    
    return {"user_id": user_id, "followers": len(follows_storage[user_id])}

@app.get("/users/{user_id}/following")
async def get_following(user_id: str):
    """Get following count for a user"""
    
    # For now, return mock data
    # In real implementation, you'd count how many users this user follows
    following_count = 0
    for followers in follows_storage.values():
        if user_id in followers:
            following_count += 1
    
    return {"user_id": user_id, "following": following_count}

@app.post("/videos/{video_id}/comments")
async def add_comment(video_id: str, comment: CommentCreate):
    """Add a comment to a video"""
    
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
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
    
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if video_id in comments_storage:
        comments = comments_storage[video_id]
    else:
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
    total_saves = sum(len(users) for users in saves_storage.values())
    total_follows = sum(len(users) for users in follows_storage.values())
    total_comments = sum(len(comments) for comments in comments_storage.values())
    
    return {
        "total_videos": TOTAL_VIDEOS,
        "videos_with_likes": len(likes_storage),
        "total_likes": total_likes,
        "videos_with_saves": len(saves_storage),
        "total_saves": total_saves,
        "users_with_follows": len(follows_storage),
        "total_follows": total_follows,
        "videos_with_comments": len(comments_storage),
        "total_comments": total_comments,
        "pagination_type": "timestamp-based cursor"
    }

@app.get("/user/saved")
async def get_saved_videos():
    """Get saved videos for current user"""
    saved_video_ids = [vid for vid, users in saves_storage.items() if CURRENT_USER_ID in users]
    
    saved_videos = []
    for video_id in saved_video_ids[:20]:
        try:
            index = int(video_id.split('_')[1])
            video = generate_video(index)
            
            like_count = len(likes_storage.get(video_id, set()))
            if like_count > 0:
                video["stats"]["likes"] = like_count
            
            saved_videos.append(Video(**video))
        except (ValueError, IndexError):
            continue
    
    return {"saved_videos": saved_videos}
