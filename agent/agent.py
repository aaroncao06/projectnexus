"""
Agentic LLM loop for extracting relationship comments from email chains.

The LLM reads an email chain and repeatedly calls `add_relationship_comment`
to annotate relationships between people in the Neo4j graph.
"""

from __future__ import annotations

import json
from typing import Optional

from openai import OpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from graph import (
    get_driver,
    ensure_constraints,
    upsert_person,
    append_comment,
    increment_email_count,
    get_all_edges,
    get_comments,
    set_summary,
)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "add_relationship_comment",
        "description": (
            "Record one observation about the relationship between two people "
            "based on the email chain. Call this once for each distinct "
            "relationship insight you find. The comment should be a concise "
            "description of how these two people relate or interact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_email": {
                    "type": "string",
                    "description": "Email address of one person in the relationship.",
                },
                "to_email": {
                    "type": "string",
                    "description": "Email address of the other person in the relationship.",
                },
                "comment": {
                    "type": "string",
                    "description": (
                        "A concise observation about the relationship between "
                        "these two people, derived from the email chain."
                    ),
                },
            },
            "required": ["from_email", "to_email", "comment"],
        },
    },
}

SYSTEM_PROMPT = """\
You are a relationship-extraction agent. You will receive an email chain and \
a list of email addresses that appear in it.

Your job: analyse the email chain and identify relationships between the \
people involved. For every meaningful relationship insight you find, call the \
`add_relationship_comment` tool with the two email addresses and a concise \
comment describing the relationship (e.g. "Alice delegated the design review \
to Bob", "Carol and Dave disagree on the timeline").

Guidelines:
- Only use email addresses from the provided list.
- One tool call per observation — make as many calls as needed.
- Focus on professional dynamics: collaboration, delegation, disagreement, \
  mentorship, reporting, etc.
- Be specific and ground observations in the email content.
- When you have extracted all insights, stop calling tools and respond with \
  a brief summary of what you found.\
"""


def run_agent(email_addresses: list[str], email_chain: str) -> str:
    """
    Run the agentic loop on one email chain.

    Returns a text summary of what was ingested.
    """
    driver = get_driver()
    ensure_constraints(driver)

    with driver.session() as session:
        for email in email_addresses:
            session.execute_write(upsert_person, email)

    address_list = "\n".join(f"- {addr}" for addr in email_addresses)
    user_message = (
        f"Email addresses involved:\n{address_list}\n\n"
        f"--- EMAIL CHAIN ---\n{email_chain}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    modified_pairs: set[tuple[str, str]] = set()

    while True:
        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            tools=[TOOL_SCHEMA],
            tool_choice="auto",
        )

        choice = response.choices[0]
        assistant_msg = choice.message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            break

        for tool_call in assistant_msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            from_email = args["from_email"]
            to_email = args["to_email"]
            comment = args["comment"]

            with driver.session() as session:
                session.execute_write(append_comment, from_email, to_email, comment)

            pair = tuple(sorted([from_email, to_email]))
            modified_pairs.add(pair)

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps({"status": "ok", "from": from_email, "to": to_email}),
            })

    # Increment email_count once per modified pair for this email chain
    with driver.session() as session:
        for pair in modified_pairs:
            session.execute_write(increment_email_count, pair[0], pair[1])

    driver.close()

    summary = assistant_msg.content or "(no summary returned)"
    print(f"Agent finished: {len(modified_pairs)} relationship(s) annotated.")
    return summary


def summarize_edges(emails: Optional[list[str]] = None) -> int:
    """
    Generate LLM summaries for edges that have comments.

    If `emails` is provided, only summarize edges involving those addresses.
    Returns the number of edges summarized.
    """
    driver = get_driver()
    count = 0

    with driver.session() as session:
        edges = session.execute_read(get_all_edges)

    if emails:
        email_set = set(emails)
        edges = [e for e in edges if e["email_a"] in email_set or e["email_b"] in email_set]

    for edge in edges:
        comments = edge["comments"]
        if not comments:
            continue

        comment_text = "\n".join(f"- {c}" for c in comments)
        prompt = (
            f"Below are observations about the relationship between "
            f"{edge['email_a']} and {edge['email_b']}:\n\n"
            f"{comment_text}\n\n"
            f"Write a 1-2 sentence summary of their overall relationship."
        )

        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )

        summary = response.choices[0].message.content.strip()
        with driver.session() as session:
            session.execute_write(set_summary, edge["email_a"], edge["email_b"], summary)

        print(f"  Summarized {edge['email_a']} <-> {edge['email_b']}")
        count += 1

    driver.close()
    print(f"Summarized {count} edge(s).")
    return count
