"""Background research pipeline."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from atria.core.skill_tools import SkillToolContext

from .jobs import ResearchJob
from .persistence import save_report
from .synthesis import synthesize_section

logger = logging.getLogger(__name__)


def _emit(ctx: SkillToolContext, event: Dict[str, Any]) -> None:
    if ctx.broadcaster:
        try:
            ctx.broadcaster(event)
        except Exception as exc:
            logger.debug(f"Deep research emit error: {exc}")


def run_job(job: ResearchJob, ctx: SkillToolContext) -> None:
    try:
        job.status = "running"
        _emit(
            ctx,
            {
                "type": "deep_research_start",
                "job_id": job.job_id,
                "topic": job.topic,
                "taxonomy": job.taxonomy,
            },
        )

        categories: List[Dict] = job.taxonomy.get("taxonomy", [])
        total = max(sum(len(c.get("sub_topics", [])) for c in categories), 1)
        done = 0

        for cat in categories:
            cat_name = cat.get("name", "")
            for sub in cat.get("sub_topics", []):
                sub_name = sub.get("name", "")
                queries: List[str] = sub.get("search_queries", [])

                _emit(
                    ctx,
                    {
                        "type": "deep_research_section_start",
                        "job_id": job.job_id,
                        "category": cat_name,
                        "subtopic": sub_name,
                    },
                )

                evidence: List[str] = []
                if ctx.web_search and queries:
                    for q in queries[:3]:
                        try:
                            res = ctx.web_search.search(q, max_results=3)
                            for r in res.get("results", []):
                                title = r.get("title", "")
                                url = r.get("url", "")
                                snippet = r.get("snippet", "")
                                if snippet:
                                    evidence.append(f"**{title}** ({url})\n{snippet}")
                        except Exception as se:
                            logger.debug(f"Search error for '{q}': {se}")

                content = synthesize_section(
                    job.topic, cat_name, sub_name, evidence, chat_fn=ctx.llm_chat
                )
                job.report_sections.append(
                    {
                        "category": cat_name,
                        "subtopic": sub_name,
                        "content": content,
                    }
                )

                done += 1
                job.progress = done / total
                _emit(
                    ctx,
                    {
                        "type": "deep_research_section_done",
                        "job_id": job.job_id,
                        "category": cat_name,
                        "subtopic": sub_name,
                        "content": content,
                        "progress": round(job.progress, 3),
                    },
                )

        job.status = "done"
        report_path = save_report(job, ctx.working_dir)
        _emit(
            ctx,
            {
                "type": "deep_research_done",
                "job_id": job.job_id,
                "topic": job.topic,
                "section_count": len(job.report_sections),
                "sections": job.report_sections,
                "report_path": report_path,
            },
        )

    except Exception as exc:
        logger.exception(f"Deep research job {job.job_id} failed")
        job.status = "error"
        job.error = str(exc)
        _emit(
            ctx,
            {
                "type": "deep_research_error",
                "job_id": job.job_id,
                "error": str(exc),
            },
        )
