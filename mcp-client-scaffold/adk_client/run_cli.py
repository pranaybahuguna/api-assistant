"""Interactive CLI: python -m adk_client.run_cli"""
import asyncio
import uuid

from dotenv import load_dotenv
load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from adk_client.agent import build_agent

APP = "api_assistant"


async def main() -> None:
    session_service = InMemorySessionService()
    user, session = "local-dev", str(uuid.uuid4())
    await session_service.create_session(app_name=APP, user_id=user, session_id=session)
    runner = Runner(agent=build_agent(), app_name=APP, session_service=session_service)

    print("the API Assistant CLI — type 'exit' to quit.\n")
    while True:
        q = input("you> ").strip()
        if q.lower() in {"exit", "quit"}:
            break
        msg = types.Content(role="user", parts=[types.Part(text=q)])
        async for event in runner.run_async(user_id=user, session_id=session, new_message=msg):
            if event.is_final_response() and event.content and event.content.parts:
                print(f"agent> {event.content.parts[0].text}\n")


if __name__ == "__main__":
    asyncio.run(main())
