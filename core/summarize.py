
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.runnables import RunnablePassthrough, RunnableLambda

import os
import time

DIRECT_SUMMARY_CHAR_LIMIT = 12000


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
    return ChatMistralAI(
        model="mistral-small-latest",
        mistral_api_key=os.getenv("MISTRAL_API_KEY"),
        temperature=0.3,
        request_timeout=60,
    )


def split_transcript(transcript: str) -> list:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=3000,
        chunk_overlap=200
    )
    return splitter.split_text(transcript)


def summarize(transcript: str) -> str:
    llm = get_llm()
    chunks = split_transcript(transcript)

    map_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Summarize only the information explicitly stated in this transcript portion. "
                "Do not add outside knowledge, assumptions, examples, objectives, or future directions.",
            ),
            ("human", "{text}"),
        ]
    )

    map_chain = map_prompt | llm | StrOutputParser()

    if len(transcript) <= DIRECT_SUMMARY_CHAR_LIMIT:
        return invoke_with_retry(map_chain, {"text": transcript})

    chunk_summaries = [invoke_with_retry(map_chain, {"text": chunk}) for chunk in chunks]

    combined = "\n\n".join(chunk_summaries)

    combined_prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "Combine these partial summaries into one concise final summary. "
                "Use only the provided text. Do not add outside knowledge or expand the topic. "
                "If the transcript is very short, return 1-2 short sentences instead of bullet points.",
            ),
            ("human", "{text}"),
        ]
    )

    combined_chain = (
        RunnablePassthrough() | RunnableLambda(lambda x: {"text": x}) | combined_prompt | llm | StrOutputParser()
    )

    return invoke_with_retry(combined_chain, combined)


def generate_title(transcipt: str) -> str:
    llm = get_llm()

    title_chain = (
        RunnablePassthrough() | RunnableLambda(lambda x: {"text": x}) |
        ChatPromptTemplate.from_messages([
            (
                "system",
                "Based on the meeting transcript, generate a short professional meeting title "
                "(max 8 words). Only return the title, nothing else.",
            ),
            ("human", "{text}"),
        ])
        | llm
        | StrOutputParser()
    )

    return invoke_with_retry(title_chain, transcipt[:2000])
