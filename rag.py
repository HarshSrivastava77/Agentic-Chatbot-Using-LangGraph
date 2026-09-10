import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

FAISS_DB_PATH = Path(os.getenv("APP_DATA_DIR", ".")) / "faiss_db"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

TOP_K = 3

MAX_RAG_CHARS = 6000


# ============================================================
# EMBEDDINGS
# ============================================================

embeddings = HuggingFaceEmbeddings(
    model_name=EMBEDDING_MODEL
)


# ============================================================
# PDF INGESTION
# ============================================================

def ingest_rag_document(file_path: str) -> int:
    """
    Load a PDF, split it into chunks, create embeddings,
    and save the FAISS vector database.

    Returns:
        Number of chunks created.
    """

    if not os.path.exists(file_path):
        raise FileNotFoundError(
            f"PDF not found: {file_path}"
        )

    if not file_path.lower().endswith(".pdf"):
        raise ValueError(
            "Only PDF files are supported."
        )

    # --------------------------------------------------------
    # LOAD PDF
    # --------------------------------------------------------

    loader = PyPDFLoader(file_path)

    documents = loader.load()

    if not documents:
        raise ValueError(
            "The PDF contains no readable text."
        )

    # --------------------------------------------------------
    # CHUNK DOCUMENT
    # --------------------------------------------------------

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
            "",
        ],
    )

    chunks = splitter.split_documents(documents)

    if not chunks:
        raise ValueError(
            "No chunks were created from the PDF."
        )

    # --------------------------------------------------------
    # CREATE FAISS
    # --------------------------------------------------------

    vectorstore = FAISS.from_documents(
        chunks,
        embeddings,
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    FAISS_DB_PATH.mkdir(parents=True, exist_ok=True)

    vectorstore.save_local(
        FAISS_DB_PATH
    )

    # Clear cached retriever so the new document is loaded
    get_retriever.cache_clear()

    return len(chunks)


# ============================================================
# LOAD RETRIEVER
# ============================================================

@lru_cache(maxsize=1)
def get_retriever():
    """
    Load the local FAISS database and return a retriever.
    """

    index_file = os.path.join(
        FAISS_DB_PATH,
        "index.faiss",
    )

    pkl_file = os.path.join(
        FAISS_DB_PATH,
        "index.pkl",
    )

    if not os.path.exists(index_file):
        raise FileNotFoundError(
            "No FAISS index found. Please upload and index a PDF first."
        )

    if not os.path.exists(pkl_file):
        raise FileNotFoundError(
            "FAISS metadata file is missing."
        )

    vectorstore = FAISS.load_local(
        FAISS_DB_PATH,
        embeddings,
        allow_dangerous_deserialization=True,
    )

    return vectorstore.as_retriever(
        search_kwargs={
            "k": TOP_K,
        }
    )


# ============================================================
# RAG TOOL
# ============================================================

@tool
def rag_tool(query: str) -> str:
    """
    Search the currently indexed PDF for relevant information.

    Use this tool when the user asks questions about an uploaded PDF.
    """

    query = query.strip()

    if not query:
        return "No RAG query was provided."

    try:

        retriever = get_retriever()

        documents = retriever.invoke(query)

        if not documents:
            return (
                "No relevant information was found "
                "in the uploaded PDF."
            )

        results = []

        for i, document in enumerate(
            documents,
            start=1,
        ):

            page = document.metadata.get(
                "page",
                "unknown",
            )

            source = document.metadata.get(
                "source",
                "unknown",
            )

            content = document.page_content.strip()

            results.append(
                f"""
SOURCE {i}
Page: {page}
Source: {source}

{content}
"""
            )

        combined_results = "\n".join(results)

        return combined_results[:MAX_RAG_CHARS]

    except FileNotFoundError as e:
        return str(e)

    except Exception as e:
        return f"RAG retrieval failed: {e}"