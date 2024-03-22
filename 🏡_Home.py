from dotenv import load_dotenv
import streamlit as st


assert load_dotenv(), "Failed to load .env file"


st.title("Welcome to SQL Agent LLM")

st.header("Main functionalities")
st.page_link("pages/🪄_SQL_agent.py")

st.header("Debug tools")
st.page_link("pages/🔍_Business_DB_search.py")
st.page_link("pages/🔍_SQLite_doc_DB_search.py")
