"""
The internal Org-hosted LLM as an ADK model, via LiteLlm. The "openai/"
prefix selects the OpenAI wire format; api_base redirects every call to
YOUR custom URL — no traffic goes to OpenAI/Google.

If your gateway is not OpenAI-compatible, replace this with a custom
google.adk.models.BaseLlm subclass; agent.py only needs get_internal_llm().
"""
import os
from google.adk.models.lite_llm import LiteLlm


def get_internal_llm() -> LiteLlm:
    return LiteLlm(
        model=f"openai/{os.environ.get('INTERNAL_LLM_MODEL_NAME', 'internal-llm')}",
        api_base=os.environ["INTERNAL_LLM_BASE_URL"],
        api_key=os.environ["INTERNAL_LLM_API_KEY"],
        # Custom auth scheme instead of bearer key? set extra_headers here:
        # extra_headers={"X-Internal-Auth": "..."},
    )
