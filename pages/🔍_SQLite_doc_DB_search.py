from utils.sqlite_doc_db import query
import streamlit as st
import asyncio


async def display() -> None:
    st.title("SQLite doc DB search")
    search = st.text_input(label="Data query")
    if search:
        data = await query([search])
        st.header("Data")
        st.dataframe(data, hide_index=True)


if __name__ == "__main__":
    asyncio.run(display())
