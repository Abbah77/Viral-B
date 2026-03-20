from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


class Author(BaseModel):
    name: str
    avatar: str


class Stats(BaseModel):
    likes: int
    comments: int
    shares: int
    original_likes: Optional[int] = None  # For internal use


class Video(BaseModel):
    id: str
    author: Author
    caption: str
    hashtags: List[str]
    video_url: str
    thumbnail: str
    stats: Stats
    comments: List[Dict[str, Any]] = []
    timestamp: Optional[int] = None


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
    action: str = Field(..., regex="^(like|unlike)$")


class PaginatedResponse(BaseModel):
    videos: List[Video]
    next_cursor: Optional[str]
    has_more: bool


class VideoResponse(BaseModel):
    video: Video
    is_liked: bool = False
