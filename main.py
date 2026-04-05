import asyncio
import random
from fastapi import FastAPI
from TikTokApi import TikTokApi
import yt_dlp
from playwright_stealth.stealth import stealth_async

app = FastAPI()
video_cache = [] # Our "Internal CDN" buffer

# 1. THE EXTRACTOR (yt-dlp)
def get_stream_link(url):
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'socket_timeout': 10
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return {
                "url": info.get('url'),
                "thumbnail": info.get('thumbnail'),
                "title": info.get('title'),
                "author": info.get('uploader')
            }
        except: return None

# 2. THE DISCOVERY (Background Worker)
async def discovery_worker():
    """Constantly refills the video_cache so the app is never empty"""
    while True:
        try:
            async with TikTokApi() as api:
                # 'Stealth' mode makes your Render server look like a home PC
                await api.create_sessions(ms_tokens=["your_token"], num_sessions=1, sleep=1)
                async for video in api.trending.videos(count=10):
                    url = f"https://tiktok.com@{video.author.username}/video/{video.id}"
                    data = get_stream_link(url)
                    if data:
                        video_cache.append(data)
                        if len(video_cache) > 50: video_cache.pop(0) # Keep fresh
            await asyncio.sleep(300) # Refresh every 5 mins
        except Exception as e:
            print(f"Worker Error: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(discovery_worker())

# 3. THE API (Instant Response)
@app.get("/feed/unlimited")
async def get_feed():
    if not video_cache:
        return {"status": "loading", "videos": []}
    
    # Return a random slice for "infinite" variety
    sample = random.sample(video_cache, min(len(video_cache), 5))
    return {"videos": sample}
