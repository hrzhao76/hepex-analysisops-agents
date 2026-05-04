from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent_02_scifi_oh.prompt_builder import build_sam_prompt
from agent_02_scifi_oh.review import ReviewResult, review_submission_bundle


StatusCallback = Callable[[str], Awaitable[None]]
WorkerCallback = Callable[[str, int, int], Awaitable[str]]
PromptBuilderCallback = Callable[..., str]


@dataclass
class NativeSciFiLoopResult:
    final_text: str
    attempts: int
    review: ReviewResult


def _json_dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


class NativeSciFiLoop:
    """Agent03-native review/retry loop.

    This mirrors the upstream agent02 SciFi loop behavior without modifying the
    agent02 package. Agent03 needs custom prompt builders for 03b/03c, so that
    customization lives here instead of in `agent_02_scifi_oh.loop`.
    """

    def __init__(
        self,
        *,
        worker: WorkerCallback,
        status: StatusCallback,
        max_attempts: int = 2,
        prompt_builder: PromptBuilderCallback = build_sam_prompt,
        label: str = "SciFi-native loop",
    ) -> None:
        self.worker = worker
        self.status = status
        self.max_attempts = max(1, max_attempts)
        self.prompt_builder = prompt_builder
        self.label = label

    async def run(
        self,
        *,
        base_prompt: str,
        req_json: dict[str, Any] | None,
        input_manifest: dict[str, Any] | None,
        work_dir: Path | None,
    ) -> NativeSciFiLoopResult:
        review_feedback: dict[str, Any] | None = None
        last_text = ""
        last_review = ReviewResult(
            passed=False,
            feedback={
                "missing_required_artifacts": [],
                "schema_or_type_errors": [f"{self.label} did not run"],
                "trace_consistency_errors": [],
                "scientific_consistency_warnings": [],
                "retry_instruction": "run the worker",
            },
        )

        for attempt in range(1, self.max_attempts + 1):
            sam_prompt = self.prompt_builder(
                base_prompt,
                req_json,
                input_manifest,
                attempt=attempt,
                max_attempts=self.max_attempts,
                review_feedback=review_feedback,
            )
            await self.status(
                f"{self.label}: Prescan rendered SAM prompt for attempt {attempt}/{self.max_attempts}."
            )
            last_text = await self.worker(sam_prompt, attempt, self.max_attempts)
            last_review = review_submission_bundle(req_json, last_text, input_manifest, work_dir)
            await self.status(f"{self.label}: Independent review {last_review.summary}.")

            if last_review.passed:
                final_payload = last_review.bundle if last_review.bundle is not None else json.loads(last_text)
                return NativeSciFiLoopResult(
                    final_text=_json_dump(final_payload),
                    attempts=attempt,
                    review=last_review,
                )

            review_feedback = last_review.feedback
            if attempt < self.max_attempts:
                await self.status(
                    f"{self.label}: retrying worker with independent review feedback."
                )

        error_payload = {
            "status": "error",
            "error": f"{self.label} independent review failed before a valid submission_bundle_v1 was produced.",
            "review_feedback": last_review.feedback,
        }
        return NativeSciFiLoopResult(
            final_text=_json_dump(error_payload),
            attempts=self.max_attempts,
            review=last_review,
        )
