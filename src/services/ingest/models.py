"""Data models and configuration for the offline ingestion pipeline (FR-01)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IngestConfig(BaseModel):
    """Configuration parameters for adaptive keyframing and video processing.

    Wraps multiple thresholds into a single parameter object to strictly satisfy
    the three-parameter function limit across ingestion modules.
    """

    hist_diff_threshold: float = Field(
        default=0.40,
        description="Minimum HSV histogram distance required to trigger an event keyframe.",
    )
    max_heartbeat_s: float = Field(
        default=5.0,
        description="Maximum seconds before forcing a heartbeat keyframe in stationary scenes.",
    )
    target_width: int = Field(
        default=64,
        description="Width to downsample frames before computing histogram deltas.",
    )
    keyframing_strategy: str = Field(
        default="lmske",
        description="Keyframing engine strategy ('lmske' or 'hsv_heartbeat').",
    )
    cosine_similarity_threshold: float = Field(
        default=0.80,
        description="Similarity threshold for LMSKE stage 3 redundancy removal.",
    )
    enable_auto_fallback: bool = Field(
        default=True,
        description="Enable automatic fail-safe fallback to hsv_heartbeat on exception.",
    )
    compare_bottom_crop: float = Field(
        default=0.0,
        ge=0.0,
        lt=0.9,
        description="Fraction of frame height ignored at the bottom when comparing frames. For "
        "dashcam footage where the car's own bonnet fills the lower frame: that region "
        "is the same in every frame, so it flattens every histogram distance. Affects "
        "comparison only -- saved frames are never cropped.",
    )


class VideoMetadata(BaseModel):
    """Essential metadata extracted from a raw video container."""

    video_id: str = Field(description="Unique identifier or basename of the video clip.")
    fps: float = Field(description="Frames per second of the source video.")
    total_frames: int = Field(description="Total count of frames in the clip.")
    width: int = Field(description="Frame pixel width.")
    height: int = Field(description="Frame pixel height.")


class ExtractedKeyframe(BaseModel):
    """Represents a selected keyframe from the adaptive ingestion algorithm."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    frame_id: str = Field(description="Unique identifier for this specific frame.")
    video_id: str = Field(description="Source video identifier.")
    timestamp_s: float = Field(description="Timestamp in seconds offset from clip start.")
    frame_idx: int = Field(description="Original frame index in the raw video stream.")
    reason: str = Field(description="Why this frame was selected ('event' or 'heartbeat').")
    image_array: Any = Field(default=None, description="In-memory NumPy BGR image matrix.")
