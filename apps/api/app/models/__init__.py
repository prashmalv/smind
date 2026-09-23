"""Import every model so SQLAlchemy's metadata is complete before create_all/migrations."""

from app.models.commerce import Customer, Order, OrderItem, Product, Store
from app.models.intelligence import (
    ChurnScore,
    Conversation,
    Insight,
    Message,
    NextBestOffer,
    SegmentAssignment,
    SimulationRun,
)
from app.models.signals import Campaign, CompetitorSignal, Feedback
from app.models.tenant import ApiKey, Tenant, User
from app.models.vision import Camera, CameraAlert, CameraEvent

__all__ = [
    "ApiKey", "Camera", "CameraAlert", "CameraEvent", "Campaign", "ChurnScore",
    "CompetitorSignal", "Conversation", "Customer", "Feedback", "Insight", "Message",
    "NextBestOffer", "Order", "OrderItem", "Product", "SegmentAssignment",
    "SimulationRun", "Store", "Tenant", "User",
]
