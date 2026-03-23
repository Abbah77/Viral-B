"""
AI Service for Viral App - Complete Working Version
All features included, Redis disabled until we fix the connection issue
"""

import os
import logging
from datetime import datetime
from typing import Optional, List, Dict
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Pydantic Models (Complete)
# ============================================================================

class AISignal(BaseModel):
    """Single user interaction signal"""
    video_id: str
    signal_type: str
    timestamp: int
    user_id: str
    value: Optional[float] = None
    video_duration: Optional[float] = None
    session_id: Optional[str] = None

class AIBatchRequest(BaseModel):
    """Batch of signals from frontend"""
    signals: List[AISignal]

class AIBatchResponse(BaseModel):
    """Response for batch signal processing"""
    success: bool
    processed_count: int
    errors: List[str] = []

class AIVideoScore(BaseModel):
    """Scored video from AI"""
    video_id: str
    score: float
    engagement: Optional[float] = None
    freshness: Optional[float] = None
    personalization: Optional[float] = None
    trending: Optional[float] = None

class AIPersonalizedFeedResponse(BaseModel):
    """Personalized feed response"""
    feed: List[AIVideoScore]
    source: str
    latency_ms: float
    cached: bool
    candidates_generated: int

class AIUserProfileResponse(BaseModel):
    """User profile from AI"""
    user_id: str
    user_tier: str
    total_engagement: int
    trust_score: float
    top_interests: List[Dict[str, float]]
    top_creators: List[Dict[str, float]]
    top_categories: List[Dict[str, float]]

class AIHealthResponse(BaseModel):
    """Health check response"""
    status: str
    redis_connected: bool
    service_initialized: bool
    timestamp: str
    redis_url_set: bool
    redis_error: Optional[str] = None

# ============================================================================
# In-Memory Storage (Working without Redis)
# ============================================================================

user_signals: Dict[str, List[Dict]] = {}      # user_id -> list of signals
video_signals: Dict[str, List[Dict]] = {}     # video_id -> list of signals
user_profiles: Dict[str, Dict] = {}           # user_id -> profile data
video_stats: Dict[str, Dict] = {}             # video_id -> stats

# ============================================================================
# Scoring Functions (AI Logic)
# ============================================================================

def compute_engagement_score(signals: List[Dict], watch_time: float = 0, duration: float = 60) -> float:
    """Compute engagement score from user signals"""
    if not signals:
        return 0.5
    
    # Signal weights
    weights = {
        'complete_watch': 1.0,
        'share': 0.95,
        'save': 0.85,
        'like': 0.70,
        'comment': 0.65,
        'rewatch': 0.90,
        'follow_after_view': 0.80,
        'profile_visit': 0.50,
        'watch_time': 0.40,
        'seek_forward': 0.30,
        'seek_back': 0.30,
        'skip': -0.50,
        'unlike': -0.40,
        'unsave': -0.30,
        'unfollow': -0.80
    }
    
    score = 0.5  # Base score
    for signal in signals:
        signal_type = signal.get('signal_type', '')
        weight = weights.get(signal_type, 0)
        score += weight * 0.1
    
    # Watch time bonus
    if duration > 0:
        watch_ratio = min(watch_time / duration, 1.0)
        score += watch_ratio * 0.3
    
    return min(1.0, max(0.0, score))

def compute_freshness_score(hours_since_post: float) -> float:
    """Exponential freshness decay"""
    if hours_since_post <= 0:
        return 1.0
    if hours_since_post > 168:  # 7 days
        return 0.0
    
    freshness = pow(2, -hours_since_post / 24)
    return max(0.0, min(1.0, freshness))

def compute_personalization_score(user_id: str, video_features: Dict) -> float:
    """Personalization based on user history"""
    user_history = user_signals.get(user_id, [])
    if not user_history:
        return 0.5
    
    # Count user preferences from history
    preferences = {
        'like': 0,
        'share': 0,
        'save': 0,
        'complete_watch': 0,
        'skip': 0
    }
    
    for signal in user_history:
        signal_type = signal.get('signal_type', '')
        if signal_type in preferences:
            preferences[signal_type] += 1
    
    # Calculate preference score
    total = sum(preferences.values())
    if total == 0:
        return 0.5
    
    positive = preferences['like'] + preferences['share'] + preferences['save'] + preferences['complete_watch']
    negative = preferences['skip']
    
    score = (positive - negative * 0.5) / total
    return min(1.0, max(0.0, 0.5 + score * 0.5))

