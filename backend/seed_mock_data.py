"""
Seed the Neo4j database with mock data modelling a criminal fraud network.

The data represents intercepted email communications between suspects
involved in various fraud schemes: securities fraud, money laundering,
identity theft, wire fraud, and insider trading.

Usage:
    cd backend
    python seed_mock_data.py
"""

import sys
sys.path.insert(0, ".")

from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

# ── Suspects ────────────────────────────────────────────────────────────────
PEOPLE = [
    # Ring leaders / Securities fraud orchestrators
    ("victor.marquez@vantacap.com", "Victor Marquez"),
    ("elena.ross@vantacap.com", "Elena Ross"),
    ("dean.hargrove@vantacap.com", "Dean Hargrove"),

    # Money laundering operators
    ("nina.okafor@shellbridge.net", "Nina Okafor"),
    ("raymond.tse@shellbridge.net", "Raymond Tse"),
    ("luis.pena@shellbridge.net", "Luis Pena"),
    ("carmen.west@tridentholdings.com", "Carmen West"),

    # Identity theft / Synthetic identity ring
    ("jason.blank@protonbox.io", "Jason Blank"),
    ("sarah.cole@protonbox.io", "Sarah Cole"),
    ("derek.mills@protonbox.io", "Derek Mills"),
    ("tanya.novak@protonbox.io", "Tanya Novak"),

    # Wire fraud / Phishing operations
    ("marcus.lee@darkpulse.org", "Marcus Lee"),
    ("priya.anand@darkpulse.org", "Priya Anand"),
    ("kevin.rhodes@darkpulse.org", "Kevin Rhodes"),
    ("ashley.tran@darkpulse.org", "Ashley Tran"),
    ("omar.farid@darkpulse.org", "Omar Farid"),

    # Insider trading network
    ("helen.price@meridianfunds.com", "Helen Price"),
    ("david.kwan@meridianfunds.com", "David Kwan"),
    ("rachel.dunn@biotekrx.com", "Rachel Dunn"),
    ("samuel.gordon@biotekrx.com", "Samuel Gordon"),

    # Corrupt officials / Facilitators
    ("frank.bishop@stategov.org", "Frank Bishop"),
    ("diane.castro@cityfinance.gov", "Diane Castro"),

    # Lawyers / Professional enablers
    ("gerald.hyde@hydelaw.com", "Gerald Hyde"),
    ("megan.cross@hydelaw.com", "Megan Cross"),
]

