from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional, List
import time
import random
from datetime import datetime

from .models import Video, VideoResponse, Comment, CommentCreate, LikeAction, PaginatedResponse
from .storage import likes_storage, comments_storage
from .generators import generate_videos_batch, VIDEO_POOL

app = FastAPI(title="Viral API", version="1.0.0")

# Configure CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development - restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
TOTAL_VIDEOS = 10000  # Total virtual videos available
VIDEOS_PER_PAGE = 10  # Default limit per request

# In-memory storage for likes (video_id -> set of user_ids)
# For now, we'll simulate with a single user "current_user"
CURRENT_USER_ID = "user_001"


@app.get("/")
async def root():
    return {"message": "Viral API is running", "status": "healthy"}


@app.get("/api/videos", response_model=PaginatedResponse)
async def get_videos(
    limit: int = Query(VIDEOS_PER_PAGE, ge=1, le=50, description="Number of videos to return"),
    cursor: Optional[str] = Query(None, description="Timestamp-based cursor (video ID)")
):
    """
    Get paginated videos with cursor-based pagination.
    Uses timestamp-based cursors (video_id format: timestamp_random)
    """
    # Parse cursor
    if cursor:
        try:
            # Cursor format: timestamp_random (e.g., 1700000000_abc123)
            cursor_timestamp = int(cursor.split('_')[0])
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Invalid cursor format")
    else:
        cursor_timestamp = int(time.time() * 1000)  # Current timestamp in milliseconds
    
    # Generate videos batch
    videos_data = generate_videos_batch(cursor_timestamp, limit, cursor)
    
    if not videos_data:
        return PaginatedResponse(
            videos=[],
            next_cursor=None,
            has_more=False
        )
    
    # Convert to Video objects and add like counts from storage
    videos = []
    for video_dict in videos_data:
        video_id = video_dict["id"]
        
        # Get like count from storage
        like_count = len(likes_storage.get(video_id, set()))
        
        # Update stats with actual like count
        video_dict["stats"]["likes"] = like_count if like_count > 0 else video_dict["stats"]["original_likes"]
        
        # Check if current user liked this video
        is_liked = video_id in likes_storage and CURRENT_USER_ID in likes_storage[video_id]
        
        videos.append(Video(**video_dict))
    
    # Get next cursor (last video's timestamp)
    last_video = videos[-1] if videos else None
    next_cursor = last_video.id if last_video and len(videos) == limit else None
    
    # Determine if there are more videos
    # For dynamic generation, we always have more until we hit TOTAL_VIDEOS
    last_index = int(last_video.id.split('_')[1]) if last_video else 0
    has_more = last_index < TOTAL_VIDEOS - 1 if last_video else True
    
    return PaginatedResponse(
        videos=videos,
        next_cursor=next_cursor,
        has_more=has_more
    )


@app.post("/api/videos/{video_id}/like")
async def like_video(video_id: str, action: LikeAction):
    """
    Like or unlike a video
    """
    # Validate video exists (check if ID is within range)
    try:
        video_index = int(video_id.split('_')[1])
        if video_index < 0 or video_index >= TOTAL_VIDEOS:
            raise HTTPException(status_code=404, detail="Video not found")
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Initialize storage for this video if not exists
    if video_id not in likes_storage:
        likes_storage[video_id] = set()
    
    if action.action == "like":
        likes_storage[video_id].add(CURRENT_USER_ID)
        action_type = "liked"
    else:  # unlike
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
    """
    Add a comment to a video
    """
    # Validate video exists
    try:
        video_index = int(video_id.split('_')[1])
        if video_index < 0 or video_index >= TOTAL_VIDEOS:
            raise HTTPException(status_code=404, detail="Video not found")
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Create new comment
    new_comment = Comment(
        id=f"cmt_{int(time.time() * 1000)}_{random.randint(1000, 9999)}",
        user={
            "name": "@current_user",
            "avatar": "https://randomuser.me/api/portraits/women/8.jpg"
        },
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
    """
    Get comments for a video
    """
    # Validate video exists
    try:
        video_index = int(video_id.split('_')[1])
        if video_index < 0 or video_index >= TOTAL_VIDEOS:
            raise HTTPException(status_code=404, detail="Video not found")
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid video ID format")
    
    # Get comments from storage or generate mock comments
    if video_id in comments_storage:
        comments = comments_storage[video_id]
    else:
        # Generate mock comments for new videos
        comments = generate_mock_comments(video_id)
        comments_storage[video_id] = comments
    
    return {"comments": comments}


def generate_mock_comments(video_id: str) -> List[dict]:
    """
    Generate mock comments for a video
    """
    num_comments = random.randint(0, 5)
    comments = []
    
    comment_templates = [
        "This is amazing! 🔥",
        "Great content! 👏",
        "Love this video! ❤️",
        "So funny! 😂",
        "Can't stop watching!",
        "Best video ever!",
        "Keep up the good work!",
        "This made my day! ✨",
        "So creative! 🎨",
        "Wow! Just wow! 🤯"
    ]
    
    for i in range(num_comments):
        comment = Comment(
            id=f"cmt_{video_id}_{i}",
            user={
                "name": f"@user_{random.randint(100, 999)}",
                "avatar": f"https://randomuser.me/api/portraits/{random.choice(['men', 'women'])}/{random.randint(1, 50)}.jpg"
            },
            text=random.choice(comment_templates),
            likes=random.randint(0, 1000),
            time=f"{random.randint(1, 24)}h ago"
        )
        comments.append(comment)
    
    return comments


@app.get("/api/health")
async def health_check():
    """
    Health check endpoint
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "total_videos": TOTAL_VIDEOS,
        "active_likes": len(likes_storage),
        "active_comments": len(comments_storage)
    }


# Optional: Stats endpoint for debugging
@app.get("/api/stats")
async def get_stats():
    """
    Get API statistics (for debugging)
    """
    total_likes = sum(len(users) for users in likes_storage.values())
    total_comments = sum(len(comments) for comments in comments_storage.values())
    
    return {
        "total_videos": TOTAL_VIDEOS,
        "videos_with_likes": len(likes_storage),
        "total_likes": total_likes,
        "videos_with_comments": len(comments_storage),
        "total_comments": total_comments,
        "storage": {
            "likes": {k: list(v) for k, v in list(likes_storage.items())[:5]},  # Show first 5
            "comments": {k: len(v) for k, v in list(comments_storage.items())[:5]}
        }
    }
