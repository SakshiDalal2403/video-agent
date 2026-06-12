#Actionableitems , decision , questions 

from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
import os 
import time 
import asyncio


def invoke_with_retry(chain, payload, attempts: int = 3):
    last_error = None
    for attempt in range(attempts):
        try:
            return chain.invoke(payload)
        except Exception as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(2 ** (attempt + 1))
    raise last_error


def get_llm():
    return ChatMistralAI(model = "mistral-small-latest", mistral_api_key = os.getenv("MISTRAL_API_KEY"),temperature=0.2)



def build_chain(system_prompt : str):
    llm = get_llm()
    return (
        RunnablePassthrough() | RunnableLambda(lambda x : {"text" : x}) |ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human","{text}"),
    ]) | llm |StrOutputParser()
    )

def extract_action_items(transcript:str)->str:
    chain = build_chain(
        "You are an expert content analyst. From the transcript below, "
        "extract ALL action items, tasks, to-dos, or things that need to be done. "
        "This could be from a meeting, lecture, speech, conversation, or any audio/video content. "
        "For each item provide:\n"
        "- Task description\n"
        "- Owner (who is responsible, if mentioned, else write 'Not specified')\n"
        "- Deadline (if mentioned, else write 'Not specified')\n\n"
        "Format as a numbered list. If none found say 'No action items found.'"
    )

    return invoke_with_retry(chain, transcript)


def extract_key_decisions(transcript: str) -> str:
    chain = build_chain(
        "You are an expert content analyst. From the transcript below, "
        "extract all key decisions, conclusions, choices, or outcomes that were stated or implied. "
        "This could be from a meeting, lecture, speech, conversation, or any audio/video content. "
        "Format as a numbered list. "
        "If none found say 'No key decisions found.'"
    )
    return invoke_with_retry(chain, transcript)


def extract_questions(transcript: str) -> str:
    chain = build_chain(
        "You are an expert content analyst. From the transcript below, "
        "extract ALL questions — including open questions, rhetorical questions, unresolved topics, "
        "things needing follow-up, or questions posed to the audience or listener. "
        "This could be from a meeting, lecture, speech, conversation, or any audio/video content. "
        "Do NOT skip questions just because they are rhetorical or conversational. "
        "Format as a numbered list. "
        "If none found say 'No open questions found.'"
    )
    return invoke_with_retry(chain, transcript)


async def extract_all_async(transcript: str) -> dict:
    """Run all three extractors concurrently using asyncio."""
    results = await asyncio.gather(
        asyncio.to_thread(extract_action_items, transcript),
        asyncio.to_thread(extract_key_decisions, transcript),
        asyncio.to_thread(extract_questions, transcript),
    )
    return {
        "action_items": results[0],
        "key_decisions": results[1],
        "open_questions": results[2],
    }
