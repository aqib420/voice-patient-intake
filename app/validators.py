"""Field validators shared by the REST schemas and the voice agent's
validate_field tool, so the rules live in exactly one place.

Each function takes raw input, returns the normalised value, or raises
ValueError with a message short and plain enough to be read to a caller.
"""
import re
from datetime import date, datetime

from email_validator import EmailNotValidError, validate_email

from app.models import Sex

_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-][^\W\d_]+)*$")
_MEMBER_ID_RE = re.compile(r"^[A-Z0-9]{1,30}$")

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "U.S. Virgin Islands",
    "AS": "American Samoa", "MP": "Northern Mariana Islands",
}
_STATE_BY_NAME = {v.lower(): k for k, v in US_STATES.items()}

_SEX_ALIASES = {
    "male": Sex.MALE, "m": Sex.MALE, "man": Sex.MALE,
    "female": Sex.FEMALE, "f": Sex.FEMALE, "woman": Sex.FEMALE,
    "other": Sex.OTHER,
    "decline to answer": Sex.DECLINE, "decline": Sex.DECLINE,
    "prefer not to say": Sex.DECLINE, "prefer not to answer": Sex.DECLINE,
}


def blank_to_none(v):
    if isinstance(v, str) and not v.strip():
        return None
    return v


def name(v: str, label: str = "Name", max_len: int = 50) -> str:
    v = " ".join(str(v).replace("’", "'").split())  # curly apostrophe, extra spaces
    if not v:
        raise ValueError(f"{label} is required.")
    if len(v) > max_len:
        raise ValueError(f"{label} must be {max_len} characters or fewer.")
    if not _NAME_RE.match(v):
        raise ValueError(f"{label} can only contain letters, spaces, hyphens and apostrophes.")
    return v


def date_of_birth(v) -> date:
    if isinstance(v, datetime):
        d = v.date()
    elif isinstance(v, date):
        d = v
    else:
        s = str(v).strip()
        d = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
        if d is None:
            raise ValueError("Date of birth must be a real date in MM/DD/YYYY format.")
    if d > date.today():
        raise ValueError("Date of birth can't be in the future.")
    if d.year < 1900:
        raise ValueError("Date of birth must be after 1900.")
    return d


def sex(v) -> Sex:
    if isinstance(v, Sex):
        return v
    key = " ".join(str(v).strip().lower().split())
    if key in _SEX_ALIASES:
        return _SEX_ALIASES[key]
    raise ValueError("Sex must be Male, Female, Other, or Decline to Answer.")


def phone(v, label: str = "Phone number") -> str:
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(f"{label} must be a 10-digit U.S. number; I got {len(digits)} digits.")
    if digits[0] in "01":
        raise ValueError(f"{label} has an invalid area code; U.S. area codes can't start with 0 or 1.")
    return digits


def email(v: str) -> str:
    try:
        return validate_email(str(v).strip(), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ValueError("That doesn't look like a valid email address.") from None


def state(v: str) -> str:
    s = " ".join(str(v).strip().split())
    if s.upper() in US_STATES:
        return s.upper()
    code = _STATE_BY_NAME.get(s.lower())
    if code:
        return code
    raise ValueError("State must be a valid U.S. state, like TX or California.")


def zip_code(v) -> str:
    s = str(v).strip()
    digits = re.sub(r"\D", "", s)
    if re.fullmatch(r"\d{5}", s) or re.fullmatch(r"\d{5}-\d{4}", s):
        return s
    if len(digits) == 9 and re.fullmatch(r"[\d\s-]+", s):
        return f"{digits[:5]}-{digits[5:]}"
    raise ValueError("ZIP code must be 5 digits, or ZIP+4 like 12345-6789.")


def text(v, label: str, max_len: int, min_len: int = 1) -> str:
    s = " ".join(str(v).split())
    if len(s) < min_len:
        raise ValueError(f"{label} is required.")
    if len(s) > max_len:
        raise ValueError(f"{label} must be {max_len} characters or fewer.")
    return s


def member_id(v) -> str:
    s = re.sub(r"[\s-]", "", str(v)).upper()
    if not _MEMBER_ID_RE.match(s):
        raise ValueError("Insurance member ID must be letters and numbers only, up to 30 characters.")
    return s


# Used by the voice agent's validate_field tool. Maps field name -> validator.
FIELD_VALIDATORS = {
    "first_name": lambda v: name(v, "First name"),
    "last_name": lambda v: name(v, "Last name"),
    "date_of_birth": date_of_birth,
    "sex": sex,
    "phone_number": phone,
    "email": email,
    "address_line_1": lambda v: text(v, "Street address", 200),
    "address_line_2": lambda v: text(v, "Address line 2", 100),
    "city": lambda v: text(v, "City", 100),
    "state": state,
    "zip_code": zip_code,
    "insurance_provider": lambda v: text(v, "Insurance provider", 100),
    "insurance_member_id": member_id,
    "preferred_language": lambda v: text(v, "Preferred language", 50),
    "emergency_contact_name": lambda v: name(v, "Emergency contact name", 100),
    "emergency_contact_phone": lambda v: phone(v, "Emergency contact phone"),
}
