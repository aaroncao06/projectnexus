"""
Fake email chains for testing the relationship-extraction agent.
Use with: python main.py ingest-fake
"""

# Chain 1: Small thread — 3 people, delegation and coordination
FAKE_CHAIN_SMALL = """\
From: alice@example.com
To: bob@example.com, carol@example.com
Subject: Project kickoff

Hi Bob and Carol,

I'd like to kick off the new analytics dashboard project. Bob, could you \
take the lead on the backend API design? Carol, please handle the frontend \
wireframes and coordinate with Bob on the data contract.

Let's aim to have initial designs by Friday.

Thanks,
Alice

---

From: bob@example.com
To: alice@example.com, carol@example.com
Subject: Re: Project kickoff

Alice,

Sounds good — I'll draft the API spec by Wednesday so Carol has time to \
align the frontend. Carol, let's sync tomorrow to agree on the payload \
format.

Bob

---

From: carol@example.com
To: bob@example.com
Cc: alice@example.com
Subject: Re: Re: Project kickoff

Bob,

Works for me. I have some concerns about the pagination approach from last \
quarter — let's make sure we don't repeat that. I'll prepare a short \
comparison doc before our sync.

Carol
"""

# Chain 2: One-to-many — one sender to several recipients (tests batch + recipient–recipient)
FAKE_CHAIN_GROUP = """\
From: shirley.crenshaw@enron.com
To: vince.kaminski@enron.com, stinson.gibner@enron.com, pinnamaneni.krishnarao@enron.com, vasant.shanbhogue@enron.com, mike.roberts@enron.com
Subject: Telerate Service

Hello everyone,

Please let me know if you have a subscription to "Telerate"? We are being \
billed for this service and I do not know who is using it.

Thanks!
Shirley
"""

# Chain 3: Short back-and-forth with disagreement
FAKE_CHAIN_DISAGREEMENT = """\
From: jane@acme.com
To: john@acme.com
Subject: Q4 timeline

John — I think we should ship by Dec 1. Marketing is counting on it.

Jane

---

From: john@acme.com
To: jane@acme.com
Subject: Re: Q4 timeline

Jane — Dec 1 is too aggressive. Engineering needs until Dec 15. We disagreed \
on this last quarter too; I’d rather slip than cut scope again.

John
"""

FAKE_CHAINS = [
    ("small (3 people)", FAKE_CHAIN_SMALL),
    ("group (1 sender, 5 recipients)", FAKE_CHAIN_GROUP),
    ("disagreement (2 people)", FAKE_CHAIN_DISAGREEMENT),
]
