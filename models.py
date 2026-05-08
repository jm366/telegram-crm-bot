from pydantic import BaseModel, Field
from typing import Optional, Dict, Literal

class LeadExtraction(BaseModel):
    """Structured lead extracted from voice text."""
    first_name: Optional[str] = Field(None, description="First name of the contact")
    last_name: Optional[str] = Field(None, description="Last name of the contact")
    email: Optional[str] = Field(None, description="Email address")
    phone: Optional[str] = Field(None, description="Phone / WhatsApp number")
    title: Optional[str] = Field(None, description="Job title")
    company: Optional[str] = Field(None, description="Company name")
    industry: Optional[str] = Field(None, description="Industry (e.g. oil & gas, manufacturing)")
    address: Optional[str] = Field(None, description="Office address / location")
    country: Optional[str] = Field("UAE", description="Country")
    city: Optional[str] = Field(None, description="City")
    notes: Optional[str] = Field(None, description="Any additional context from the conversation")
    segment: Optional[Literal["hot", "warm", "partner", "learn", "low_priority", "new"]] = Field("new", description="Sales assessment")
    status: Optional[Literal["new", "contacted", "engaged", "qualified", "opportunity", "customer", "churned", "nurture", "dnc"]] = Field("new", description="Pipeline status")
    fit_score: Optional[int] = Field(None, ge=0, le=100, description="How good a fit for smartics (0-100)")
    intent_score: Optional[int] = Field(None, ge=0, le=100, description="How urgent / interested (0-100)")
    priority: Optional[int] = Field(None, ge=1, le=5, description="Priority 1=high, 5=low")
    tags: Optional[str] = Field(None, description="Comma-separated tags")
    linkedin: Optional[str] = Field(None, description="LinkedIn profile URL")

    # Non-DB meta fields
    next_step: Optional[str] = Field(None, description="Recommended next action for John Mark")
    source_channel: Optional[str] = Field("telegram_voice_bot", description="How the lead came in")

class ExtractionResult(BaseModel):
    """Top-level response from LLM extraction."""
    lead: LeadExtraction
    confidence: Literal["high", "medium", "low"] = "medium"
    reasoning: str = Field(description="Brief explanation of what was understood from the voice")
