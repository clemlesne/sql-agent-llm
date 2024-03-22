import pandas as pd
import sqlite3
import streamlit as st


@st.cache_resource
def get_db() -> sqlite3.Connection:
    business_db = sqlite3.connect(":memory:", check_same_thread=False)

    with open("resources/sql-db/create.sql") as f:
        business_db.executescript(f.read())

    with open("resources/sql-db/data.sql") as f:
        business_db.executescript(f.read())

    print("Loaded Business DB from script")
    return business_db


def query(query: str) -> pd.DataFrame:
    cur = get_db().cursor()
    cur.execute(query)
    columns = [i[0] for i in cur.description]
    data = pd.DataFrame(cur.fetchall(), columns=columns)
    return data
