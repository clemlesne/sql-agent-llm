from autogen import AssistantAgent, GroupChat, GroupChatManager, Cache
from os import getenv
from typing import Any
from typing import Tuple
from typing_extensions import Annotated
from utils.business_db import query as business_db_query, get_db as business_db_get
from utils.sqlite_doc_db import query as sqlite_doc_db_query
import asyncio
import re
import sqlite3
import streamlit as st


@st.cache_resource
def get_agent() -> GroupChatManager:
    gpt4_config = {
        "max_tokens": 1000,
        "temperature": 0,
        "timeout": 180,
        "config_list": [
            {
                "api_key": getenv("AOAI_API_KEY"),
                "api_type": "azure",
                "api_version": "2023-12-01-preview",
                "base_url": getenv("AOAI_BASE_URL"),
                "model": getenv("AOAI_LLM_DEPLOYMENT"),
            }
        ],
    }

    pm = AssistantAgent(
        llm_config=gpt4_config,
        name="product_manager",
        description="Product Manager, scope the project. Must be consulted to start the conversation, plus if a team member requests a change.",
        system_message="""
            Assistant is a product manager with 20 years' experience in the software industry.

            # Objective
            Define project requirements and update tasks backlog.

            # Rules
            - Do not add any introductory phrases
            - For complex tasks, cut them into smaller pieces
            - For each task, provide a status, clear description, expected result, acceptance criteria, and owner
            - If team started to work without scoping, scope the project first
            - Only use functional terms
            - Preserve the data privacy at maximum
            - Project is restricted to creating a SQL query to solve a problem
            - The project is completed when all tasks are in status "done"
            - Use simple and clear language
            - Use the feedbacks from the team members to update the tasks

            # Response format if the project is in progress
            Task 1
            Acceptance criteria: xxx
            Description: xxx
            Expected result: xxx
            Name: xxx
            Owner: xxx
            Status: todo / in progress / done

            Task 2
            xxx

            # Response format if the project is completed
            project is completed
        """,
    )

    developer = AssistantAgent(
        llm_config=gpt4_config,
        name="developer",
        description="SQL Developer, write code. Use team members' comments and corrections to improve code. Must be consulted when writing code.",
        system_message="""
            Assistant is a SQL developer, with 20 years' experience in SQL.

            # Objective
            Write and debug SQL to solve a problem.

            # Rules
            - Always answer with a SQL query
            - Be concise and clear
            - Do not add any introductory phrases
            - Follow the business requirements as closely as possible
            - If a task is not feasible, answer "task xxx is not feasible" and explain why
            - If a task should be updated, argue why
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
            What changed:
            - xxx

            # Response format if a task is not feasible
            task xxx is not feasible
            Reasons:
            - xxx
        """,
    )

    qa = AssistantAgent(
        llm_config=gpt4_config,
        name="quality_analyst",
        description="Quality Analyst, provide feedbacks on the code. After writing code, review it. Must be consulted to review code after developer.",
        system_message="""
            Assistant is a quality analyst with 20 years' experience in quality assurance. Assistant is a perfectionist with an eye for detail.

            # Objective
            Examine SQL code written by the developer, confirm that it works as expected and provide feedback.

            # Rules
            - Always use deterministic queries, never use random functions or static values
            - Be tricky, quality is the highest priority
            - Database structure cannot be changed, do your best with the current structure
            - Do not add any introductory phrases
            - If a change requires a specific skill, explain it
            - If a task should be updated, argue why
            - If the test query result is empty, male sure to double check the query
            - If there are no fixes to implement to the latest code solving a task, answer "task xxx is validated"
            - Query must be tested and reviewed before validating
            - Use specific and detailed language

            # Metrics to check
            - Bugs
            - Maintainability
            - Performance
            - Security

            # Response format if the task is in progress
            Fixes to implement to task xxx:
            - xxx

            # Response format if a task is validated
            task xxx is validated
        """,
    )

    group = GroupChat(
        admin_name=None,
        agents=[developer, qa, pm],
        max_round=50,
        messages=[],
        send_introductions=True,
    )

    manager = GroupChatManager(
        groupchat=group,
        is_termination_msg=lambda x: x.get("name", "") == pm.name
        and bool(
            re.search(
                "project is completed", re.sub(r"\W+", " ", x.get("content", "").lower())
            )
        ),
        llm_config=gpt4_config,
    )

    @developer.register_for_execution()
    @developer.register_for_llm(
        description="Get the SQL engine information, such as the version and the software used"
    )
    def _sql_engine() -> Annotated[str, "SQL engine information"]:
        return f"SQLite v{sqlite3.sqlite_version}"

    @developer.register_for_execution()
    @developer.register_for_llm(
        description="Get the SQL schema of the database. Use it to understand the structure of the database."
    )
    def _sql_schema() -> Annotated[str, "Raw SQL schema."]:
        return "\n".join(
            " ".join(sublist)
            for sublist in business_db_get().execute(
                "SELECT sql FROM sqlite_master WHERE type='table'"
            ).fetchall()
        )

    @qa.register_for_execution()
    @qa.register_for_llm(
        description="Run a SQL query on the database, only SELECT actions are allowed"
    )
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
            cursor = business_db_get().execute(query)
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

    @developer.register_for_execution()
    @developer.register_for_llm(
        description="Search in the SQL documentation. Use it to understand how functions and syntax work."
    )
    async def _sql_doc(
        searches: Annotated[
            list[str],
            "Multiple sentences to search into the documentation database, each one should be few words, use them to expand the field of view",
        ],
    ) -> Annotated[str, "Documentation of the function or syntax"]:
        return (await sqlite_doc_db_query(searches)).to_json()

    return manager


async def run(request: str, agent: GroupChatManager) -> Tuple[str, str]:
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
                    - Use Markdown to format the response (e.g. bullet points, code blocks, etc.)
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


async def display() -> None:
    agent = get_agent()


    st.title("SQL agent")
    st.caption("""
        [Project is hosted on GitHub.](https://github.com/clemlesne/sql-agent-llm)

        This application help you with your database. It can help you to write SQL queries, understand the data, and search in easily.

        Technically, it is a group chat with multiple LLM agents. All are working together to help you with your SQL request. The agents are:

        - Product manager, to scope the project
        - Quality analyst, to review the code
        - SQL developer, to write the code
    """)
    semantic_input = st.text_input(
        label="What is your request?",
        placeholder="A sentence to describe what you want to see in the database",
    )

    if semantic_input:
        # Run agent
        notes, query = await run(semantic_input, agent)
        # Update frontend
        data = business_db_query(query)
        st.header("Notes")
        st.markdown(notes)
        st.header("Data")
        st.dataframe(data, hide_index=True)
        st.header("SQL query")
        st.code(query, language="sql")


if __name__ == "__main__":
    asyncio.run(display())
