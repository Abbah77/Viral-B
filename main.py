import asyncio
import random
import time
from typing import List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
from TikTokApi import TikTokApi

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- UTILITIES ---

async def get_trending_urls(count=5):
    """Discovery: Find trending TikTok page URLs"""
    urls = []
    try:
        async with TikTokApi() as api:
            await api.create_sessions(ms_tokens=["your_token"], num_sessions=1, sleep=1)
            async for video in api.trending.videos(count=count):
                urls.append(f"https://www.tiktok.com/@{video.author.username}/video/{video.id}")
    except Exception as e:
        print(f"Discovery Error: {e}")
        # Fallback to a few fixed trending-style videos if scraper is blocked
        urls = ["https://tiktok.com"] 
    return urls

def extract_stream_link(page_url):
    """Extraction: Get the direct .mp4 link from the page URL"""
    ydl_opts = {'format': 'best', 'quiet': True, 'no_warnings': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(page_url, download=False)
            return info.get('url')
        except:
            return None

# --- MODELS & API ---

class Video(BaseModel):
    id: str
    video_url: str
    caption: str
    author_name: str

@app.get("/feed/live")
async def live_feed():
    # 1. Discover 5 trending videos
    page_urls = await get_trending_urls(count=5)
    
    final_videos = []
    for url in page_urls:
        # 2. Extract live link
        stream_link = extract_stream_link(url)
        if stream_link:
            final_videos.append({
                "id": str(random.randint(1000, 9999)),
                "video_url": stream_link,
                "caption": "Real Trending Content 🔥",
                "author_name": "@trending_creator"
            })
            
    return {"videos": final_videos}
