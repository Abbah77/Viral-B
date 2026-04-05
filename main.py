import asyncio
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from TikTokApi import TikTokApi
import yt_dlp

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- THE PROXY ENGINE ---
# I've put a sample of your list here. You can add more from your list above.
PROXY_POOL = [
    "http://159.65.221.25:80", "http://4.195.16.140:80", "http://143.42.66.91:80",
    "http://91.132.92.231:80", "http://69.70.244.34:80", "http://147.231.163.133:80",
    "http://38.34.179.104:8447", "http://38.34.179.66:8444", "http://196.1.93.10:80"
]

video_cache = []

def get_stream_link(url):
    """Extracts the playable link using a random proxy"""
    proxy = random.choice(PROXY_POOL)
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'proxy': proxy,
        'socket_timeout': 10,
        'nocheckcertificate': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return {
                "id": info.get('id'),
                "video_url": info.get('url'),
                "thumbnail": info.get('thumbnail'),
                "caption": info.get('title', 'Trending Content'),
                "author": f"@{info.get('uploader', 'creator')}"
            }
        except:
            return None

async def discovery_worker():
    """The Engine: Runs in the background so your app is always fast"""
    while True:
        try:
            proxy = random.choice(PROXY_POOL)
            async with TikTokApi(proxy=proxy) as api:
                # This handles the 'msToken' and 'X-Bogus' automatically
                await api.create_sessions(num_sessions=1, sleep=1)
                
                async for video in api.trending.videos(count=10):
                    url = f"https://tiktok.com@{video.author.username}/video/{video.id}"
                    data = get_stream_link(url)
                    if data:
                        video_cache.append(data)
                        # Keep cache healthy (max 50 videos)
                        if len(video_cache) > 50: video_cache.pop(0)
            
            print(f"Engine Updated: {len(video_cache)} videos ready.")
            await asyncio.sleep(300) # Re-scrape every 5 minutes
        except Exception as e:
            print(f"Worker Error (Retrying): {e}")
            await asyncio.sleep(30)

@app.on_event("startup")
async def startup_event():
    # Start the engine the moment the server turns on
    asyncio.create_task(discovery_worker())

@app.get("/feed/live")
async def get_feed():
    if not video_cache:
        return {"status": "loading", "videos": []}
    # Return 5 random videos from our fresh cache
    return {"videos": random.sample(video_cache, min(len(video_cache), 5))}

@app.get("/")
def health():
    return {"status": "online"}
