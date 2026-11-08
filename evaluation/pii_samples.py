"""Synthetic PII samples (invented values, not real people) for testing the privacy filter.
Each sample lists the exact strings that must NOT survive redaction."""

SAMPLES = [
    ("Email jane.doe@example.com about the budget", ["jane.doe@example.com"], "email"),
    ("Call 919-555-0142 after 5pm", ["919-555-0142"], "phone"),
    ("SSN 123-45-6789 is on the form", ["123-45-6789"], "ssn"),
    ("Card 4111 1111 1111 1111 expires soon", ["4111 1111 1111 1111"], "card"),
    ("Mail it to 512 N Salisbury Street in Raleigh", ["512 N Salisbury Street"], "address"),
    ("Contact Maria Lopez for details", ["Maria Lopez"], "name"),
    ("Dr. Alan Smith will review the narrative", ["Alan Smith"], "name"),
    ("Reach the office at (984) 555-0199", ["(984) 555-0199", "555-0199"], "phone"),
    ("my personal address is bob_smith99@gmail.com", ["bob_smith99@gmail.com"], "email"),
    ("Kim Nguyen will draft the narrative", ["Kim Nguyen"], "name without a title"),
]

INTERNAL_SAMPLES = [
    ("This is a draft budget, internal only", True),
    ("We face a shortfall of $2.3 million next year", True),
    ("Looking for water quality monitoring grants for coastal counties", False),
]

# place and program names that look like people's names and must be left alone
PLACES_NOT_NAMES = [
    "Funding for Jordan Lake water quality monitoring",
    "Charlotte Mecklenburg schools need STEM teachers",
    "Ryan White HIV/AIDS Program funding",
    "Paul Coverdell Forensic Science grants",
    "Virginia Beach coastal resilience",
]
