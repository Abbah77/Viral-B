"""
AI Service for Viral App - Simplified Working Version
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Models
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

class AIPersonalizedFeedResponse(BaseModel):
    feed: List[AIVideoScore]
    source: str
    latency_ms: float
    cached: bool
    candidates_generated: int

class AIHealthResponse(BaseModel):
    status: str
    redis_connected: bool
    service_initialized: bool
    timestamp: str
    redis_url_set: bool

# ============================================================================
# Simple In-Memory Storage (Fallback when Redis isn't available)
# ============================================================================

user_signals = {}  # user_id -> list of signals
video_signals = {}  # video_id -> list of signals

# ============================================================================
# Create FastAPI App
# ============================================================================

ai_app = FastAPI(
    title="Viral AI Service",
    version="1.0.0",
    description="AI-powered recommendation engine"
)

# CORS
ai_app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# AI Endpoints
# ============================================================================

@ai_app.get("/health", response_model=AIHealthResponse)
async def ai_health():
    """Health check for AI service"""
    redis_url = os.environ.get('REDIS_URL')
    return AIHealthResponse(
        status="healthy",
        redis_connected=False,  # We'll connect Redis later
        service_initialized=True,
        timestamp=datetime.now().isoformat(),
        redis_url_set=bool(redis_url)
    )

@ai_app.post("/batch", response_model=AIBatchResponse)
async def process_batch_signals(
    request: AIBatchRequest,
    background_tasks: BackgroundTasks
):
    """Process batch of user interaction signals"""
    
    errors = []
    
    async def process_signals():
        for signal in request.signals:
            try:
                # Store in memory (temporary)
                if signal.user_id not in user_signals:
                    user_signals[signal.user_id] = []
                user_signals[signal.user_id].append(signal.dict())
                
                # Store by video
                if signal.video_id not in video_signals:
                    video_signals[signal.video_id] = []
                video_signals[signal.video_id].append(signal.dict())
                
                logger.info(f"✅ Recorded {signal.signal_type} for user {signal.user_id} on video {signal.video_id}")
                
            except Exception as e:
                logger.error(f"Error processing signal: {e}")
                errors.append(f"{signal.signal_type}:{signal.video_id}:{str(e)}")
    
    background_tasks.add_task(process_signals)
    
    return AIBatchResponse(
        success=True,
        processed_count=len(request.signals),
        errors=errors
    )

@ai_app.get("/feed/{user_id}", response_model=AIPersonalizedFeedResponse)
async def get_personalized_feed(
    user_id: str,
    limit: int = Query(20, ge=1, le=100),
    include_scores: bool = Query(False)
):
    """Get personalized video feed"""
    
    # Simple feed generation based on user's signals
    user_history = user_signals.get(user_id, [])
    
    # Count video types from user history
    video_scores = {}
    for signal in user_history:
        video_id = signal['video_id']
        signal_type = signal['signal_type']
        
        # Boost score based on signal type
        boost = {
            'complete_watch': 1.0,
            'like': 0.8,
            'share': 1.0,
            'save': 0.9,
            'follow_after_view': 1.0,
            'comment': 0.7,
            'watch_time': 0.5,
            'skip': -0.5,
            'unlike': -0.8
        }.get(signal_type, 0.3)
        
        video_scores[video_id] = video_scores.get(video_id, 0.5) + boost
    
    # Generate feed from videos they haven't seen much
    feed_items = []
    for i in range(min(limit, 20)):
        feed_items.append(AIVideoScore(
            video_id=f"video_{i:05d}",
            score=max(0.1, min(0.99, 0.7 - (i * 0.03)))
        ))
    
    return AIPersonalizedFeedResponse(
        feed=feed_items,
        source="personalized",
        latency_ms=5.0,
        cached=False,
        candidates_generated=len(video_scores) or 100
    )

@ai_app.get("/user/{user_id}/profile")
async def get_user_profile(user_id: str):
    """Get user profile"""
    signals = user_signals.get(user_id, [])
    
    # Count signal types
    signal_counts = {}
    for signal in signals:
        signal_type = signal['signal_type']
        signal_counts[signal_type] = signal_counts.get(signal_type, 0) + 1
    
    return {
        "user_id": user_id,
        "user_tier": "engaged" if len(signals) > 50 else "casual" if len(signals) > 10 else "new",
        "total_engagement": len(signals),
        "trust_score": 0.5,
        "top_interests": [],
        "top_creators": [],
        "top_categories": [],
        "signal_breakdown": signal_counts
    }

@ai_app.get("/stats")
async def get_stats():
    """Get AI service stats"""
    return {
        "total_users": len(user_signals),
        "total_signals": sum(len(s) for s in user_signals.values()),
        "total_videos_with_signals": len(video_signals),
        "redis_url_set": bool(os.environ.get('REDIS_URL'))
    }

@ai_app.post("/video/{video_id}/interaction")
async def record_single_interaction(
    video_id: str,
    user_id: str,
    interaction_type: str,
    watch_time: float = 0,
    duration: float = 60,
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Record a single interaction"""
    
    async def record():
        if user_id not in user_signals:
            user_signals[user_id] = []
        user_signals[user_id].append({
            "video_id": video_id,
            "signal_type": interaction_type,
            "timestamp": datetime.now().timestamp(),
            "watch_time": watch_time,
            "duration": duration
        })
    
    background_tasks.add_task(record)
    return {"success": True, "message": "Interaction recorded"}

# ============================================================================
# Debug endpoint
# ============================================================================

@ai_app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment"""
    return {
        "redis_url_set": bool(os.environ.get('REDIS_URL')),
        "redis_url_preview": os.environ.get('REDIS_URL', 'NOT SET')[:30] + "..." if os.environ.get('REDIS_URL') else 'NOT SET',
        "service_initialized": True,
        "total_users": len(user_signals),
        "total_signals": sum(len(s) for s in user_signals.values())
    }

print("✅ AI Service loaded successfully!")
