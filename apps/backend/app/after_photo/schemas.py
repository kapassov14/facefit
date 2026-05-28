from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

AfterPhotoIntensity = Literal["subtle", "balanced", "visible"]
AfterPhotoStatus = Literal["APPROVED", "NEEDS_MANUAL_REVIEW", "FAILED", "SKIPPED_NO_API_KEY"]
QualityRecommendation = Literal["approve", "retry", "manual_review", "reject"]


class IntensityPreset(BaseModel):
    name: AfterPhotoIntensity
    prompt_addition: str
    strength: float
    guidance: float


class AfterPhotoPrompt(BaseModel):
    prompt: str
    negative_prompt: str
    intensity: AfterPhotoIntensity
    preset: IntensityPreset
    attempt_index: int = 1


class AfterPhotoQualityResult(BaseModel):
    variant_path: str
    same_identity: bool = False
    identity_score: float = Field(default=0.0, ge=0.0, le=1.0)
    realism_score: float = Field(default=0.0, ge=0.0, le=1.0)
    visible_improvement: bool = False
    structural_change_score: float = Field(default=0.0, ge=0.0, le=1.0)
    region_scores: dict[str, float] = Field(default_factory=dict)
    skin_texture_preserved: bool = False
    too_much_retouch: bool = False
    plastic_surgery_effect: bool = False
    recommendation: QualityRecommendation = "manual_review"
    reason: str = ""
    fallback_scoring: bool = False

    @property
    def approved(self) -> bool:
        return (
            self.same_identity
            and self.identity_score >= 0.82
            and self.visible_improvement
            and not self.too_much_retouch
            and self.recommendation == "approve"
        )

    @property
    def ranking_score(self) -> float:
        score = self.identity_score * 0.6 + self.realism_score * 0.15
        if self.visible_improvement:
            score += 0.2
        score += self.structural_change_score * 0.12
        if self.skin_texture_preserved:
            score += 0.05
        if self.too_much_retouch:
            score -= 0.35
        return max(0.0, min(1.0, score))


class AfterPhotoFinalResult(BaseModel):
    status: AfterPhotoStatus
    final_path: str | None = None
    variant_paths: list[str] = Field(default_factory=list)
    quality_results: list[AfterPhotoQualityResult] = Field(default_factory=list)
    used_intensity: AfterPhotoIntensity = "balanced"
    used_retry: bool = False
    retry_count: int = 0
    reason: str = ""
