"""One-time dataset generator (SPEC §9). Run ONCE offline; output is frozen and
committed. Never regenerated between runs. Produces 100 gold-labeled synthetic
tickets matching the §9 composition table, plus dataset/orders.json.

Usage: python scripts/generate_dataset.py
"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dataset" / "tickets.jsonl"
ORDERS_OUT = ROOT / "dataset" / "orders.json"

rng = random.Random(20261014)  # deterministic generation

TIERS = ["FREE", "PRO", "ENTERPRISE"]

QUEUE = {
    "PASSWORD_RESET": "account-agents",
    "ORDER_STATUS": "order-agents",
    "BILLING_DISPUTE": "billing-agents",
    "BUG_REPORT": "bug-triage",
    "CANCELLATION": "retention-agents",
    "GENERAL_INQUIRY": "support-agents",
}


def customer():
    return {
        "tier": rng.choice(TIERS),
        "account_age_days": rng.randint(5, 2000),
        "prior_tickets": rng.randint(0, 12),
    }


def gold(category, priority, escalate, strategy):
    return {
        "category": category,
        "priority": priority,
        "escalate": escalate,
        "queue": QUEUE[category] if escalate else "",
        "strategy": strategy,
    }


tickets = []

# --- 30 simple template-resolvable (password reset, how-do-I) ---
pw_subjects = [
    ("Can't log in to my account", "I forgot my password and the reset link never arrived in my inbox. Can you resend it?"),
    ("Locked out after too many attempts", "I typed my password wrong three times and now I am locked out. Please help me reset it."),
    ("Password reset email not arriving", "I requested a password reset twice but no email shows up, not even in spam."),
    ("Need to reset my password", "New phone, lost my saved credentials. How do I reset my password?"),
    ("2FA device lost, can't sign in", "I lost the phone I used for login codes. I need to reset my credentials to get back in."),
]
howto_subjects = [
    ("How do I export my data?", "I was wondering how to export my project data to CSV. Is there a guide?"),
    ("Question about team seats", "Quick question: how do I add another member to my workspace?"),
    ("How to change my email address", "Can you tell me how to update the email on my account?"),
    ("Where can I find invoices?", "Just a question - where in the dashboard can I download past invoices?"),
    ("How do I enable dark mode?", "I was wondering if there is a dark mode and how to turn it on."),
]
for i in range(30):
    if i < 18:
        subj, body = pw_subjects[i % len(pw_subjects)]
        cat = "PASSWORD_RESET"
    else:
        subj, body = howto_subjects[i % len(howto_subjects)]
        cat = "GENERAL_INQUIRY"
    tickets.append(
        {
            "subject": subj,
            "body": body + f" (ref #{1000 + i})",
            "customer": customer(),
            "gold": gold(cat, "LOW", False, "TEMPLATE_REPLY"),
        }
    )

# --- 20 auto-resolve via data lookup (order status) ---
order_bodies = [
    "My order shipped last week but tracking hasn't updated. Where is my package?",
    "Ordered 10 days ago and the delivery date keeps moving. Can you check the shipment status?",
    "Can you tell me when my order will arrive? The tracking page shows nothing.",
    "I need an update on my order - has it shipped yet?",
    "The carrier says the package is in transit for a week. What is the actual delivery estimate?",
]
for i in range(20):
    tickets.append(
        {
            "subject": f"Status of order #{8800 + i}",
            "body": order_bodies[i % len(order_bodies)],
            "customer": customer(),
            "gold": gold("ORDER_STATUS", "MEDIUM", False, "AUTO_RESOLVE"),
        }
    )

# --- 25 clear generation-required (billing disputes, nuanced complaints, cancellations) ---
gen_cases = [
    ("Charged twice for March invoice", "My card shows two identical charges for the same March invoice. I want one refunded immediately and an explanation of how this happened.", "BILLING_DISPUTE", "HIGH"),
    ("Refund amount is wrong", "The refund you processed is $40 short of what was agreed with your agent last week. Please fix this.", "BILLING_DISPUTE", "HIGH"),
    ("Overcharged after downgrade", "I downgraded to the basic plan last month but was billed the premium price again. This is the second billing mistake this year.", "BILLING_DISPUTE", "HIGH"),
    ("Unexpected charge on my statement", "There is a charge from you on my statement that I do not recognize. I did not authorize this payment.", "BILLING_DISPUTE", "URGENT"),
    ("Want to cancel my subscription", "The product no longer fits our workflow and the last two support experiences were disappointing. Please cancel my subscription and confirm there are no further charges.", "CANCELLATION", "HIGH"),
]
for i in range(25):
    subj, body, cat, pri = gen_cases[i % len(gen_cases)]
    tickets.append(
        {
            "subject": subj,
            "body": body + f" Account ref {2000 + i}.",
            "customer": customer(),
            "gold": gold(cat, pri, True, "CUSTOM_REPLY"),
        }
    )

# --- 15 ambiguous / borderline ---
ambiguous = [
    ("Something's not right", "Things have not been working the way I expected lately and I am not sure what changed. Can someone look into my account?", "GENERAL_INQUIRY", "MEDIUM", False, "CUSTOM_REPLY"),
    ("Issue with my account", "There is an issue, maybe with billing or maybe the plan, honestly not sure. The numbers look off to me.", "BILLING_DISPUTE", "HIGH", True, "CUSTOM_REPLY"),
    ("Not happy", "This has been a frustrating month with your service and I am considering my options. What can you do for me?", "GENERAL_INQUIRY", "MEDIUM", False, "CUSTOM_REPLY"),
    ("Question about my last order and my plan", "The order took long and also I think my plan renewed at a different price? Can you clarify.", "ORDER_STATUS", "MEDIUM", False, "CUSTOM_REPLY"),
    ("App behaving oddly", "Sometimes it works, sometimes it doesn't. Hard to say when. Is that a known thing?", "BUG_REPORT", "MEDIUM", False, "CUSTOM_REPLY"),
]
for i in range(15):
    subj, body, cat, pri, esc, strat = ambiguous[i % len(ambiguous)]
    tickets.append(
        {
            "subject": subj,
            "body": body + f" (case {3000 + i})",
            "customer": customer(),
            "gold": gold(cat, pri, esc, strat),
        }
    )

# --- 10 complex multi-issue (gold = dominant intent) ---
multi = [
    ("Double charge AND can't log in", "First, I was charged twice this month which needs fixing right away. Second, my password reset emails are not arriving so I cannot even check my invoices.", "BILLING_DISPUTE", "URGENT"),
    ("Order late and app crashes", "My order is a week late with no tracking update, and on top of that the mobile app crashes whenever I open the orders tab.", "ORDER_STATUS", "HIGH"),
    ("Cancel unless the bug is fixed", "The export feature has been broken for two weeks. If this is not fixed by Friday I want to cancel my subscription entirely.", "CANCELLATION", "HIGH"),
    ("Billing question plus feature request", "I think last month's invoice is wrong - the total doesn't match my plan. Also, any chance you could add SSO support?", "BILLING_DISPUTE", "HIGH"),
    ("Broken dashboard and locked account", "The analytics dashboard shows an error 500 since Monday and now my account got locked after the update. I need both fixed.", "BUG_REPORT", "HIGH"),
]
for i in range(10):
    subj, body, cat, pri = multi[i % len(multi)]
    tickets.append(
        {
            "subject": subj,
            "body": body + f" Ticket context {4000 + i}.",
            "customer": customer(),
            "gold": gold(cat, pri, True, "CUSTOM_REPLY"),
        }
    )

# assign ids in order
records = []
for n, t in enumerate(tickets, 1):
    records.append({"id": f"T-{n:03d}", **t})

OUT.parent.mkdir(parents=True, exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# Orders fixture: every ORDER_STATUS ticket gets a deterministic order record
orders = {}
for r in records:
    if r["gold"]["category"] == "ORDER_STATUS" and r["gold"]["strategy"] == "AUTO_RESOLVE":
        num = int(r["id"].split("-")[1])
        orders[r["id"]] = {
            "order_id": f"ORD-{8800 + num}",
            "status": rng.choice(["IN_TRANSIT", "OUT_FOR_DELIVERY", "PROCESSING"]),
            "carrier": rng.choice(["FastShip", "BlueDart Express", "GlobalPost"]),
            "eta": f"2026-10-{rng.randint(16, 28):02d}",
        }
ORDERS_OUT.write_text(json.dumps(orders, indent=2), encoding="utf-8")

print(f"wrote {len(records)} tickets -> {OUT}")
print(f"wrote {len(orders)} orders -> {ORDERS_OUT}")
from collections import Counter

print("strategy mix:", dict(Counter(r["gold"]["strategy"] for r in records)))
print("category mix:", dict(Counter(r["gold"]["category"] for r in records)))
