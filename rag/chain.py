from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_ollama import ChatOllama
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from prompts.system_prompt import SYSTEM_PROMPT
from config.settings import (
    OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, OLLAMA_EMBED_MODEL,
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
    TOP_K, SIMILARITY_THRESHOLD,
)

# ── Intent detection ──────────────────────────────────────────────────────────
SIMULATION_INTENT_KEYWORDS = [
    "quero simular", "gostaria de simular", "preciso simular",
    "vou simular", "rodar o anarede", "executar anarede",
    "fazer um estudo", "iniciar estudo", "começar estudo",
    "inserir bess", "alocar bess", "localizar bess",
    "estudo de fluxo", "fluxo de potência",
    "arquivo pwf", "preciso do pwf", "baixar pwf",
    "i want to simulate", "simulate a bess",
]


def is_simulation_intent(message: str) -> bool:
    message_lower = message.lower()
    return any(kw in message_lower for kw in SIMULATION_INTENT_KEYWORDS)


# ── Chain ─────────────────────────────────────────────────────────────────────
class SINChain:
    """
    Conversational RAG chain using LCEL with dual-retriever intent routing.

    - Factual questions → retriever_strict (similarity_score_threshold=0.45)
    - Simulation intent → retriever_open (top_k=2, no threshold, minimal grounding)

    Interface: chain.invoke({"question": ..., "study_context": ...})
               → {"answer": ..., "source_documents": [...]}
    """

    def __init__(self):
        self.llm = ChatOllama(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_CHAT_MODEL,
            temperature=0.2,
        )
        self.chat_history: list = []

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ])

        # Build shared vectorstore and both retrievers
        embeddings = OllamaEmbeddings(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_EMBED_MODEL,
        )
        vectorstore = QdrantVectorStore.from_existing_collection(
            embedding=embeddings,
            url=f"http://{QDRANT_HOST}:{QDRANT_PORT}",
            collection_name=QDRANT_COLLECTION,
        )

        # For factual questions: strict threshold filters out irrelevant chunks
        self.retriever_strict = vectorstore.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={
                "k": TOP_K,
                "score_threshold": SIMILARITY_THRESHOLD,
            },
        )

        # For simulation intent: minimal context, no threshold — system prompt handles flow
        self.retriever_open = vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 2},
        )

    def invoke(self, inputs: dict) -> dict:
        question = inputs["question"]
        study_context = inputs.get("study_context", "No study context defined yet.")

        # Route to appropriate retriever based on intent
        if is_simulation_intent(question):
            docs = self.retriever_open.invoke(question)
        else:
            docs = self.retriever_strict.invoke(question)

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
        }


def build_chain() -> SINChain:
    return SINChain()
