from autogen import AssistantAgent, GroupChat, GroupChatManager, Cache
from dotenv import load_dotenv
from langchain_community.document_loaders.directory import DirectoryLoader
from langchain_community.vectorstores.faiss import FAISS
from langchain_openai import AzureOpenAIEmbeddings
from langchain_text_splitters import TokenTextSplitter
from os import getenv
from os.path import isfile
from typing import Any
from typing import Tuple
from typing_extensions import Annotated
import asyncio
import pandas as pd
import re
import sqlite3
import streamlit as st


assert load_dotenv(), "Failed to load .env file"


@st.cache_resource
def get_business_db() -> sqlite3.Connection:
    business_db = sqlite3.connect(":memory:", check_same_thread=False)

    with open("resources/sql-db/create.sql") as f:
        business_db.executescript(f.read())

    with open("resources/sql-db/data.sql") as f:
        business_db.executescript(f.read())

    print("Loaded Business DB from script")
    return business_db


@st.cache_resource
def get_doc_db() -> FAISS:
    embeddings = AzureOpenAIEmbeddings(
        api_key=getenv("AOAI_API_KEY"),
        api_version="2023-12-01-preview",
        async_client=True,
        azure_deployment=getenv("AOAI_EMBEDDING_DEPLOYMENT"),
        azure_endpoint=getenv("AOAI_BASE_URL"),
        model=getenv("AOAI_EMBEDDING_MODEL"),
    )

    if isfile(".faiss-db/index.faiss"):
        doc_db = FAISS.load_local(
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
        doc_db = FAISS.from_documents(
            documents=documents,
            embedding=embeddings,
        )
        doc_db.save_local(".faiss-db")
        print("Saved Doc DB to disk")

    return doc_db


@st.cache_resource
def get_agent(_business_db: sqlite3.Connection, _doc_db: FAISS) -> GroupChatManager:
    llm_config = {
        "temperature": 0,
        "timeout": 120,
        "config_list": [
            {
                "api_key": getenv("AOAI_API_KEY"),
                "api_type": "azure",
                "api_version": "2023-12-01-preview",
                "base_url": getenv("AOAI_BASE_URL"),
                "model": getenv("AOAI_LLM_DEPLOYMENT"),
                "seed": 42,
            }
        ],
    }

    pm = AssistantAgent(
        llm_config=llm_config,
        name="product_manager",
        description="Product Manager, scope the project. Should be consulted at the beginning of the project.",
        system_message="""
            Assistant is a product manager, with 20 years of experience in the software industry.

            # Objective
            Define the project requirements and update the task backlog.

            # Rules
            - Do not add any introductory phrases
            - Only use functional terms
            - Preserve the data privacy at maximum
            - Use simple and clear language

            # Response format
            Project requirements:
            - xxx
            Implementation details:
            - xxx
            Expected columns:
            - column1: description of the column1
            - column2: description of the column2

            # Example 1
            Customer: I want to know the list of my customers plus their credit card number
            Product Manager:
            Project requirements:
            - List must be understandable for a human
            - List of the customers must be returned
            - Must preserve the privacy of the customers
            Implementation details:
            - Use a anonymized version of the credit card number
            Expected columns:
            - credit_card_hash: hash of the credit card number of the customer
            - email: hash of the email of the customer
            - name: name of the customer

            # Example 2
            Customer: For creating a loyalty program, I need to know the purchase details in store
            Product Manager:
            Project requirements:
            - List must be understandable for a human
            - A way to present the purchase details in store must be returned
            Implementation details:
            - Use the store name in the report
            - Purshase details can be aggregated by year, plus the median amount on weekday and weekend
            Expected columns:
            - med_weekday: median amount of the purchases on weekday
            - med_weekend: median amount of the purchases on weekend
            - store_name: name of the store
            - total_eur: total purchase amount in the period
            - year: year of the statistic
        """,
    )

    developer = AssistantAgent(
        llm_config=llm_config,
        name="developer",
        description="SQL Developer, write code. Use feedbacks and fixes from the team members to improve the code. Should be consulted to write the code.",
        system_message="""
            Assistant is a SQL Developer, with 20 years of experience in SQL.

            # Objective
            Write and debug SQL code to solve a problem.

            # Rules
            - Be concise and clear
            - Do not add any introductory phrases
            - Follow the business requirements as closely as possible
            - If the project is not feasible, answer "not feasible" and explain why
            - If there is no task or fix to implement, answer "nothing to do"
            - Make sure all the fixes are implemented before finishing
            - Propose a mitigation if a requirement is not feasible
            - Query must be executed as often as possible, to test it
            - Use security best practices
            - Use the feedbacks and fixes from the team members to improve the code
            - Write a clean and efficient code

            # Response format if the code is in progress
            ```sql
            xxx
            ```
            Explanations of the code:
            - xxx

            # Response format if the code is not feasible
            not feasible

            # Response format if there is nothing to do
            nothing to do

            # Example 1
            Customer: list of ID of my customers
            Developer:
            ```sql
            SELECT UNIQUE id FROM customers
            ```
            Explanations of the code:
            - One ID per customer is returned

            # Example 2
            Customer: list of my customers
            Developer:
            ```sql
            SELECT * FROM customers
            ```
            Explanations of the code:
            - All customer fields are returned
        """,
    )

    qa = AssistantAgent(
        llm_config=llm_config,
        name="quality_analyst",
        description="Quality Analyst, provide feedbacks on the code. After a code is written, review it. Should be consulted to review the code.",
        system_message="""
            Assistant is a quality analyst, with 20 years of experience in the quality insurance. Assistant is perfectionist and has a keen eye for detail.

            # Objective
            Review a code, confirm it works as expected and provide feedback.

            # Rules
            - Be tricky, quality is the highest priority
            - Database structure cannot be changed, do your best with the current structure
            - Do not add any introductory phrases
            - If a change requires a specific skill, explain it
            - If the test query result is empty, male sure to double check the query
            - If there are no fixes to implement to the latest proposal, answer "query is validated"
            - Query must be tested and reviewed before validating
            - Use specific and detailed language

            # Metrics to check
            - Bugs
            - Maintainability
            - Performance
            - Security

            # Response format if the code is in progress
            Fixes to implement:
            - xxx
            Performance improvements:
            - xxx
            Security issues:
            - xxx

            # Response format if the code is validated
            query is validated

            # Example 1
            Customer: list of ID of my customers
            Developer: SELECT UNIQUE id FROM customers
            Quality Analyst: query is validated

            # Example 2
            Customer: list of my customers
            Developer: SELECT * FROM customers
            Tools: execute the query
            Quality Analyst:
            Query result: [(1, 'John', 'john@gmail.com')]
            Executes the query.
            Fixes to implement:
            - Response may be too large, consider which fields are needed
            Security issues:
            - Field "password" and "credit_card" never should be returned as is, consider using a hash for all sensitive fields

            # Example 3
            Customer: mean of the purchases (EUR) in 2022 for sports products
            Developer: SELECT AVG(total_eur) FROM purchases WHERE date BETWEEN '2022-01-01' AND '2022-11-31' AND category = 'sports'
            Tools: execute the query
            Quality Analyst:
            Query result: []
            Fixes to implement:
            - End date selection is wrong by 1 month, should be '2022-12-31'
            - Result is empty, must validate if category filter is correct, an extract of the categories could help
            Performance improvements:
            - If latency is high, consider using an approximate average

            # Example 4
            Customer: popularity of the products
            Developer: SELECT b.brand_id, b.brand_name, (RANDOM() % 100) + 1 FROM brands b
            Quality Analyst:
            Fixes to implement:
            - Popularity cannot be random, must be deterministic

            # Example 5
            Customer: high spenders
            Developer: SELECT * FROM customers WHERE total_eur > 1000
            Quality Analyst:
            Fixes to implement:
            - Without knowing the distribution of the purshases, it is hard to define a high spender, consider using a percentile
        """,
    )

    group = GroupChat(
        agents=[developer, qa, pm],
        max_round=50,
        messages=[],
        send_introductions=True,
    )

    manager = GroupChatManager(
        groupchat=group,
        is_termination_msg=lambda x: x.get("name", "") == qa.name
        and bool(
            re.search(
                "query is validated", re.sub(r"\W+", " ", x.get("content", "").lower())
            )
        ),
        llm_config=llm_config,
    )

    @pm.register_for_execution()
    @developer.register_for_llm(
        description="Get the SQL engine information, such as the version and the software used"
    )
    @st.cache_data
    def _sql_engine() -> Annotated[str, "SQL engine information"]:
        return f"SQLite v{sqlite3.sqlite_version}"

    @pm.register_for_execution()
    @developer.register_for_llm(
        description="Get the SQL schema of the database. Use it to understand the structure of the database."
    )
    @st.cache_data
    def _sql_schema() -> Annotated[str, "Raw SQL schema."]:
        return "\n".join(
            " ".join(sublist)
            for sublist in _business_db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table'"
            ).fetchall()
        )

    @pm.register_for_execution()
    @developer.register_for_llm(
        description="Run a SQL query on the database, only SELECT actions are allowed"
    )
    @qa.register_for_llm(
        description="Run a SQL query on the database, only SELECT actions are allowed"
    )
    @st.cache_data
    def _sql_execute(
        next_step: Annotated[
            str,
            "What to do after executing the query, must include action and who should do it",
        ],
        purpose: Annotated[
            str,
            "Purpose of executing this query, must include the reason and the expected result",
        ],
        query: Annotated[str, "SQL query"],
    ) -> Annotated[
        dict[str, Any],
        "Dictionary with result, first 5 rows of the result are returned, but total count is included",
    ]:
        if any(word in ["insert", "update", "delete"] for word in query.split()):
            return {
                "error": "Only SELECT queries are allowed",
                "next_step": next_step,
                "purpose": purpose,
            }
        try:
            cursor = _business_db.execute(query)
            result = cursor.fetchall()
            total = len(result)
            return {
                "next_step": next_step,
                "purpose": purpose,
                "result": result[:5],
                "total": total,
            }
        except sqlite3.Error as e:
            return {
                "error": f"Failed to execute query: {e}",
                "next_step": next_step,
                "purpose": purpose,
            }

    @pm.register_for_execution()
    @developer.register_for_llm(
        description="Search in the SQL documentation. Use it to understand how functions and syntax work."
    )
    @qa.register_for_llm(
        description="Search in SQL engine documentation. Use it to understand how functions and syntax work."
    )
    @st.cache_data
    async def _sql_doc(
        searches: Annotated[
            list[str],
            "Multiple sentences to search into the documentation database, each one should be few words, use them to expand the field of view",
        ],
    ) -> Annotated[str, "Documentation of the function or syntax"]:
        docs = []
        for search in searches:
            docs += await _doc_db.asimilarity_search(query=search, k=3)
        return "\n".join([doc.page_content for doc in docs])

    return manager


