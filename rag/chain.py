from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from rag.retriever import get_vectorstore
from prompts.system_prompt import SYSTEM_PROMPT
from config.settings import (
    LLM_PROVIDER, TOP_K,
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

    Streaming (v6.5.0) splits the same work into steps so the app can show the
    grounding badge before generation starts:
        retrieved = chain.retrieve(question)          # the ONE search
        for text in chain.stream(inputs, retrieved):  # or chain.generate(...)
            ...
        chain.remember(question, answer)
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

    def retrieve(self, question: str) -> dict:
        # ONE search returning documents and scores. Same query, same k (TOP_K) and
        # same ranking as as_retriever(search_kwargs={"k": TOP_K}), whose default
        # "similarity" mode calls similarity_search_with_score and drops the scores.
        scored = self.vectorstore.similarity_search_with_score(question, k=TOP_K)
        docs = [doc for doc, _ in scored]
        retrieval_scores = []
        for doc, score in scored:
            item = {"source": doc.metadata.get("source", "desconhecido"), "score": float(score),
                    "excerpt": (doc.page_content or "")[:400]}
            if doc.metadata.get("page") is not None:
                item["page"] = doc.metadata["page"]
            retrieval_scores.append(item)
        return {
            "docs": docs,
            "retrieval_scores": retrieval_scores,
            "context": "\n\n".join(doc.page_content for doc in docs),
        }

    def _messages(self, inputs: dict, retrieved: dict):
        return self._prompt.format_messages(
            study_context=inputs.get("study_context", "No study context defined yet."),
            context=retrieved["context"],
            chat_history=self.chat_history,
            question=inputs["question"],
        )

    @staticmethod
    def _text(content) -> str:
        if isinstance(content, list):  # some providers return content parts
            return "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
        return content or ""

    def generate(self, inputs: dict, retrieved: dict) -> str:
        """Non-streaming generation over already-retrieved context."""
        return self._text(self.llm.invoke(self._messages(inputs, retrieved)).content)

    def stream(self, inputs: dict, retrieved: dict):
        """Yield answer text chunks over already-retrieved context."""
        for chunk in self.llm.stream(self._messages(inputs, retrieved)):
            text = self._text(getattr(chunk, "content", chunk))
            if text:
                yield text

    def remember(self, question: str, answer: str):
        """Update rolling window (max 10 turns = 20 messages)."""
        self.chat_history.append(HumanMessage(content=question))
        self.chat_history.append(AIMessage(content=answer))
        if len(self.chat_history) > 20:
            self.chat_history = self.chat_history[-20:]

    def invoke(self, inputs: dict) -> dict:
        question = inputs["question"]
        retrieved = self.retrieve(question)
        answer = self.generate(inputs, retrieved)
        self.remember(question, answer)
        return {
            "answer": answer,
            "source_documents": retrieved["docs"],
            "retrieval_scores": retrieved["retrieval_scores"],
        }


def build_chain() -> SINChain:
    return SINChain()
