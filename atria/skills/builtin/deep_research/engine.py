"""DeepResearchEngine — holds JobManager + ctx; exposes tool callables."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict

from atria.core.skill_tools import SkillToolContext

from .jobs import JobManager, ResearchJob
from .pipeline import _emit, run_job
from .taxonomy import generate_taxonomy, modify_taxonomy

logger = logging.getLogger(__name__)


class DeepResearchEngine:
    def __init__(self, ctx: SkillToolContext) -> None:
        self._ctx = ctx
        self._manager = JobManager.instance()

    def deep_research(self, topic: str, depth: str = "standard") -> Dict[str, Any]:
        if not topic or not topic.strip():
            return {"success": False, "error": "topic is required", "output": ""}
        topic = topic.strip()

        try:
            taxonomy = generate_taxonomy(topic, chat_fn=self._ctx.llm_chat)
        except Exception as exc:
            logger.exception(f"Taxonomy generation failed for: {topic!r}")
            return {"success": False, "error": f"Taxonomy generation failed: {exc}", "output": ""}

        job_id = uuid.uuid4().hex[:12]

        if self._ctx.review_callback is not None:
            while True:
                review_request_id = uuid.uuid4().hex[:12]
                event_payload = {
                    "type": "deep_research_taxonomy_ready",
                    "job_id": job_id,
                    "topic": topic,
                    "taxonomy": taxonomy,
                    "request_id": review_request_id,
                }
                try:
                    result = self._ctx.review_callback(job_id, review_request_id, event_payload)
                except Exception as exc:
                    logger.warning(f"Taxonomy review callback error: {exc} — proceeding")
                    break

                action = result.get("action", "accept")
                if action == "modify":
                    instructions = (result.get("instructions") or "").strip()
                    if instructions:
                        try:
                            taxonomy = modify_taxonomy(
                                taxonomy, instructions, chat_fn=self._ctx.llm_chat
                            )
                        except Exception as exc:
                            logger.error(f"Modify failed: {exc} — keeping previous")
                    continue
                if action == "regenerate":
                    new_topic = (result.get("topic") or topic).strip()
                    if new_topic:
                        topic = new_topic
                    try:
                        taxonomy = generate_taxonomy(topic, chat_fn=self._ctx.llm_chat)
                    except Exception as exc:
                        logger.error(f"Re-generation failed: {exc} — keeping previous taxonomy")
                    continue
                taxonomy = result.get("taxonomy") or taxonomy
                depth = result.get("depth", depth)
                break

        job = ResearchJob(job_id=job_id, topic=topic, depth=depth, taxonomy=taxonomy)
        self._manager.submit(job, lambda j: run_job(j, self._ctx))

        _emit(
            self._ctx,
            {
                "type": "deep_research_queued",
                "job_id": job_id,
                "topic": topic,
                "taxonomy": taxonomy,
            },
        )

        cat_count = len(taxonomy.get("taxonomy", []))
        sub_count = sum(len(c.get("sub_topics", [])) for c in taxonomy.get("taxonomy", []))
        bg_summary = (
            f"Deep research on **{topic}** is now running in the background "
            f"(job `{job_id}`, {cat_count} categories × {sub_count} subtopics). "
            "Results will stream into the UI section by section as they complete."
        )
        return {
            "success": True,
            "job_id": job_id,
            "topic": topic,
            "depth": depth,
            "taxonomy": taxonomy,
            "status": "queued",
            "_bg_task_started": True,
            "_bg_summary": bg_summary,
            "output": bg_summary,
        }

    def get_research_status(self, job_id: str) -> Dict[str, Any]:
        job = self._manager.get(job_id)
        if not job:
            return {
                "success": False,
                "error": f"No research job found with ID: {job_id}",
                "output": "",
            }
        return {
            "success": True,
            "job_id": job_id,
            "status": job.status,
            "progress": job.progress,
            "topic": job.topic,
            "sections_done": len(job.report_sections),
            "error": job.error,
            "output": (
                f"Job {job_id} ({job.topic}): "
                f"status={job.status}, progress={job.progress:.0%}, "
                f"sections={len(job.report_sections)}"
                + (f", error={job.error}" if job.error else "")
            ),
        }
