"""
Viral App - Backend API
FastAPI server with JWT authentication and timestamp-based cursor pagination
"""

import time
import random
import os
from datetime import datetime
from typing import Optional, List, Dict, Set, Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import jwt
import requests

# ============================================================================
# Configuration
# ============================================================================

SUPABASE_URL = "https://alslcgisopslmfucwlwf.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFsc2xjZ2lzb3BzbG1mdWN3bHdmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQwODk4NjUsImV4cCI6MjA4OTY2NTg2NX0.TzGF7XEekLktZ3UueUUNKrHK2AtJKbfjcB6lPu-A4Kg"

# Video Generation Constants
TOTAL_VIDEOS = 10000
VIDEOS_PER_PAGE = 10

# JWT Settings
JWT_ALGORITHM = "HS256"
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "your-supabase-jwt-secret-here")

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
    action: str = Field(..., pattern="^(like|unlike)$")

class SaveAction(BaseModel):
    action: str = Field(..., pattern="^(save|unsave)$")

class FollowAction(BaseModel):
    action: str = Field(..., pattern="^(follow|unfollow)$")

class UserProfile(BaseModel):
    id: str
    username: str
    full_name: str
    display_name: str
    avatar_url: Optional[str]
    bio: Optional[str]
    follower_count: int
    following_count: int
    likes_received: int

# ============================================================================
# App Setup
# ============================================================================

app = FastAPI(
    title="Viral API",
    version="1.0.0",
    description="Backend API for Viral social media app with JWT authentication"
)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer(auto_error=False)

# ============================================================================
# Storage (In-memory for demo)
# ============================================================================

class InMemoryStorage:
    """In-memory storage for user interactions (mock backend)"""
    
    def __init__(self):
        self.likes: Dict[str, Set[str]] = {}
        self.saves: Dict[str, Set[str]] = {}
        self.follows: Dict[str, Set[str]] = {}
        self.comments: Dict[str, List[Comment]] = {}
    
    def like_video(self, video_id: str, user_id: str) -> int:
        if video_id not in self.likes:
            self.likes[video_id] = set()
        self.likes[video_id].add(user_id)
        return len(self.likes[video_id])
    
    def unlike_video(self, video_id: str, user_id: str) -> int:
        if video_id in self.likes:
            self.likes[video_id].discard(user_id)
        return len(self.likes.get(video_id, set()))
    
    def is_liked(self, video_id: str, user_id: str) -> bool:
        return user_id in self.likes.get(video_id, set())
    
    def save_video(self, video_id: str, user_id: str) -> int:
        if video_id not in self.saves:
            self.saves[video_id] = set()
        self.saves[video_id].add(user_id)
        return len(self.saves[video_id])
    
    def unsave_video(self, video_id: str, user_id: str) -> int:
        if video_id in self.saves:
            self.saves[video_id].discard(user_id)
        return len(self.saves.get(video_id, set()))
    
    def is_saved(self, video_id: str, user_id: str) -> bool:
        return user_id in self.saves.get(video_id, set())
    
    def follow_user(self, target_user_id: str, follower_id: str) -> int:
        if target_user_id not in self.follows:
            self.follows[target_user_id] = set()
        self.follows[target_user_id].add(follower_id)
        return len(self.follows[target_user_id])
    
    def unfollow_user(self, target_user_id: str, follower_id: str) -> int:
        if target_user_id in self.follows:
            self.follows[target_user_id].discard(follower_id)
        return len(self.follows.get(target_user_id, set()))
    
    def is_following(self, target_user_id: str, follower_id: str) -> bool:
        return follower_id in self.follows.get(target_user_id, set())
    
    def add_comment(self, video_id: str, comment: Comment) -> List[Comment]:
        if video_id not in self.comments:
            self.comments[video_id] = []
        self.comments[video_id].insert(0, comment)
        return self.comments[video_id]
    
    def get_comments(self, video_id: str) -> List[Comment]:
        return self.comments.get(video_id, [])

# Global storage instance
storage = InMemoryStorage()

# ============================================================================
# Video Data Generation
# ============================================================================

# Google video URLs pool (10 sample videos)
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

# Author names and avatars
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

def generate_author(index: int) -> Author:
    """Generate deterministic author based on index"""
    author_index = index % len(AUTHOR_NAMES)
    author_id = f"author_{author_index:03d}"
    
    return Author(
        id=author_id,
        name=AUTHOR_NAMES[author_index],
        avatar=AUTHOR_AVATARS[author_index]
    )

