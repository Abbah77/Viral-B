import random
import time
from typing import List, Optional

# Google video URLs pool (10 test videos)
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

# Caption templates (for dynamic generation)
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

# Author (same for all videos for simplicity)
AUTHOR = {
    "name": "@tiktok_user",
    "avatar": "https://randomuser.me/api/portraits/women/8.jpg"
}


def generate_videos_batch(cursor_timestamp: int, limit: int, cursor: Optional[str] = None) -> List[dict]:
    """
    Generate a batch of videos with deterministic metadata based on video ID
    """
    videos = []
    
    # Determine starting index
    if cursor:
        try:
            # Extract index from cursor (format: timestamp_index)
            start_index = int(cursor.split('_')[1]) + 1
        except (ValueError, IndexError):
            start_index = 0
    else:
        start_index = 0
    
    # Generate videos
    for i in range(start_index, start_index + limit):
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
                "original_likes": generate_likes(i)  # Store original for reference
            },
            "timestamp": generate_timestamp(i),
            "comments": []  # Comments loaded separately
        }
        
        videos.append(video)
    
    return videos


def generate_video_id(index: int) -> str:
    """
    Generate deterministic video ID with timestamp and index
    Format: timestamp_index (e.g., 1700000000_00123)
    """
    timestamp = generate_timestamp(index)
    return f"{timestamp}_{index:05d}"


def generate_timestamp(index: int) -> int:
    """
    Generate deterministic timestamp for video
    Newer videos (higher index) have more recent timestamps
    """
    base_time = int(time.time() * 1000)  # Current time in milliseconds
    # Older videos have older timestamps
    return base_time - (index * 1000 * 60 * 60 * 24)  # Subtract 1 day per video


def generate_caption(index: int) -> str:
    """
    Generate deterministic caption based on video index
    """
    template = CAPTION_TEMPLATES[index % len(CAPTION_TEMPLATES)]
    emojis = ["😂", "🔥", "✨", "😱", "🎉", "❤️", "🤯", "💯", "👀", "🌟"]
    suffix = emojis[index % len(emojis)]
    return template.format(suffix)


def generate_hashtags(index: int) -> List[str]:
    """
    Generate deterministic hashtags based on video index
    """
    pool = HASHTAG_POOLS[index % len(HASHTAG_POOLS)]
    # Add 1-2 trending hashtags
    trending = ["fyp", "viral", "trending"]
    result = pool.copy()
    result.extend(random.sample(trending, random.randint(1, 2)))
    return result[:5]  # Max 5 hashtags


def generate_likes(index: int) -> int:
    """
    Generate deterministic like count based on video index
    """
    # Seed random with index for deterministic but varied numbers
    random.seed(index)
    likes = random.randint(1000, 5000000)
    random.seed()  # Reset seed
    return likes


def generate_comments(index: int) -> int:
    """
    Generate deterministic comment count based on video index
    """
    random.seed(index + 10000)
    comments = random.randint(100, 50000)
    random.seed()
    return comments


def generate_shares(index: int) -> int:
    """
    Generate deterministic share count based on video index
    """
    random.seed(index + 20000)
    shares = random.randint(500, 200000)
    random.seed()
    return shares
