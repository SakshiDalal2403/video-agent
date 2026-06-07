#Actionableitems , decision , questions 

from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
import os 
import time 
import json


def invoke_with_retry(chain, payload, attempts: int = 3):
    last_error = None
    for attempt in range(attempts):
        try:
            return chain.invoke(payload)
        except Exception as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(2 * (attempt + 1))
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


def parse_extraction_response(response: str) -> dict:
    try:
        data = json.loads(response)
    except json.JSONDecodeError:
        return {
            "action_items": response,
            "key_decisions": "Could not parse key decisions from extraction response.",
            "open_questions": "Could not parse open questions from extraction response.",
        }

    return {
        "action_items": data.get("action_items", "No action items found."),
        "key_decisions": data.get("key_decisions", "No key decisions found."),
        "open_questions": data.get("open_questions", "No open questions found."),
    }


def extract_meeting_insights(transcript: str) -> dict:
    chain = build_chain(
        "You are an expert meeting analyst. From the meeting transcript, extract:\n"
        "1. Action items. For each provide task description, owner, and deadline. "
        "If deadline is not mentioned, write 'Not specified'.\n"
        "2. Key decisions made.\n"
        "3. Open questions or topics needing follow-up.\n\n"
        "Return only valid JSON with exactly these string fields:\n"
        "{"
        "\"action_items\": \"numbered list or No action items found.\", "
        "\"key_decisions\": \"numbered list or No key decisions found.\", "
        "\"open_questions\": \"numbered list or No open questions found.\""
        "}"
    )

    response = invoke_with_retry(chain, transcript)
    return parse_extraction_response(response)

def extract_action_items(transcript:str)->str:
    chain = build_chain(
         "You are an expert meeting analyst. From the meeting transcript, "
        "extract all action items. For each provide:\n"
        "- Task description\n"
        "- Owner (who is responsible)\n"
        "- Deadline (if mentioned, else write 'Not specified')\n\n"
        "Format as a numbered list. If none found say 'No action items found.'"
    )

    return invoke_with_retry(chain, transcript)


def extract_key_decisions(transcript: str) -> str:
    chain = build_chain(
        "You are an expert meeting analyst. From the meeting transcript, "
        "extract all key decisions made. Format as a numbered list. "
        "If none found say 'No key decisions found.'"
    )
    return invoke_with_retry(chain, transcript)


def extract_questions(transcript: str) -> str:
    chain = build_chain(
        "From the meeting transcript, extract all unresolved questions "
        "or topics needing follow-up. Format as a numbered list. "
        "If none found say 'No open questions found.'"
    )
    return invoke_with_retry(chain, transcript)
