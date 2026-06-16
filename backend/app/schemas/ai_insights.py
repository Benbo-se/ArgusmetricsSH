"""
Pydantic schemas for AI Insights Dashboard endpoints.

Defines request and response models for:
- AI-powered insights and recommendations
- Traffic trend analysis
- Content performance insights
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class TrafficTrendInsight(BaseModel):
    """
    Traffic trend insight from AI analysis.

    Attributes:
        trend: Trend direction ('up', 'down', 'stable')
        percentage_change: Percentage change in traffic
        description: Natural language description of the trend
        time_period: Time period analyzed (e.g., "last 7 days")
    """
    trend: str = Field(
        ...,
        description="Trend direction (up, down, stable)",
        example="up"
    )
    percentage_change: float = Field(
        ...,
        description="Percentage change in traffic",
        example=15.5
    )
    description: str = Field(
        ...,
        description="Natural language description of the trend",
        example="Your traffic increased by 15.5% compared to the previous period"
    )
    time_period: str = Field(
        ...,
        description="Time period analyzed",
        example="last 7 days"
    )


class ContentInsight(BaseModel):
    """
    Content performance insight from AI analysis.

    Attributes:
        page_path: Path of the page
        metric: Performance metric analyzed
        value: Metric value
        description: Natural language description
    """
    page_path: str = Field(
        ...,
        description="Path of the page",
        example="/blog/post-1"
    )
    metric: str = Field(
        ...,
        description="Performance metric",
        example="bounce_rate"
    )
    value: float = Field(
        ...,
        description="Metric value",
        example=45.2
    )
    description: str = Field(
        ...,
        description="Natural language description",
        example="This page has a high bounce rate of 45.2%, consider improving engagement"
    )


class RecommendationInsight(BaseModel):
    """
    AI-generated recommendation for improvement.

    Attributes:
        category: Category of recommendation
        priority: Priority level (high, medium, low)
        title: Short title of the recommendation
        description: Detailed description
        impact: Expected impact
    """
    category: str = Field(
        ...,
        description="Category of recommendation",
        example="performance"
    )
    priority: str = Field(
        ...,
        description="Priority level (high, medium, low)",
        example="high"
    )
    title: str = Field(
        ...,
        description="Short title",
        example="Optimize high-traffic pages"
    )
    description: str = Field(
        ...,
        description="Detailed description",
        example="Your top 3 pages account for 60% of traffic. Focus optimization efforts here for maximum impact."
    )
    impact: str = Field(
        ...,
        description="Expected impact",
        example="Could improve engagement by 20-30%"
    )


class AIInsightsResponse(BaseModel):
    """
    Response schema for AI insights endpoint.

    Attributes:
        website_id: ID of the website
        generated_at: When insights were generated
        traffic_trends: List of traffic trend insights
        content_insights: List of content performance insights
        recommendations: List of AI recommendations
        summary: Overall summary of insights
        cached: Whether this response was cached
    """
    website_id: int = Field(
        ...,
        description="ID of the website",
        example=1
    )
    generated_at: str = Field(
        ...,
        description="When insights were generated (ISO format)",
        example="2025-11-01T12:00:00Z"
    )
    traffic_trends: List[TrafficTrendInsight] = Field(
        default=[],
        description="List of traffic trend insights"
    )
    content_insights: List[ContentInsight] = Field(
        default=[],
        description="List of content performance insights"
    )
    recommendations: List[RecommendationInsight] = Field(
        default=[],
        description="List of AI recommendations"
    )
    summary: str = Field(
        ...,
        description="Overall summary of insights",
        example="Your traffic is growing steadily with strong performance on top content pages"
    )
    cached: bool = Field(
        default=False,
        description="Whether this response was cached",
        example=False
    )


class AIInsightsRequest(BaseModel):
    """
    Request schema for AI insights (not used in GET, but for reference).

    Attributes:
        days: Number of days to analyze (default 7)
    """
    days: int = Field(
        default=7,
        description="Number of days to analyze",
        ge=1,
        le=90,
        example=7
    )
