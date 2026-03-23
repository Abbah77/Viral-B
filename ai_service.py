"""
AI Service for Viral App - FastAPI Wrapper
Integrates with the existing ai.py recommendation engine
"""

import asyncio
import logging
import os
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from contextlib import asynccontextmanager

# Import your existing AI engine
from ai import (
    ProductionConfig, 
    FeedService,
)

# ============================================================================
# Configuration
# ============================================================================

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Global AI service instance
ai_feed_service = None

# ============================================================================
# Pydantic Models for AI Endpoints
# ============================================================================

class AISignal(BaseModel):
    video_id: str
    signal_type: str
    timestamp: int
    user_id: str
    value: Optional[float] = None
    video_duration: Optional[float] = None
    session_id: Optional[str] = None

class AIBatchRequest(BaseModel):
    signals: List[AISignal]

class AIBatchResponse(BaseModel):
    success: bool
    processed_count: int
    errors: List[str] = []

class AIVideoScore(BaseModel):
    video_id: str
    score: float
    engagement: Optional[float] = None
    freshness: Optional[float] = None
    personalization: Optional[float] = None
    trending: Optional[float] = None

class AIPersonalizedFeedResponse(BaseModel):
    feed: List[AIVideoScore]
    source: str
    latency_ms: float
    cached: bool
    candidates_generated: int

class AIUserProfileResponse(BaseModel):
    user_id: str
    user_tier: str
    total_engagement: int
    trust_score: float
    top_interests: List[Dict[str, float]]
    top_creators: List[Dict[str, float]]
    top_categories: List[Dict[str, float]]

class AIHealthResponse(BaseModel):
    status: str
    redis_connected: bool
    service_initialized: bool
    timestamp: str

# ============================================================================
# Lifespan Manager
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ai_feed_service
    
    logger.info("🚀 Initializing AI Service...")
    try:
        config = ProductionConfig()
        redis_url = os.environ.get('REDIS_URL', config.redis_url)
        config.redis_url = redis_url
        logger.info(f"Using Redis URL: {redis_url[:20]}..." if redis_url else "No Redis URL")
        
        ai_feed_service = FeedService(config)
        await ai_feed_service.initialize()
        logger.info("✅ AI Service initialized successfully")
    except Exception as e:
        logger.error(f"❌ Failed to initialize AI Service: {e}")
        ai_feed_service = None
    
    yield
    
    logger.info("🛑 Shutting down AI Service...")
    if ai_feed_service:
        await ai_feed_service.close()
    logger.info("✅ AI Service shutdown complete")

# ============================================================================
# FastAPI App (NO /ai prefix in routes!)
# ============================================================================

ai_app = FastAPI(
    title="Viral AI Service",
    version="1.0.0",
    lifespan=lifespan
)

ai_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# Helper Functions
# ============================================================================

def get_ai_service():
    if ai_feed_service is None:
        raise HTTPException(status_code=503, detail="AI Service not initialized")
    return ai_feed_service

def signal_type_to_ai_format(signal: AISignal) -> Dict:
    type_mapping = {
        'complete_watch': 'complete_watch',
        'rewatch': 'watch_75pct',
        'like': 'like',
        'unlike': 'unlike',
        'comment': 'comment',
        'share': 'share',
        'save': 'save',
        'unsave': 'unsave',
        'follow_after_view': 'follow',
        'unfollow': 'unfollow',
        'profile_visit': 'like',
        'seek_forward': 'watch_75pct',
        'seek_back': 'watch_75pct',
        'skip': 'skip_early',
        'watch_time': 'watch_50pct',
    }
    
    interaction_type = type_mapping.get(signal.signal_type, signal.signal_type)
    
    return {
        'type': interaction_type,
        'creator_id': None,
        'category': None,
        'tags': [],
        'watch_time': signal.value or 0,
        'duration': signal.video_duration or 60,
        'timestamp': signal.timestamp / 1000 if signal.timestamp > 9999999999 else signal.timestamp
    }

# ============================================================================
# AI Endpoints - NO /ai prefix (mounting adds it)
# ============================================================================

@ai_app.get("/health", response_model=AIHealthResponse)  # ← REMOVED /ai/
async def ai_health():
    service = ai_feed_service
    
    redis_connected = False
    if service and service.redis_client and service.redis_client.client:
        try:
            await service.redis_client.client.ping()
            redis_connected = True
        except:
            pass
    
    return AIHealthResponse(
        status="healthy" if service and redis_connected else "degraded",
        redis_connected=redis_connected,
        service_initialized=service is not None,
        timestamp=datetime.now().isoformat()
    )