# ── Intercepted communications ──────────────────────────────────────────────
# (source_email, target_email, email_count, summary)
RELATIONSHIPS = [
    # Securities fraud core
    ("victor.marquez@vantacap.com", "elena.ross@vantacap.com", 189,
     "Marquez and Ross coordinate pump-and-dump schemes on penny stocks; discuss timing of press releases and coordinated buy orders."),
    ("victor.marquez@vantacap.com", "dean.hargrove@vantacap.com", 134,
     "Hargrove provides Marquez with forged analyst reports and fabricated revenue projections to inflate stock prices."),
    ("elena.ross@vantacap.com", "dean.hargrove@vantacap.com", 97,
     "Ross and Hargrove discuss creation of fake brokerage accounts to layer fraudulent trades."),
    ("victor.marquez@vantacap.com", "gerald.hyde@hydelaw.com", 76,
     "Marquez consults Hyde on legal structuring of offshore shell companies to hide fraud proceeds."),

    # Securities fraud ↔ Money laundering bridge
    ("victor.marquez@vantacap.com", "nina.okafor@shellbridge.net", 112,
     "Marquez instructs Okafor to move fraud proceeds through layered shell company accounts across three jurisdictions."),
    ("elena.ross@vantacap.com", "raymond.tse@shellbridge.net", 68,
     "Ross sends Tse wire transfer instructions for laundering stock sale profits through Asian intermediaries."),

    # Money laundering core
    ("nina.okafor@shellbridge.net", "raymond.tse@shellbridge.net", 156,
     "Okafor and Tse coordinate rapid movement of funds through shell companies; discuss structuring deposits below reporting thresholds."),
    ("nina.okafor@shellbridge.net", "luis.pena@shellbridge.net", 121,
     "Pena manages cryptocurrency conversion of laundered funds under Okafor's direction; discusses mixing services."),
    ("raymond.tse@shellbridge.net", "luis.pena@shellbridge.net", 88,
     "Tse and Pena coordinate on smurfing cash deposits across multiple bank branches."),
    ("nina.okafor@shellbridge.net", "carmen.west@tridentholdings.com", 93,
     "West operates front businesses for Okafor; invoices for fictitious consulting services to justify fund transfers."),
    ("carmen.west@tridentholdings.com", "luis.pena@shellbridge.net", 47,
     "West and Pena discuss real estate purchases using laundered funds through anonymous LLCs."),

    # Money laundering ↔ Corrupt officials
    ("nina.okafor@shellbridge.net", "diane.castro@cityfinance.gov", 41,
     "Okafor bribes Castro for advance notice of financial audits; Castro delays suspicious activity reports."),
    ("raymond.tse@shellbridge.net", "frank.bishop@stategov.org", 37,
     "Bishop provides Tse with insider knowledge of upcoming regulatory actions in exchange for payments."),

    # Identity theft core
    ("jason.blank@protonbox.io", "sarah.cole@protonbox.io", 143,
     "Blank and Cole build synthetic identities using stolen SSNs and fabricated credit histories for loan fraud."),
    ("jason.blank@protonbox.io", "derek.mills@protonbox.io", 118,
     "Mills provides Blank with bulk stolen personal data harvested from data breaches; discuss pricing per record."),
    ("jason.blank@protonbox.io", "tanya.novak@protonbox.io", 95,
     "Novak creates counterfeit IDs and supporting documents for Blank's synthetic identity operation."),
    ("sarah.cole@protonbox.io", "derek.mills@protonbox.io", 82,
     "Cole and Mills coordinate on targeting victims through social engineering and phishing for personal data."),
    ("sarah.cole@protonbox.io", "tanya.novak@protonbox.io", 67,
     "Novak and Cole discuss document quality and techniques to pass bank KYC verification."),
    ("derek.mills@protonbox.io", "tanya.novak@protonbox.io", 54,
     "Mills and Novak exchange stolen data batches and coordinate on dark web marketplace listings."),

    # Identity theft ↔ Wire fraud bridge
    ("jason.blank@protonbox.io", "marcus.lee@darkpulse.org", 73,
     "Blank sells synthetic identities to Lee's wire fraud operation for use in business email compromise attacks."),
    ("derek.mills@protonbox.io", "priya.anand@darkpulse.org", 49,
     "Mills provides Anand with compromised email credentials harvested from phishing campaigns."),

    # Wire fraud / Phishing core
    ("marcus.lee@darkpulse.org", "priya.anand@darkpulse.org", 167,
     "Lee and Anand orchestrate business email compromise campaigns targeting corporate CFOs; discuss social engineering scripts."),
    ("marcus.lee@darkpulse.org", "kevin.rhodes@darkpulse.org", 132,
     "Rhodes builds phishing infrastructure (domains, landing pages) for Lee's fraud campaigns."),
    ("marcus.lee@darkpulse.org", "ashley.tran@darkpulse.org", 98,
     "Tran manages mule accounts that receive wire fraud proceeds under Lee's direction."),
    ("marcus.lee@darkpulse.org", "omar.farid@darkpulse.org", 81,
     "Farid provides Lee with technical exploit kits and email spoofing tools."),
    ("priya.anand@darkpulse.org", "kevin.rhodes@darkpulse.org", 109,
     "Anand and Rhodes coordinate on crafting convincing phishing emails impersonating executives."),
    ("priya.anand@darkpulse.org", "ashley.tran@darkpulse.org", 63,
     "Tran reports successful wire transfers to Anand; discuss extraction timing."),
    ("kevin.rhodes@darkpulse.org", "omar.farid@darkpulse.org", 77,
     "Rhodes and Farid share zero-day exploits and discuss malware deployment for credential harvesting."),
    ("ashley.tran@darkpulse.org", "omar.farid@darkpulse.org", 45,
     "Farid and Tran discuss VPN and anonymization techniques to avoid law enforcement tracing."),

    # Wire fraud ↔ Money laundering bridge
    ("ashley.tran@darkpulse.org", "carmen.west@tridentholdings.com", 52,
     "Tran routes wire fraud proceeds to West's front companies for laundering through fake invoices."),
    ("marcus.lee@darkpulse.org", "luis.pena@shellbridge.net", 38,
     "Lee uses Pena's cryptocurrency mixing services to launder BEC fraud proceeds."),

    # Insider trading core
    ("helen.price@meridianfunds.com", "david.kwan@meridianfunds.com", 128,
     "Price and Kwan share non-public merger and acquisition information; coordinate trades through offshore accounts."),
    ("helen.price@meridianfunds.com", "rachel.dunn@biotekrx.com", 94,
     "Dunn leaks upcoming FDA drug approval results to Price before public announcement."),
    ("david.kwan@meridianfunds.com", "samuel.gordon@biotekrx.com", 71,
     "Gordon provides Kwan with insider clinical trial data; Kwan trades on material non-public information."),
    ("rachel.dunn@biotekrx.com", "samuel.gordon@biotekrx.com", 86,
     "Dunn and Gordon coordinate which information to leak and discuss their cut of trading profits."),
    ("helen.price@meridianfunds.com", "samuel.gordon@biotekrx.com", 43,
     "Price contacts Gordon directly for time-sensitive pre-announcement intel on biotech approvals."),

    # Insider trading ↔ Securities fraud bridge
    ("helen.price@meridianfunds.com", "elena.ross@vantacap.com", 56,
     "Price tips Ross on upcoming M&A targets; Ross front-runs trades through Vanta Capital accounts."),
    ("david.kwan@meridianfunds.com", "victor.marquez@vantacap.com", 39,
     "Kwan provides Marquez with non-public earnings data to enhance pump-and-dump timing."),

    # Lawyers / Enablers
    ("gerald.hyde@hydelaw.com", "megan.cross@hydelaw.com", 145,
     "Hyde and Cross coordinate legal strategies to shield clients from fraud investigations; discuss privilege claims."),
    ("gerald.hyde@hydelaw.com", "nina.okafor@shellbridge.net", 62,
     "Hyde advises Okafor on structuring shell companies to obscure beneficial ownership."),
    ("megan.cross@hydelaw.com", "carmen.west@tridentholdings.com", 48,
     "Cross drafts fictitious contracts for West's front businesses to create paper trails for laundered funds."),
    ("gerald.hyde@hydelaw.com", "helen.price@meridianfunds.com", 33,
     "Hyde provides Price with legal cover stories for suspicious trading patterns."),

    # Corrupt officials cross-links
    ("frank.bishop@stategov.org", "diane.castro@cityfinance.gov", 29,
     "Bishop and Castro coordinate to suppress fraud investigations and delay regulatory referrals."),
    ("frank.bishop@stategov.org", "gerald.hyde@hydelaw.com", 35,
     "Bishop tips Hyde off about upcoming law enforcement operations targeting Hyde's clients."),
    ("diane.castro@cityfinance.gov", "carmen.west@tridentholdings.com", 31,
     "Castro approves fraudulent business permits for West's front companies in exchange for kickbacks."),
]


def seed():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    with driver.session() as session:
        # Wipe existing data
        session.run("MATCH (n) DETACH DELETE n")
        print("Cleared existing data.")

        # Create uniqueness constraint
        session.run(
            "CREATE CONSTRAINT IF NOT EXISTS "
            "FOR (p:Person) REQUIRE p.email IS UNIQUE"
        )

        # Create all Person nodes
        for email, name in PEOPLE:
            session.run(
                "MERGE (p:Person {email: $email}) SET p.name = $name",
                email=email, name=name,
            )
        print(f"Created {len(PEOPLE)} suspect nodes.")

        # Create all relationships
        for src, tgt, count, summary in RELATIONSHIPS:
            session.run(
                "MATCH (a:Person {email: $src}), (b:Person {email: $tgt}) "
                "MERGE (a)-[r:COMMUNICATES_WITH]-(b) "
                "SET r.email_count = $count, r.summary = $summary, "
                "    r.comments = [$summary]",
                src=src, tgt=tgt, count=count, summary=summary,
            )
        print(f"Created {len(RELATIONSHIPS)} intercepted communications.")

    driver.close()
    print("\nDone! Criminal fraud network seeded successfully.")


if __name__ == "__main__":
    seed()
