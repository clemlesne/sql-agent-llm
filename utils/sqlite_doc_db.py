from langchain_community.document_loaders.directory import DirectoryLoader
from langchain_community.vectorstores.faiss import FAISS
from langchain_community.vectorstores.faiss import FAISS
from langchain_core.documents import Document
from langchain_openai import AzureOpenAIEmbeddings
from langchain_openai import AzureOpenAIEmbeddings
from langchain_text_splitters import TokenTextSplitter
from os import getenv
from os.path import isfile
import pandas as pd
import streamlit as st


@st.cache_resource
def get_db() -> FAISS:
    embeddings = AzureOpenAIEmbeddings(
        api_key=getenv("AOAI_API_KEY"),
        api_version="2023-12-01-preview",
        azure_deployment=getenv("AOAI_EMBEDDING_DEPLOYMENT"),
        azure_endpoint=getenv("AOAI_BASE_URL"),
        model=getenv("AOAI_EMBEDDING_MODEL"),
    )

    if isfile(".faiss-db/index.faiss"):
        sqlite_doc_db = FAISS.load_local(
            allow_dangerous_deserialization=True,
            embeddings=embeddings,
            folder_path=".faiss-db",
        )
        print("Loaded Doc DB from cache")

    else:
        print("Doc DB cache not found, building from scratch")
        raw_documents = DirectoryLoader(
            glob="*.html",
            path="resources/sqlite-doc",
            recursive=True,
        ).load()
        print(f"Loaded {len(raw_documents)} documents")
        documents = TokenTextSplitter(
            chunk_overlap=20,  # 10% overlap
            chunk_size=200,  # 200 tokens is small but enhances retrieval
        ).split_documents(raw_documents)
        print(f"Splited to {len(documents)} chuncks")
        sqlite_doc_db = FAISS.from_documents(
            documents=documents,
            embedding=embeddings,
        )
        sqlite_doc_db.save_local(".faiss-db")
        print("Saved Doc DB to disk")

    return sqlite_doc_db


async def query(searches: list[str]) -> pd.DataFrame:
    if not searches:
        return "No search terms provided"
    docs: list[Document] = []
    for search in searches:
        docs += await get_db().asimilarity_search(query=search, k=3)
    df = pd.DataFrame([
        {
            "content": doc.page_content,
            "metadata": doc.metadata,
        }
        for doc in docs
    ])
    return df