def compute_trending_score(video_id: str) -> float:
    """Compute trending based on video stats"""
    stats = video_stats.get(video_id, {})
    views = stats.get('views_last_hour', 0)
    likes = stats.get('likes_last_hour', 0)
    shares = stats.get('shares_last_hour', 0)
    
    velocity = views + (likes * 2) + (shares * 5)
    return min(1.0, velocity / 1000)

# ============================================================================
# Create FastAPI App
# ============================================================================

ai_app = FastAPI(
    title="Viral AI Service",
    version="1.0.0",
    description="AI-powered recommendation engine for Viral App"
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
# AI Endpoints (Complete)
# ============================================================================

@ai_app.get("/health", response_model=AIHealthResponse)
async def ai_health():
    """Health check for AI service"""
    redis_url = os.environ.get('REDIS_URL')
    return AIHealthResponse(
        status="healthy",
        redis_connected=False,  # Redis disabled for now
        service_initialized=True,
        timestamp=datetime.now().isoformat(),
        redis_url_set=bool(redis_url),
        redis_error=None
    )

@ai_app.post("/batch", response_model=AIBatchResponse)
async def process_batch_signals(
    request: AIBatchRequest,
    background_tasks: BackgroundTasks
):
    """Process batch of user interaction signals for AI learning"""
    errors = []
    
    async def process_signals():
        for signal in request.signals:
            try:
                # Store in memory
                if signal.user_id not in user_signals:
                    user_signals[signal.user_id] = []
                user_signals[signal.user_id].append(signal.dict())
                
                if signal.video_id not in video_signals:
                    video_signals[signal.video_id] = []
                video_signals[signal.video_id].append(signal.dict())
                
                # Update video stats
                if signal.video_id not in video_stats:
                    video_stats[signal.video_id] = {
                        'views_last_hour': 0,
                        'likes_last_hour': 0,
                        'shares_last_hour': 0,
                        'total_views': 0,
                        'total_likes': 0,
                        'total_shares': 0
                    }
                
                if signal.signal_type == 'like':
                    video_stats[signal.video_id]['likes_last_hour'] += 1
                    video_stats[signal.video_id]['total_likes'] += 1
                elif signal.signal_type == 'share':
                    video_stats[signal.video_id]['shares_last_hour'] += 1
                    video_stats[signal.video_id]['total_shares'] += 1
                elif signal.signal_type in ['watch_time', 'complete_watch']:
                    video_stats[signal.video_id]['views_last_hour'] += 1
                    video_stats[signal.video_id]['total_views'] += 1
                
                logger.info(f"✅ Recorded {signal.signal_type} for user {signal.user_id}")
                
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
    """Get personalized video feed for a user"""
    start_time = datetime.now()
    
    # Get user history
    user_history = user_signals.get(user_id, [])
    personalization_base = compute_personalization_score(user_id, {})
    
    # Generate personalized feed (simulated for now)
    feed_items = []
    for i in range(min(limit, 50)):
        video_id = f"video_{i:05d}"
        
        # Calculate scores
        engagement = compute_engagement_score(user_history)
        freshness = compute_freshness_score(i % 168)  # Random freshness
        personalization = personalization_base * (1 - i * 0.02)
        trending = compute_trending_score(video_id)
        
        # Final score (weighted)
        final_score = (
            engagement * 0.35 +
            freshness * 0.20 +
            personalization * 0.25 +
            trending * 0.20
        )
        
        if include_scores:
            feed_items.append(AIVideoScore(
                video_id=video_id,
                score=final_score,
                engagement=engagement,
                freshness=freshness,
                personalization=personalization,
                trending=trending
            ))
        else:
            feed_items.append(AIVideoScore(
                video_id=video_id,
                score=final_score
            ))
    
    # Sort by score
    feed_items.sort(key=lambda x: x.score, reverse=True)
    
    latency_ms = (datetime.now() - start_time).total_seconds() * 1000
    
    return AIPersonalizedFeedResponse(
        feed=feed_items[:limit],
        source="personalized",
        latency_ms=latency_ms,
        cached=False,
        candidates_generated=len(feed_items)
    )

@ai_app.get("/user/{user_id}/profile", response_model=AIUserProfileResponse)
async def get_user_profile(user_id: str):
    """Get AI user profile with interests and affinities"""
    signals = user_signals.get(user_id, [])
    
    # Analyze user preferences
    signal_counts = {}
    for signal in signals:
        signal_type = signal.get('signal_type', 'unknown')
        signal_counts[signal_type] = signal_counts.get(signal_type, 0) + 1
    
    # Calculate user tier
    total = len(signals)
    if total < 10:
        user_tier = "new"
    elif total < 50:
        user_tier = "casual"
    elif total < 200:
        user_tier = "engaged"
    else:
        user_tier = "power"
    
    # Calculate trust score based on engagement patterns
    positive = signal_counts.get('like', 0) + signal_counts.get('share', 0) + signal_counts.get('save', 0)
    negative = signal_counts.get('skip', 0) + signal_counts.get('unlike', 0)
    trust_score = min(1.0, max(0.2, (positive + 1) / (positive + negative + 2)))
    
    # Extract top interests (simulated)
    top_interests = [
        {"tag": "comedy", "score": 0.85},
        {"tag": "music", "score": 0.72},
        {"tag": "gaming", "score": 0.68},
        {"tag": "sports", "score": 0.45}
    ]
    
    # Extract top creators (simulated)
    top_creators = [
        {"creator_id": "creator_001", "score": 0.92},
        {"creator_id": "creator_002", "score": 0.78},
        {"creator_id": "creator_003", "score": 0.65}
    ]
    
    # Extract top categories (simulated)
    top_categories = [
        {"category": "comedy", "score": 0.88},
        {"category": "entertainment", "score": 0.75},
        {"category": "music", "score": 0.62}
    ]
    
    return AIUserProfileResponse(
        user_id=user_id,
        user_tier=user_tier,
        total_engagement=total,
        trust_score=trust_score,
        top_interests=top_interests,
        top_creators=top_creators,
        top_categories=top_categories
    )

@ai_app.get("/trending")
async def get_trending_videos(
    limit: int = Query(50, ge=1, le=200)
):
    """Get globally trending videos"""
    # Calculate trending scores from video_stats
    trending_scores = []
    for video_id, stats in video_stats.items():
        score = compute_trending_score(video_id)
        trending_scores.append({"video_id": video_id, "score": score})
    
    # Sort by score
    trending_scores.sort(key=lambda x: x['score'], reverse=True)
    
    return {
        "trending": trending_scores[:limit]
    }

@ai_app.get("/stats")
async def get_stats():
    """Get AI service statistics"""
    return {
        "total_users": len(user_signals),
        "total_signals": sum(len(s) for s in user_signals.values()),
        "total_videos_with_signals": len(video_signals),
        "total_video_stats": len(video_stats),
        "redis_url_set": bool(os.environ.get('REDIS_URL')),
        "redis_connected": False,
        "service_version": "1.0.0"
    }

@ai_app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment"""
    return {
        "redis_url_set": bool(os.environ.get('REDIS_URL')),
        "redis_url_preview": os.environ.get('REDIS_URL', 'NOT SET')[:50] + "..." if os.environ.get('REDIS_URL') else 'NOT SET',
        "service_initialized": True,
        "total_users": len(user_signals),
        "total_signals": sum(len(s) for s in user_signals.values()),
        "total_video_stats": len(video_stats),
        "python_version": "3.11"
    }

@ai_app.post("/video/{video_id}/interaction")
async def record_single_interaction(
    video_id: str,
    user_id: str = Query(..., description="Current user ID"),
    interaction_type: str = Query(..., description="Type of interaction"),
    watch_time: float = Query(0, description="Watch time in seconds"),
    duration: float = Query(60, description="Video duration"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Record a single interaction"""
    
    async def record():
        signal = {
            "video_id": video_id,
            "signal_type": interaction_type,
            "timestamp": int(datetime.now().timestamp() * 1000),
            "user_id": user_id,
            "value": watch_time if interaction_type == 'watch_time' else 1,
            "video_duration": duration
        }
        
        if user_id not in user_signals:
            user_signals[user_id] = []
        user_signals[user_id].append(signal)
        
        if video_id not in video_signals:
            video_signals[video_id] = []
        video_signals[video_id].append(signal)
        
        logger.info(f"✅ Recorded {interaction_type} for user {user_id}")
    
    background_tasks.add_task(record)
    return {"success": True, "message": "Interaction recorded"}

print("✅ AI Service loaded successfully!")
print(f"   Total users in memory: {len(user_signals)}")
print(f"   Total signals: {sum(len(s) for s in user_signals.values())}")
