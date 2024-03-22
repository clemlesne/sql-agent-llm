from utils.business_db import query
import streamlit as st


def display() -> None:
    st.title("Business DB search")
    search = st.text_input(label="SQL query")
    if search:
        data = query(search)
        st.header("Data")
        st.dataframe(data, hide_index=True)


if __name__ == "__main__":
    display()
