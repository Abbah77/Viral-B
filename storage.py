from typing import Dict, Set, List
from .models import Comment

# In-memory storage for likes (video_id -> set of user_ids)
likes_storage: Dict[str, Set[str]] = {}

# In-memory storage for comments (video_id -> list of comments)
comments_storage: Dict[str, List[Comment]] = {}
