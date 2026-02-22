"""
Agentic LLM loop for extracting relationship comments from email chains.

The LLM reads an email chain and repeatedly calls `add_relationship_comment`
to annotate relationships between people in the Neo4j graph.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from openai import OpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from graph import (
    get_driver,
    ensure_constraints,
    upsert_person,
    append_comment,
    append_comment_batch,
    append_comment_recipient_pairs,
    increment_email_count,
    get_all_edges,
    get_comments,
    set_summary,
)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

TOOL_ADD_ONE = {
    "type": "function",
    "function": {
        "name": "add_relationship_comment",
        "description": (
            "Record one observation about the relationship between two people. "
            "Use for a single pair or when each relationship has a different comment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_email": {"type": "string", "description": "Email of one person."},
                "to_email": {"type": "string", "description": "Email of the other person."},
                "comment": {"type": "string", "description": "Concise observation about this pair."},
            },
            "required": ["from_email", "to_email", "comment"],
        },
    },
}

TOOL_ADD_BATCH = {
    "type": "function",
    "function": {
        "name": "add_relationship_comments_batch",
        "description": (
            "Record the same observation for one sender and many recipients in one call "
            "(e.g. one person emailed a group). Creates sender–recipient edges and also "
            "links recipients to each other as 'same audience' (copied together). Use when "
            "one person communicated the same thing to multiple people."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_email": {"type": "string", "description": "Sender / central person."},
                "to_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses.",
                },
                "comment": {"type": "string", "description": "Concise observation (same for all)."},
            },
            "required": ["from_email", "to_emails", "comment"],
        },
    },
}

TOOL_SCHEMAS = [TOOL_ADD_ONE, TOOL_ADD_BATCH]

SYSTEM_PROMPT = """\
You are a relationship-extraction agent. You will receive an email chain and \
a list of email addresses that appear in it.

Your job: analyse the email chain and identify relationships between the \
people involved.

Tools:
- `add_relationship_comment`: one (from_email, to_email, comment). Use for a single pair \
  or when each relationship has a different observation.
- `add_relationship_comments_batch`: (from_email, to_emails[], comment). Use when one \
  person sent the same kind of communication to many recipients (e.g. group email). \
  Records sender–recipient edges and also links recipients to each other (same audience).

Guidelines:
- Only use email addresses from the provided list.
- Prefer the batch tool when one sender emailed many people with the same observation.
- Focus on professional dynamics: collaboration, delegation, disagreement, \
  mentorship, reporting, etc.
- Be specific and ground observations in the email content.
- When you have extracted all insights, stop calling tools and respond with \
  a brief summary of what you found.\
"""

# Match email addresses in chain text (e.g. FROM/TO lines in CSV-style chains).
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")


def parse_emails_from_chain(chain_text: str) -> list[str]:
    """Extract unique email addresses from CSV-style chain_text (FROM:/TO: lines)."""
    return list(dict.fromkeys(EMAIL_RE.findall(chain_text)))


def run_agent_from_chain_text(chain_text: str) -> str:
    """
    Run the agent on a single email chain string (e.g. chain_text from your CSV).
    Parses email addresses from the chain and calls run_agent.
    """
    addresses = parse_emails_from_chain(chain_text)
    if not addresses:
        return "(no email addresses found in chain)"
    return run_agent(addresses, chain_text)


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
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        assistant_msg = choice.message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            break

        for tool_call in assistant_msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            name = tool_call.function.name
            from_email = args["from_email"]
            comment = args["comment"]

            if name == "add_relationship_comments_batch":
                to_emails = args.get("to_emails") or []
                to_emails = [e for e in to_emails if e != from_email]
                recipient_comment = f"Same audience (copied together on email from {from_email}): {comment}"
                with driver.session() as session:
                    session.execute_write(
                        append_comment_batch, from_email, to_emails, comment
                    )
                    if len(to_emails) >= 2:
                        session.execute_write(
                            append_comment_recipient_pairs,
                            to_emails,
                            recipient_comment,
                        )
                for to_email in to_emails:
                    modified_pairs.add(tuple(sorted([from_email, to_email])))
                tool_result = {"status": "ok", "from": from_email, "to_count": len(to_emails)}
            else:
                to_email = args["to_email"]
                with driver.session() as session:
                    session.execute_write(append_comment, from_email, to_email, comment)
                modified_pairs.add(tuple(sorted([from_email, to_email])))
                tool_result = {"status": "ok", "from": from_email, "to": to_email}

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result),
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