async def run(
    request: str, agent: GroupChatManager, business_db: sqlite3.Connection
) -> Tuple[str, str]:
    with Cache.disk(cache_path_root=".autogen") as cache:
        res = await agent.a_initiate_chat(
            cache=cache,  # type: ignore
            message=request,
            recipient=agent,
            summary_method="reflection_with_llm",
            summary_args={
                "summary_prompt": f"""
                    Assistant is a business analyst, with 20 years of experience in the technology field.

                    # Objective
                    Answer to a customer's request, asking for a SQL query. Use the conversation with the engineering team as your source of information.

                    # Rules
                    - Do not add any introductory phrases
                    - Usage notes are made to help the customer use the query and understand the result
                    - Use simple language, understandable by any non-technical person

                    # Customer request
                    {request}

                    # Response format
                    SQL query:
                    ```sql
                    xxx
                    ```
                    Usage notes:
                    - xxx
                """,
            },
        )

    sql_query = res.summary.split("```sql\n")[1].split("\n```")[0]
    usage_notes = res.summary.split("Usage notes:\n")[1]

    return (usage_notes, sql_query)


@st.cache_data
def query_to_df(query: str, _business_db: sqlite3.Connection) -> pd.DataFrame:
    cur = _business_db.cursor()
    cur.execute(query)
    columns = [i[0] for i in cur.description]
    data = pd.DataFrame(cur.fetchall(), columns=columns)
    return data


async def main() -> None:
    business_db = get_business_db()
    doc_db = get_doc_db()
    agent = get_agent(business_db, doc_db)

    st.title("SQL agent")
    st.caption(
        "A SQL agent to help you with your database. It can help you to write SQL queries, understand the data, and search in easily. Technically, it is a group chat with multiple LLM agents: a product manager, a SQL developer, and a quality analyst. All are working together to help you with your SQL request."
    )
    semantic_input = st.text_input(
        label="What is your request?",
        placeholder="A sentence to describe what you want to see in the database",
    )
    if semantic_input:
        notes, query = await run(semantic_input, agent, business_db)
        data = query_to_df(query, business_db)
        st.header("Notes")
        st.markdown(notes)
        st.header("Data")
        st.dataframe(data, hide_index=True)
        st.header("SQL query")
        st.code(query, language="sql")


if __name__ == "__main__":
    st.set_page_config(page_title="SQL agent", page_icon="📊")
    asyncio.run(main())