def generate_video(index: int, current_user_id: Optional[str] = None) -> dict:
    """Generate a single video with deterministic data"""
    current_time = int(time.time() * 1000)
    timestamp = current_time - (index * 3600000)
    
    # Seed random for deterministic data
    random.seed(index)
    
    author = generate_author(index)
    
    # Check if current user follows this author
    is_following = False
    if current_user_id:
        is_following = storage.is_following(author.id, current_user_id)
    
    # Generate hashtags
    hashtag_pool = ["fyp", "viral", "trending", f"tag{index % 100}"]
    num_hashtags = random.randint(3, 5)
    hashtags = hashtag_pool[:num_hashtags]
    
    video = {
        "id": f"{timestamp}_{index:05d}",
        "author": author.dict(),
        "caption": CAPTIONS[index % len(CAPTIONS)],
        "hashtags": hashtags,
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
    
    # Override likes count from storage if exists
    video_id = video["id"]
    if current_user_id and storage.is_liked(video_id, current_user_id):
        storage_likes = len(storage.likes.get(video_id, set()))
        if storage_likes > 0:
            video["stats"]["likes"] = storage_likes
    
    random.seed()
    return video

def get_videos_before_timestamp(
    timestamp: Optional[int], 
    limit: int, 
    current_user_id: Optional[str] = None
) -> List[dict]:
    """Get videos with timestamp < cursor timestamp"""
    videos = []
    
    if timestamp is None:
        start_index = 0
    else:
        # Find index where timestamp is less than cursor
        start_index = 0
        for i in range(TOTAL_VIDEOS):
            video_timestamp = int(time.time() * 1000) - (i * 3600000)
            if video_timestamp < timestamp:
                start_index = i
                break
        else:
            start_index = TOTAL_VIDEOS
    
    for i in range(start_index, min(start_index + limit, TOTAL_VIDEOS)):
        video = generate_video(i, current_user_id)
        videos.append(video)
    
    return videos

# ============================================================================
# Authentication Dependencies
# ============================================================================

async def verify_supabase_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Optional[dict]:
    """
    Verify Supabase JWT token and return user info.
    Returns None if no token provided, raises HTTPException if token is invalid.
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    
    try:
        # Decode and verify JWT
        # In production, you'd verify against Supabase's JWT secret
        # For now, we'll decode without verification for demo
        # but still validate structure
        
        # Unverified decode to get user info
        payload = jwt.decode(
            token, 
            options={"verify_signature": False},
            algorithms=[JWT_ALGORITHM]
        )
        
        # Validate required fields
        if "sub" not in payload or "email" not in payload:
            raise HTTPException(status_code=401, detail="Invalid token structure")
        
        return {
            "id": payload["sub"],
            "email": payload["email"],
            "user_metadata": payload.get("user_metadata", {}),
            "credentials": credentials  # Store credentials for Supabase calls
        }
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")

async def get_current_user(
    token_info: Optional[dict] = Depends(verify_supabase_token)
) -> str:
    """
    Get current user ID from JWT token.
    Returns "anonymous" for unauthenticated requests (for demo purposes).
    """
    if token_info:
        return token_info["id"]
    
    # For demo, return a default user ID for unauthenticated requests
    # In production, you might want to raise 401 instead
    return "anonymous_user"

# ============================================================================
# API Endpoints
# ============================================================================

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "message": "Viral API is running with JWT authentication",
        "status": "healthy",
        "version": "1.0.0",
        "endpoints": {
            "videos": "GET /videos?limit=10&cursor=<timestamp>",
            "like": "POST /videos/{video_id}/like",
            "save": "POST /videos/{video_id}/save",
            "follow": "POST /users/{user_id}/follow",
            "comments": "GET/POST /videos/{video_id}/comments",
            "profile": "GET /profile",
            "health": "GET /health"
        },
        "authentication": "Bearer token from Supabase"
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "storage_stats": {
            "total_likes": sum(len(users) for users in storage.likes.values()),
            "total_saves": sum(len(users) for users in storage.saves.values()),
            "total_follows": sum(len(users) for users in storage.follows.values()),
            "total_comments": sum(len(comments) for comments in storage.comments.values())
        }
    }

# ============================================================================
# Video Feed Endpoints
# ============================================================================

@app.get("/videos", response_model=PaginatedResponse)
async def get_videos(
    current_user_id: str = Depends(get_current_user),
    limit: int = Query(VIDEOS_PER_PAGE, ge=1, le=50),
    cursor: Optional[str] = Query(None)
):
    """
    Get videos with timestamp-based cursor pagination.
    Requires JWT authentication (optional for demo).
    """
    cursor_timestamp = None
    if cursor:
        try:
            cursor_timestamp = int(cursor)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid cursor format")
    
    videos_data = get_videos_before_timestamp(
        cursor_timestamp, 
        limit, 
        current_user_id if current_user_id != "anonymous_user" else None
    )
    
    if not videos_data:
        return PaginatedResponse(videos=[], next_cursor=None, has_more=False)
    
    videos = []
    for video_dict in videos_data:
        video_id = video_dict["id"]
        author_id = video_dict["author"]["id"]
        
        # Update likes from storage if user is authenticated
        if current_user_id != "anonymous_user":
            storage_likes = len(storage.likes.get(video_id, set()))
            if storage_likes > 0:
                video_dict["stats"]["likes"] = storage_likes
        
        # Update following status
        video_dict["is_following"] = storage.is_following(author_id, current_user_id)
        
        videos.append(Video(**video_dict))
    
    last_video = videos[-1] if videos else None
    next_cursor = str(last_video.timestamp) if last_video and len(videos) == limit else None
    
    # Check if there are more videos
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

# ============================================================================
# Interaction Endpoints
# ============================================================================

@app.post("/videos/{video_id}/like")
async def like_video(
    video_id: str,
    action: LikeAction,
    current_user_id: str = Depends(get_current_user)
):
    """Like or unlike a video (requires authentication)"""
    
    if current_user_id == "anonymous_user":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Validate video ID format
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if action.action == "like":
        likes_count = storage.like_video(video_id, current_user_id)
        action_type = "liked"
    else:
        likes_count = storage.unlike_video(video_id, current_user_id)
        action_type = "unliked"
    
    return {
        "success": True,
        "action": action_type,
        "video_id": video_id,
        "likes_count": likes_count
    }

@app.post("/videos/{video_id}/save")
async def save_video(
    video_id: str,
    action: SaveAction,
    current_user_id: str = Depends(get_current_user)
):
    """Save or unsave a video (requires authentication)"""
    
    if current_user_id == "anonymous_user":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    if action.action == "save":
        saves_count = storage.save_video(video_id, current_user_id)
        action_type = "saved"
    else:
        saves_count = storage.unsave_video(video_id, current_user_id)
        action_type = "unsaved"
    
    return {
        "success": True,
        "action": action_type,
        "video_id": video_id,
        "saves_count": saves_count
    }

@app.post("/users/{user_id}/follow")
async def follow_user(
    user_id: str,
    action: FollowAction,
    current_user_id: str = Depends(get_current_user)
):
    """Follow or unfollow a user (requires authentication)"""
    
    if current_user_id == "anonymous_user":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid user ID")
    
    # Prevent self-follow
    if user_id == current_user_id:
        raise HTTPException(status_code=400, detail="You cannot follow yourself")
    
    if action.action == "follow":
        followers_count = storage.follow_user(user_id, current_user_id)
        action_type = "followed"
    else:
        followers_count = storage.unfollow_user(user_id, current_user_id)
        action_type = "unfollowed"
    
    return {
        "success": True,
        "action": action_type,
        "user_id": user_id,
        "followers_count": followers_count
    }

# ============================================================================
# Comment Endpoints
# ============================================================================

@app.post("/videos/{video_id}/comments")
async def add_comment(
    video_id: str,
    comment: CommentCreate,
    current_user_id: str = Depends(get_current_user),
    token_info: Optional[dict] = Depends(verify_supabase_token)
):
    """Add a comment to a video (requires authentication)"""
    
    if current_user_id == "anonymous_user":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Get user info from token or profile
    user_name = token_info.get("user_metadata", {}).get("username", f"@{current_user_id[:8]}") if token_info else f"@{current_user_id[:8]}"
    user_avatar = token_info.get("user_metadata", {}).get("avatar_url", "https://randomuser.me/api/portraits/women/8.jpg") if token_info else "https://randomuser.me/api/portraits/women/8.jpg"
    
    new_comment = Comment(
        id=f"cmt_{int(time.time() * 1000)}_{random.randint(1000, 9999)}",
        user=CommentUser(
            name=user_name,
            avatar=user_avatar
        ),
        text=comment.text,
        likes=0,
        time="Just now"
    )
    
    storage.add_comment(video_id, new_comment)
    
    return {
        "success": True,
        "comment": new_comment
    }

@app.get("/videos/{video_id}/comments")
async def get_comments(
    video_id: str,
    current_user_id: str = Depends(get_current_user)
):
    """Get comments for a video"""
    
    if not video_id or len(video_id.split('_')) != 2:
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    comments = storage.get_comments(video_id)
    
    # Generate mock comments if none exist
    if not comments:
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
        
        storage.comments[video_id] = comments
    
    return {"comments": comments}

# ============================================================================
# User Profile Endpoints
# ============================================================================

@app.get("/profile", response_model=UserProfile)
async def get_profile(
    current_user_id: str = Depends(get_current_user),
    token_info: Optional[dict] = Depends(verify_supabase_token)
):
    """
    Get current user's profile from Supabase.
    Requires authentication.
    """
    
    if current_user_id == "anonymous_user":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not token_info:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    
    try:
        # Prepare headers for Supabase request
        supabase_headers = {
            "apikey": SUPABASE_ANON_KEY,
            "Authorization": f"Bearer {token_info['credentials'].credentials}"
        }
        
        # Get profile data
        profile_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            headers=supabase_headers,
            params={"id": f"eq.{current_user_id}", "select": "*"}
        )
        
        if profile_response.status_code != 200:
            raise HTTPException(status_code=500, detail="Failed to fetch profile")
        
        profiles = profile_response.json()
        if not profiles:
            raise HTTPException(status_code=404, detail="Profile not found")
        
        profile = profiles[0]
        
        # Get follower count
        followers_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/follows",
            headers=supabase_headers,
            params={"following_id": f"eq.{current_user_id}", "select": "*", "limit": 0}
        )
        follower_count = 0
        if followers_response.status_code == 200:
            content_range = followers_response.headers.get("content-range", "0-0/0")
            follower_count = int(content_range.split("/")[-1]) if "/" in content_range else 0
        
        # Get following count
        following_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/follows",
            headers=supabase_headers,
            params={"follower_id": f"eq.{current_user_id}", "select": "*", "limit": 0}
        )
        following_count = 0
        if following_response.status_code == 200:
            content_range = following_response.headers.get("content-range", "0-0/0")
            following_count = int(content_range.split("/")[-1]) if "/" in content_range else 0
        
        # Get total likes received
        videos_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/videos",
            headers=supabase_headers,
            params={"author_id": f"eq.{current_user_id}", "select": "likes_count"}
        )
        
        total_likes = 0
        if videos_response.status_code == 200:
            videos = videos_response.json()
            total_likes = sum(v.get("likes_count", 0) for v in videos)
        
        return UserProfile(
            id=profile["id"],
            username=profile.get("username", ""),
            full_name=profile.get("full_name", ""),
            display_name=profile.get("display_name", ""),
            avatar_url=profile.get("avatar_url"),
            bio=profile.get("bio"),
            follower_count=follower_count,
            following_count=following_count,
            likes_received=total_likes
        )
        
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Supabase request failed: {str(e)}")

@app.get("/user/saved")
async def get_saved_videos(
    current_user_id: str = Depends(get_current_user)
):
    """Get saved videos for current user (from in-memory storage)"""
    
    if current_user_id == "anonymous_user":
        raise HTTPException(status_code=401, detail="Authentication required")
    
    saved_video_ids = [
        vid for vid, users in storage.saves.items() 
        if current_user_id in users
    ]
    
    saved_videos = []
    for video_id in saved_video_ids[:20]:
        try:
            index = int(video_id.split('_')[1])
            video = generate_video(index, current_user_id)
            
            # Update likes from storage
            storage_likes = len(storage.likes.get(video_id, set()))
            if storage_likes > 0:
                video["stats"]["likes"] = storage_likes
            
            saved_videos.append(Video(**video))
        except (ValueError, IndexError):
            continue
    
    return {"saved_videos": saved_videos}

@app.get("/user/videos")
async def get_user_videos(
    current_user_id: str = Depends(get_current_user)
):
    """Get videos created by the current user (mock data)"""
    
    # For mock backend, return videos created by this user
    # In real implementation, this would query Supabase
    
    user_videos = []
    for i in range(0, min(TOTAL_VIDEOS, 50), 10):
        author = generate_author(i)
        if author.id == current_user_id or i < 5:  # Mock: return first 5 videos for user
            video = generate_video(i, current_user_id)
            user_videos.append(Video(**video))
    
    return {"videos": user_videos[:10]}

# ============================================================================
# Statistics Endpoint
# ============================================================================

@app.get("/stats")
async def get_stats():
    """Get API statistics"""
    total_likes = sum(len(users) for users in storage.likes.values())
    total_saves = sum(len(users) for users in storage.saves.values())
    total_follows = sum(len(users) for users in storage.follows.values())
    total_comments = sum(len(comments) for comments in storage.comments.values())
    
    return {
        "total_videos": TOTAL_VIDEOS,
        "videos_with_likes": len(storage.likes),
        "total_likes": total_likes,
        "videos_with_saves": len(storage.saves),
        "total_saves": total_saves,
        "users_with_follows": len(storage.follows),
        "total_follows": total_follows,
        "videos_with_comments": len(storage.comments),
        "total_comments": total_comments,
        "pagination_type": "timestamp-based cursor",
        "authentication": "Supabase JWT"
    }

# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return {
        "error": True,
        "status_code": exc.status_code,
        "detail": exc.detail,
        "path": request.url.path
    }

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    return {
        "error": True,
        "status_code": 500,
        "detail": "Internal server error",
        "path": request.url.path
    }

# ============================================================================
# Run with: uvicorn main:app --reload
# ============================================================================