@ai_app.post("/batch", response_model=AIBatchResponse)  # ← REMOVED /ai/
async def process_batch_signals(
    request: AIBatchRequest,
    background_tasks: BackgroundTasks
):
    service = get_ai_service()
    errors = []
    processed = 0
    
    async def process_signals():
        nonlocal processed
        for signal in request.signals:
            try:
                interaction = signal_type_to_ai_format(signal)
                
                reward_map = {
                    'complete_watch': 1.0, 'rewatch': 0.9, 'like': 0.8,
                    'comment': 0.7, 'share': 1.0, 'save': 0.85,
                    'follow_after_view': 1.0, 'profile_visit': 0.5,
                    'seek_forward': 0.4, 'seek_back': 0.4, 'watch_time': 0.3,
                    'unlike': 0.0, 'unsave': 0.0, 'unfollow': 0.0, 'skip': 0.0,
                }
                
                reward = reward_map.get(signal.signal_type, 0.5)
                
                await service.user_profiles.update_profile(
                    signal.user_id, interaction, reward
                )
                
                await service.video_analytics.update_stats(
                    signal.video_id, signal.signal_type
                )
                
                processed += 1
                
            except Exception as e:
                logger.error(f"Error processing signal: {e}")
                errors.append(f"{signal.signal_type}:{signal.video_id}:{str(e)}")
    
    background_tasks.add_task(process_signals)
    
    return AIBatchResponse(
        success=True,
        processed_count=len(request.signals),
        errors=errors
    )

@ai_app.get("/feed/{user_id}", response_model=AIPersonalizedFeedResponse)  # ← REMOVED /ai/
async def get_personalized_feed(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    include_scores: bool = Query(False)
):
    service = get_ai_service()
    
    try:
        result = await service.get_feed(user_id, limit)
        
        if 'error' in result:
            raise HTTPException(status_code=500, detail=result['error'])
        
        feed_items = []
        for item in result.get('feed', []):
            score_item = AIVideoScore(
                video_id=item['video_id'],
                score=item['score']
            )
            if include_scores:
                score_item.engagement = item.get('engagement')
                score_item.freshness = item.get('freshness')
                score_item.personalization = item.get('personalization')
                score_item.trending = item.get('trending')
            feed_items.append(score_item)
        
        return AIPersonalizedFeedResponse(
            feed=feed_items,
            source=result.get('source', 'unknown'),
            latency_ms=result.get('latency_ms', 0),
            cached=result.get('cached', False),
            candidates_generated=result.get('candidates_generated', 0)
        )
        
    except Exception as e:
        logger.error(f"Error generating feed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ai_app.get("/user/{user_id}/profile", response_model=AIUserProfileResponse)  # ← REMOVED /ai/
async def get_user_profile(user_id: str):
    service = get_ai_service()
    
    try:
        profile = await service.user_profiles.get_profile(user_id)
        
        interests = sorted(
            [{"tag": k, "score": v} for k, v in profile.get('interests', {}).items()],
            key=lambda x: x['score'], reverse=True
        )[:10]
        
        creators = sorted(
            [{"creator_id": k, "score": v} for k, v in profile.get('creator_affinity', {}).items()],
            key=lambda x: x['score'], reverse=True
        )[:10]
        
        categories = sorted(
            [{"category": k, "score": v} for k, v in profile.get('category_affinity', {}).items()],
            key=lambda x: x['score'], reverse=True
        )[:10]
        
        return AIUserProfileResponse(
            user_id=profile['user_id'],
            user_tier=profile['user_tier'],
            total_engagement=profile['total_engagement'],
            trust_score=profile['trust_score'],
            top_interests=interests,
            top_creators=creators,
            top_categories=categories
        )
        
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@ai_app.post("/video/{video_id}/interaction")  # ← REMOVED /ai/
async def record_single_interaction(
    video_id: str,
    user_id: str = Query(..., description="Current user ID"),
    interaction_type: str = Query(..., description="Type of interaction"),
    watch_time: float = Query(0, description="Watch time in seconds"),
    duration: float = Query(60, description="Video duration"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    service = get_ai_service()
    
    async def record():
        await service.record_interaction(
            user_id=user_id,
            video_id=video_id,
            interaction_type=interaction_type,
            watch_time=watch_time,
            duration=duration
        )
    
    background_tasks.add_task(record)
    
    return {"success": True, "message": "Interaction recorded"}

@ai_app.get("/trending")  # ← REMOVED /ai/
async def get_trending_videos(
    limit: int = Query(50, ge=1, le=200)
):
    service = get_ai_service()
    
    try:
        client = service.redis_client.get_client()
        trending = await client.zrevrange("trending:global", 0, limit - 1, withscores=True)
        
        return {
            "trending": [
                {"video_id": vid, "score": score}
                for vid, score in trending
            ]
        }
    except Exception as e:
        logger.error(f"Error getting trending: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# End of file - ai_app is ready to be imported
# ============================================================================
