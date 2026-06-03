import os
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from core.vector_store import build_vector_store, load_vector_store, get_retriever

RAG_TOP_K = 4

def log_rag(message: str):
    print(f"[rag] {message}", flush=True)

def get_llm():
    return ChatMistralAI(
        model="mistral-small-latest",
        mistral_api_key=os.getenv("MISTRAL_API_KEY"),
        temperature=0.3,
    )

def format_docs(docs):
    return "\n\n".join([doc.page_content for doc in docs])

def build_rag_chain(transcript:str, run_id: str | None = None):
    log_rag(f"Starting RAG chain build for run_id={run_id}")

    vector_store = build_vector_store(transcript, run_id=run_id)
    log_rag("Vector store ready")

    retriever = get_retriever(vector_store, k = RAG_TOP_K)
    log_rag(f"Retriever ready; it will pick top {RAG_TOP_K} chunk(s) per question")

    llm = get_llm()
    log_rag("Mistral LLM ready for RAG answers")

    prompt = ChatPromptTemplate.from_messages(

        [(
            "system",
            """You are an expert meeting assistant. Answer the user's question 
based ONLY on the meeting transcript context provided below.

If the answer is not found in the context, say: 
"I could not find this information in the meeting transcript."

Always be concise and precise. If quoting someone, mention it clearly.

Context from meeting transcript:
{context}""",
        ),
        ("human", "{question}"),
    ]
    )

    #full LCEL Rag pipeline 

    rag_chain = (

        {"context" : retriever | RunnableLambda(format_docs),
         "question": RunnablePassthrough()
         }
         |prompt|llm|StrOutputParser()
    )

    log_rag("RAG chain build complete")
    return rag_chain


def load_rag_chain(persist_directory: str | None = None):
    log_rag(f"Loading RAG chain from persist_directory={persist_directory}")
    vector_store = load_vector_store(persist_directory) if persist_directory else load_vector_store()
    retriver = get_retriever(vector_store, k=RAG_TOP_K)
    log_rag(f"Retriever ready; it will pick top {RAG_TOP_K} chunk(s) per question")

    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            """You are an expert meeting assistant. Answer the user's question 
based ONLY on the meeting transcript context provided below.

If the answer is not found in the context, say: 
"I could not find this information in the meeting transcript."

Always be concise and precise. If quoting someone, mention it clearly.

Context from meeting transcript:
{context}""",
        ),
        ("human", "{question}"),
    ])

    rag_chain = (
        {
            "context":  retriver| RunnableLambda(format_docs),
            "question": RunnablePassthrough(),
        }
        | prompt
        | llm
        | StrOutputParser()
    )

    log_rag("RAG chain load complete")
    return rag_chain


def ask_question(rag_chain, question:str) -> str:
    print(f"Question : {question}")
    answer = rag_chain.invoke(question)
    print(f"answer :{answer}")
    return answer
