from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage
from langchain_ollama import ChatOllama
from rag.retriever import get_retriever
from prompts.system_prompt import SYSTEM_PROMPT
from config.settings import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL


class SINChain:
    """
    Conversational RAG chain using LCEL.
    Keeps last 10 turns (20 messages) in memory.
    Simulation intent and context handling logic lives in the system prompt.

    Interface: chain.invoke({"question": ..., "study_context": ...})
               → {"answer": ..., "source_documents": [...]}
    """

    def __init__(self):
        self.llm = ChatOllama(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_CHAT_MODEL,
            temperature=0.2,
        )
        self.retriever = get_retriever()
        self.chat_history: list = []

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{question}"),
        ])

    def invoke(self, inputs: dict) -> dict:
        question = inputs["question"]
        study_context = inputs.get("study_context", "No study context defined yet.")

        docs = self.retriever.invoke(question)
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
