"""
get_guideline_section — fetch the full text of a named guidelines section,
by exact metadata match against the docstore (no embedding call, no
similarity ranking). Complements top-k retrieval: validate_oas/fix_oas
responses carry a guidelines_toc listing every section that exists, and
this tool pulls any of them in full on demand — so the calling agent is
never limited to whatever top-k retrieval happened to surface.
"""
import logging
from collections import defaultdict

from app.models import GuidelineSectionInput, GetGuidelineSectionResult, GuidelineSection
from app.rag.retriever import get_section_chunks, build_guidelines_toc

logger = logging.getLogger(__name__)


def get_guideline_section(payload: GuidelineSectionInput) -> GetGuidelineSectionResult:
    chunks = get_section_chunks(payload.section, document=payload.document)

    # One entry per (document, section) pair, chunks joined in order.
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for c in chunks:
        grouped[(c.metadata.get("source", ""), c.metadata.get("section", ""))].append(c.page_content)
    matches = [
        GuidelineSection(document=doc, section=section, content="\n".join(texts))
        for (doc, section), texts in sorted(grouped.items())
    ]

    logger.info("get_guideline_section: section=%r document=%s -> %d match(es)",
                payload.section, payload.document, len(matches))

    if matches:
        next_step = ("Use this section's text directly — quote it with its document/section "
                     "citation when answering the user.")
    else:
        toc = build_guidelines_toc()
        next_step = ("No section matched. Pick an exact name from the available sections and "
                     "retry:\n" + toc if toc else
                     "No section matched and the guidelines index is empty — has ingestion been run?")

    return GetGuidelineSectionResult(
        matches=matches,
        summary=f"{len(matches)} section(s) matched.",
        next_step=next_step,
    )
