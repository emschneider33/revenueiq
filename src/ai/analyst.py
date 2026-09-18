"""RevenueIQ AI analyst -- Claude-powered tool-calling layer (Phase 4).

Claude never invents metrics here. Every number in a response comes
from one of the analytics functions in src/analytics/, invoked as a
tool call -- this file's only job is to send the conversation to
Claude, route any tool requests it makes to those functions (via
src/ai/tools.py), hand the results back, and repeat until Claude has
enough to give a plain-text answer.

Usage:
    python -m src.ai.analyst

Requires ANTHROPIC_API_KEY in .env (same file as your MySQL
credentials). There's no Streamlit UI yet (Phase 5) -- this is a
terminal chat loop for testing the tool-calling layer on its own
first.
"""

import json
import os

import anthropic
from dotenv import load_dotenv

from src.ai.tools import TOOL_SPECS, call_tool
from src.ingestion.db import get_engine

load_dotenv()

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TOOL_ROUNDS = 6  # safety cap on back-and-forth tool calls per question,
                      # so a confused model can't loop forever burning API calls

SYSTEM_PROMPT = """You are the RevenueIQ analyst: an AI that explains \
revenue and customer trends for a grocery retailer, built on the \
Dunnhumby "Complete Journey" dataset (2,500 households, roughly 2 \
years of transactions, 2016-01 through 2017-12-11).

CORE RULE: you never invent, estimate, or calculate a number yourself. \
Every figure in your answer must come from calling one of the \
available tools -- each one runs a reviewed SQL view, not an ad-hoc \
query. If no tool covers what's being asked, say so plainly instead of \
guessing or approximating.

Known data caveats to keep in mind when interpreting results (don't \
recite these unprompted -- only mention the ones actually relevant to \
the question being asked):
- Dates are synthetic: day_number=1 is anchored to 2016-01-01, an \
  arbitrary reference point with no real-world meaning.
- January 2016 and December 2017 are partial/ramp-up periods, not real \
  revenue declines -- the customer panel was still ramping up in early \
  2016, and the dataset's collection window stops 11 days into \
  December 2017. get_monthly_revenue_anomalies already flags these two \
  months as a known partial period rather than scoring them.
- Recency/tenure/churn metrics are relative to the dataset's own last \
  transaction day, not today's real date -- there is no live "today."
- Only about 801 of 2,500 households have demographic data.
- Promotion effectiveness (get_promotion_lift_summary, \
  get_product_promotion_lift) compares product/store/weeks with a \
  matching causal_data record ("Promoted") against product/store/weeks \
  with none ("Not Promoted") -- it excludes gas-station/kiosk sales, \
  and treats any non-'0' display/mailer code as "Promoted" without \
  distinguishing placement types. Per-product lift is only computed \
  for products with at least 3 promoted and 3 not-promoted weeks of \
  data.

Answer like an analyst briefing a stakeholder: lead with the finding, \
cite the specific numbers behind it, and mention a data caveat only \
when it would change how the number should be read."""


def run_conversation(engine, client, messages):
    """Send `messages` to Claude, executing any tool calls it makes,
    until it returns a final text answer.

    Returns (answer_text, updated_messages) so the caller can keep
    building on the same conversation across turns.
    """
    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=TOOL_SPECS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            return text, messages

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                result = call_tool(block.name, block.input, engine)
                content = json.dumps(result, default=str)
            except Exception as exc:  # noqa: BLE001 -- report any tool failure
                # back to Claude as a tool error rather than crashing the chat
                content = json.dumps({"error": str(exc)})
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": content,
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return (
        "I wasn't able to finish answering that within the allowed number "
        "of tool calls -- try breaking the question into a smaller piece.",
        messages,
    )


def main():
    engine = get_engine()
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    print("RevenueIQ analyst -- ask a question about the business.")
    print("Type 'exit' or Ctrl+C to quit.\n")

    messages = []
    while True:
        try:
            question = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            break

        messages.append({"role": "user", "content": question})
        answer, messages = run_conversation(engine, client, messages)
        print(f"\nAnalyst: {answer}\n")


if __name__ == "__main__":
    main()
