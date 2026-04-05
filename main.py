import asyncio
import random
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yt_dlp

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store for our real TikTok data
video_cache = []

def fetch_real_tiktok_trending():
    """Uses yt-dlp to scrape the actual TikTok trending section"""
    # Using 'titles' and 'urls' from the actual TikTok trending page
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'playlist_items': '1-10',
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            # This hits the actual trending playlist on TikTok
            meta = ydl.extract_info("https://tiktok.com", download=False)
            results = []
            
            for entry in meta.get('entries', []):
                # Now we get the direct playable CDN link for each
                with yt_dlp.YoutubeDL({'format': 'best', 'quiet': True}) as ydl_inner:
                    v_info = ydl_inner.extract_info(entry['url'], download=False)
                    results.append({
                        "id": v_info.get('id'),
                        "video_url": v_info.get('url'), # REAL TIKTOK CDN LINK
                        "thumbnail": v_info.get('thumbnail'),
                        "caption": v_info.get('title'),
                        "author_name": f"@{v_info.get('uploader')}"
                    })
            return results
        except Exception as e:
            print(f"Scrape Error: {e}")
            return []

async def worker():
    """Background task to keep the feed fresh"""
    global video_cache
    while True:
        real_vids = fetch_real_tiktok_trending()
        if real_vids:
            video_cache = real_vids
            print(f"✅ Success: {len(video_cache)} Real TikToks Cached")
        await asyncio.sleep(600) # Refresh every 10 mins

@app.on_event("startup")
async def startup():
    asyncio.create_task(worker())

@app.get("/feed/live")
async def get_feed():
    return {"videos": video_cache}

@app.get("/")
def health():
    return {"status": "running"}
