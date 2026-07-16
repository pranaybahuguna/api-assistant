"""
Callbacks that spare the LLM from retyping large OAS documents.

The problem: validate_oas/fix_oas take the full spec as a tool argument,
and in function calling the MODEL must generate that argument token by
token. A 400-line spec is thousands of output tokens per call — slow,
easily truncated by the gateway's max output tokens (surfacing to the user
as "the document is too large to be passed"), and one silently mistyped
line corrupts the validation.

The fix: the spec already exists verbatim in the conversation — the user
pasted it (or the model just emitted a corrected version). So:

- before_agent_callback / after_model_callback watch the conversation and
  stash the most recent OAS-looking text in session state ("last_oas").
- The INSTRUCTION tells the model to pass oas_content="LAST_SPEC" instead
  of retyping.
- before_tool_callback substitutes the stashed text into the tool args
  before the MCP call goes out — the server always receives the full,
  byte-exact spec; the model only ever generates a 9-character placeholder.
"""
import re

OAS_PLACEHOLDER = "LAST_SPEC"
_STATE_KEY = "last_oas"
_OAS_TOOLS = {"validate_oas", "fix_oas"}

_FENCE_RE = re.compile(r"```[a-zA-Z0-9_-]*\n(.*?)```", re.DOTALL)


def _extract_oas(text: str) -> str | None:
    """The most recent OAS document in a message: prefer fenced code blocks
    that contain an openapi/swagger version key, else a bare document that
    starts one (people paste specs without fences too). Returns None if the
    text doesn't look like it carries a spec."""
    if not text:
        return None
    fenced = [m.group(1) for m in _FENCE_RE.finditer(text)]
    # Latest fenced block wins; the bare message is only a fallback for an
    # unfenced paste (checked last, or it would swallow surrounding prose).
    for candidate in list(reversed(fenced)) + [text]:
        stripped = candidate.strip()
        if re.search(r'(^|\n)\s*\{?\s*(["\']?)(openapi|swagger)\2\s*:', stripped):
            return stripped
    return None


def remember_user_oas(callback_context):
    """before_agent_callback: if the incoming user message carries an OAS
    document, stash it. Returning None lets the turn proceed normally."""
    content = getattr(callback_context, "user_content", None)
    for part in (getattr(content, "parts", None) or []):
        oas = _extract_oas(getattr(part, "text", "") or "")
        if oas:
            callback_context.state[_STATE_KEY] = oas
    return None


def remember_model_oas(callback_context, llm_response):
    """after_model_callback: when the model itself emits a spec (e.g. the
    corrected OAS after a fix), that becomes the latest spec — so the
    follow-up re-validate can use the placeholder too. Returning None keeps
    the response unchanged."""
    content = getattr(llm_response, "content", None)
    for part in (getattr(content, "parts", None) or []):
        oas = _extract_oas(getattr(part, "text", "") or "")
        if oas:
            callback_context.state[_STATE_KEY] = oas
    return None


def substitute_oas(tool, args, tool_context):
    """before_tool_callback: swap the placeholder for the real spec text.
    Mutating args in place and returning None lets the (modified) call
    proceed; returning a dict would skip the tool and use it as the result,
    which we only do for the error case below."""
    if getattr(tool, "name", "") not in _OAS_TOOLS:
        return None
    if args.get("oas_content", "").strip() != OAS_PLACEHOLDER:
        return None

    stored = tool_context.state.get(_STATE_KEY)
    if not stored:
        return {
            "error": f"oas_content was '{OAS_PLACEHOLDER}' but no OAS document has "
                     "been seen in this conversation yet. Ask the user to paste the "
                     "spec, or pass the full oas_content explicitly.",
        }
    args["oas_content"] = stored
    return None
