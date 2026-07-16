"""
get_guideline_section — fetch guidelines content on explicit request. First
tries an exact section-heading match (no embedding call); if nothing
matches, falls back to a semantic content search so a topic that isn't a
section heading (e.g. a tool name mentioned in a table) is still findable.

Unlike the auto-anchoring in validate_oas — which excludes non-rule /
reference material — this explicit lookup searches EVERYTHING, so asking
"is there anything about X" returns reference material too.
"""
import logging
from collections import defaultdict

from app.models import GuidelineSectionInput, GetGuidelineSectionResult, GuidelineSection
from app.rag.retriever import get_section_chunks, retrieve_guidelines, build_guidelines_toc

logger = logging.getLogger(__name__)


def get_guideline_section(payload: GuidelineSectionInput) -> GetGuidelineSectionResult:
    chunks = get_section_chunks(payload.section, document=payload.document)
    via = "section-name"

    if not chunks:
        # No heading matched — semantic content search over ALL guideline
        # chunks (rules AND reference material), so an explicit lookup for a
        # topic like a tool name still surfaces something.
        docs = retrieve_guidelines(payload.section, k=4)
        if payload.document:
            docs = [d for d in docs if d.metadata.get("source") == payload.document]
        chunks = docs
        via = "content-search"

    # One entry per (document, section) pair, chunks joined in order.
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    for c in chunks:
        grouped[(c.metadata.get("source", ""), c.metadata.get("section", ""))].append(c.page_content)
    matches = [
        GuidelineSection(document=doc, section=section or "(no heading)", content="\n".join(texts))
        for (doc, section), texts in sorted(grouped.items())
    ]

    logger.info("get_guideline_section: section=%r document=%s via=%s -> %d match(es)",
                payload.section, payload.document, via if matches else "none", len(matches))

    if matches and via == "section-name":
        next_step = ("Use this section's text directly — quote it with its document/section "
                     "citation when answering the user.")
    elif matches:
        next_step = ("No exact section heading matched, so these are the closest chunks by "
                     "content search (may include reference material, not just design rules). "
                     "Use them if relevant; quote with the document/section citation.")
    else:
        toc = build_guidelines_toc()
        next_step = ("Nothing matched by name or content. Pick a section from the list and "
                     "retry:\n" + toc if toc else
                     "Nothing matched and the guidelines index is empty — has ingestion been run?")

    return GetGuidelineSectionResult(
        matches=matches,
        summary=f"{len(matches)} match(es) ({via})." if matches else "0 matches.",
        next_step=next_step,
    )
