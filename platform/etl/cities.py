"""City name canonicalisation.

Platforms disagree about names as well as case. Zepto writes "Bengaluru", Instamart
writes "Bangalore"; both appear in the top five as if they were different cities,
splitting one city's revenue in two. Renamed Indian cities are mapped to their
current official name so each place is counted once.
"""

# old / alternate spelling -> current official name
ALIASES = {
    "bangalore": "Bengaluru",
    "mysore": "Mysuru",
    "hubli": "Hubballi",
    "belgaum": "Belgavi",
    "pondicherry": "Puducherry",
    "tumkuru": "Tumakuru",
    "tumkur": "Tumakuru",
    "trichy": "Tiruchirappalli",
    "trichirappalli": "Tiruchirappalli",
    "vizag": "Visakhapatnam",
    "calicut": "Kozhikode",
    "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram",
    "mangalore": "Mangaluru",
    "shimoga": "Shivamogga",
    "gurugram": "Gurgaon",
    "bombay": "Mumbai",
    "madras": "Chennai",
    "calcutta": "Kolkata",
    "poona": "Pune",
    "baroda": "Vadodara",
    "allahabad": "Prayagraj",
    "noida 1": "Noida",
    "new delhi": "Delhi",
}


def canonical(name) -> str | None:
    """Title-case and de-alias a city name. Returns None for blanks."""
    if name is None:
        return None
    text = " ".join(str(name).strip().split())
    if not text:
        return None
    return ALIASES.get(text.lower(), text.title())
