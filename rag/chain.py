from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from rag.retriever import get_vectorstore
from config.settings import TOP_K
from prompts.system_prompt import SYSTEM_PROMPT
from config.settings import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL,
    GOOGLE_API_KEY, GEMINI_CHAT_MODEL,
)


def get_llm():
    if LLM_PROVIDER == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=GEMINI_CHAT_MODEL,
            google_api_key=GOOGLE_API_KEY,
            temperature=0.1,
            convert_system_message_to_human=False,
        )
    else:
        from langchain_ollama import ChatOllama
        return ChatOllama(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_CHAT_MODEL,
            temperature=0.1,
        )


class SINChain:
    """
    Conversational RAG chain using LCEL.
    Keeps last 10 turns (20 messages) in memory.
    Simulation intent and context handling logic lives in the system prompt.

    Interface: chain.invoke({"question": ..., "study_context": ...})
               → {"answer": ..., "source_documents": [...],
                  "retrieval_scores": [{"source": ..., "score": ...}, ...]}
    """

    def __init__(self):
        self.llm = get_llm()
        self.vectorstore = get_vectorstore()
        self.chat_history: list = []

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ])

    def invoke(self, inputs: dict) -> dict:
        question = inputs["question"]
        study_context = inputs.get("study_context", "No study context defined yet.")

        # Same similarity search as as_retriever(k=TOP_K), but keeps the scores.
        scored = self.vectorstore.similarity_search_with_score(question, k=TOP_K)
        docs = [doc for doc, _ in scored]
        retrieval_scores = [
            {"source": doc.metadata.get("source", "desconhecido"), "score": float(score)}
            for doc, score in scored
        ]
        context = "\n\n".join(doc.page_content for doc in docs)

        messages = self._prompt.format_messages(
            study_context=study_context,
            context=context,
            chat_history=self.chat_history,
            question=question,
        )

        response = self.llm.invoke(messages)
        answer = response.content

        # Update rolling window (max 10 turns = 20 messages)
        self.chat_history.append(HumanMessage(content=question))
        self.chat_history.append(AIMessage(content=answer))
        if len(self.chat_history) > 20:
            self.chat_history = self.chat_history[-20:]

        return {
            "answer": answer,
            "source_documents": docs,
            "retrieval_scores": retrieval_scores,
        }


def build_chain() -> SINChain:
    return SINChain()
