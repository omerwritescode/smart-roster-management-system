"""Fictional sample data: 34 employees, 4 pods, 25 brands, demo month December 2026.

Brand and employee names are invented. Staffing follows the brief: 20 of 25 brands
(80%) have one dedicated employee, and 5 have two or three.

Problems built in on purpose, so the demo shows real conflicts:
- Tara Toys CS runs 7 days with one employee and no backup, so her weekly off is a gap.
- Rhea holds Jute Junction RET on Saturdays in the Late shift, which overlaps her
  General shift work at Zest Gully and Jute Junction.
- Harsh holds two brands with no backup and has leave on 14-15 December.
- Anika and both Saffron Thread CS backups are away on 22 December.
- Monsoon Mugs needs 2 people on 31 December and one of its two is on leave.
"""
from __future__ import annotations

from datetime import date

G, E, L = "shift-general", "shift-early", "shift-late"
CS, ACC, NDR, RET, RNR = "proc-cs", "proc-acc", "proc-ndr", "proc-ret", "proc-rnr"
ALL, DAILY, SHOFF, CUSTOM = "all_days", "daily_except_holidays", "sundays_holidays_off", "custom"

SHIFTS = [
    (G, "General", "10:00", "19:00"),
    (E, "Early", "07:00", "16:00"),
    (L, "Late", "13:00", "22:00"),
]
PROCESSES = [
    (CS, "CS", "Customer Support"),
    (ACC, "ACC", "Abandoned Cart Conversions"),
    (NDR, "NDR", "Non-Delivery Report Management"),
    (RET, "RET", "Retention"),
    (RNR, "RNR", "Returns and Refunds"),
]
# Christmas verified against the 2026 CDSL holiday list and publicholidays.in (Maharashtra).
HOLIDAYS = [
    (date(2026, 11, 24), "Guru Nanak Jayanti", "public"),
    (date(2026, 12, 4), "Founders' Day", "company"),
    (date(2026, 12, 25), "Christmas Day", "public"),
    (date(2027, 1, 26), "Republic Day", "public"),
]
PODS = [
    ("pod-aurora", "Aurora", "emp-meera"),
    ("pod-banyan", "Banyan", "emp-rohan"),
    ("pod-cedar", "Cedar", "emp-farah"),
    ("pod-delta", "Delta", "emp-vikram"),
]

# id, name, pod, title, policy, fixed weekdays, rotation weekdays
_S = ("solver", (), ())
EMPLOYEES = [
    ("emp-meera", "Meera Nair", "pod-aurora", "Pod Lead", *_S),
    ("emp-priya", "Priya Menon", "pod-aurora", "Senior Associate", *_S),
    ("emp-karan", "Karan Bhatia", "pod-aurora", "Associate", *_S),
    ("emp-sana", "Sana Kulkarni", "pod-aurora", "Associate", "fixed", (6,), ()),
    ("emp-anika", "Anika Rao", "pod-aurora", "Senior Associate", "rotating", (), (1, 3, 5, 0)),
    ("emp-dev", "Dev Malhotra", "pod-aurora", "Associate", *_S),
    ("emp-ishaan", "Ishaan Joshi", "pod-aurora", "Associate", *_S),
    ("emp-neha", "Neha Pillai", "pod-aurora", "Associate", "fixed", (5,), ()),
    ("emp-arjun", "Arjun Sethi", "pod-aurora", "Associate", "fixed", (0,), ()),
    ("emp-rohan", "Rohan Deshmukh", "pod-banyan", "Pod Lead", *_S),
    ("emp-tanvi", "Tanvi Shah", "pod-banyan", "Senior Associate", *_S),
    ("emp-yash", "Yash Agarwal", "pod-banyan", "Associate", *_S),
    ("emp-rhea", "Rhea D'Souza", "pod-banyan", "Associate", *_S),
    ("emp-aditya", "Aditya Verma", "pod-banyan", "Associate", *_S),
    ("emp-zoya", "Zoya Khan", "pod-banyan", "Associate", "fixed", (2,), ()),
    ("emp-kabir", "Kabir Mehta", "pod-banyan", "Senior Associate", "fixed", (1,), ()),
    ("emp-riya", "Riya Chawla", "pod-banyan", "Associate", *_S),
    ("emp-om", "Om Gokhale", "pod-banyan", "Associate", *_S),
    ("emp-farah", "Farah Siddiqui", "pod-cedar", "Pod Lead", *_S),
    ("emp-aanya", "Aanya Reddy", "pod-cedar", "Senior Associate", *_S),
    ("emp-imran", "Imran Sayed", "pod-cedar", "Associate", *_S),
    ("emp-divya", "Divya Hegde", "pod-cedar", "Associate", *_S),
    ("emp-harsh", "Harsh Patil", "pod-cedar", "Senior Associate", *_S),
    ("emp-leela", "Leela Thomas", "pod-cedar", "Associate", *_S),
    ("emp-gauri", "Gauri Kamat", "pod-cedar", "Associate", "rotating", (), (2, 4, 0, 3)),
    ("emp-manav", "Manav Saxena", "pod-cedar", "Associate", *_S),
    ("emp-vikram", "Vikram Iyer", "pod-delta", "Pod Lead", *_S),
    ("emp-pooja", "Pooja Gupta", "pod-delta", "Associate", *_S),
    ("emp-sameer", "Sameer Kapoor", "pod-delta", "Associate", *_S),
    ("emp-nikhil", "Nikhil Bose", "pod-delta", "Associate", "fixed", (6,), ()),
    ("emp-swati", "Swati Jain", "pod-delta", "Senior Associate", *_S),
    ("emp-rahul", "Rahul Pawar", "pod-delta", "Associate", *_S),
    ("emp-ayesha", "Ayesha Qureshi", "pod-delta", "Associate", *_S),
    ("emp-tushar", "Tushar Naik", "pod-delta", "Associate", *_S),
]

# brand id, name, pod, [(process, calendar, shift, min staff, weekday mask)]
BRANDS = [
    ("nimbu", "Nimbu Naturals", "pod-aurora", [(CS, ALL, G), (ACC, SHOFF, G), (NDR, DAILY, G)]),
    ("haldi", "Haldi House", "pod-aurora", [(CS, DAILY, G), (RET, SHOFF, G)]),
    ("lotus", "Little Lotus", "pod-aurora", [(CS, SHOFF, G), (NDR, SHOFF, G)]),
    ("saffron", "Saffron Thread", "pod-aurora", [(CS, ALL, G), (ACC, DAILY, G), (NDR, SHOFF, G)]),
    ("kora", "Kora Cotton", "pod-aurora", [(CS, ALL, G), (ACC, SHOFF, G), (RET, CUSTOM, G, (0, 1, 2, 3, 4))]),
    ("copper", "Copper Crate", "pod-banyan", [(CS, ALL, E), (ACC, SHOFF, E)]),
    ("ritu", "Ritu Botanics", "pod-banyan", [(CS, ALL, G), (NDR, DAILY, G)]),
    ("zest", "Zest Gully", "pod-banyan", [(CS, SHOFF, G)]),
    ("jute", "Jute Junction", "pod-banyan", [(CS, SHOFF, G), (RET, CUSTOM, L, (5,))]),
    ("peepal", "Peepal Paper", "pod-banyan", [(CS, DAILY, G)]),
    ("vayu", "Vayu Wear", "pod-banyan", [(CS, ALL, L), (RNR, SHOFF, L)]),
    ("ember", "Ember Candles", "pod-banyan", [(CS, ALL, G), (ACC, DAILY, L), (NDR, SHOFF, G), (RET, SHOFF, G)]),
    ("pebble", "Pebble Pets", "pod-cedar", [(CS, ALL, G), (NDR, DAILY, G)]),
    ("tiffin", "Tiffin Tales", "pod-cedar", [(CS, ALL, G), (ACC, ALL, G)]),
    ("rangoli", "Rangoli Rugs", "pod-cedar", [(CS, SHOFF, G)]),
    ("sattva", "Sattva Snacks", "pod-cedar", [(CS, SHOFF, G)]),
    ("kulfi", "Kulfi Club", "pod-cedar", [(CS, SHOFF, G)]),
    ("amrit", "Amrit Oils", "pod-cedar", [(CS, ALL, G), (RET, SHOFF, G)]),
    ("bamboo", "Bamboo Bay", "pod-cedar", [(CS, ALL, G), (NDR, SHOFF, G)]),
    ("tara", "Tara Toys", "pod-delta", [(CS, ALL, G)]),
    ("dhaga", "Dhaga Denim", "pod-delta", [(CS, DAILY, G), (ACC, SHOFF, G)]),
    ("ananda", "Ananda Ayurveda", "pod-delta", [(CS, SHOFF, G), (NDR, SHOFF, G)]),
    ("loom", "Loomkart", "pod-delta", [(CS, ALL, G), (RNR, CUSTOM, G, (0, 2, 4))]),
    ("chai", "Chai Theory", "pod-delta", [(CS, ALL, L)]),
    ("monsoon", "Monsoon Mugs", "pod-delta", [(CS, ALL, G)]),
]
# Zest Gully and Jute Junction share one holder, as do Sattva Snacks and Kulfi Club.


def bp_id(brand: str, process: str) -> str:
    return f"{brand}-{process.removeprefix('proc-')}"


# employee, brand, process, share (regular work)
_REGULAR = [
    # Aurora: single-employee brands
    ("emp-priya", "nimbu", CS, 50), ("emp-priya", "nimbu", ACC, 30), ("emp-priya", "nimbu", NDR, 20),
    ("emp-karan", "haldi", CS, 60), ("emp-karan", "haldi", RET, 40),
    ("emp-sana", "lotus", CS, 70), ("emp-sana", "lotus", NDR, 30),
    # Aurora: three employees on three separate processes
    ("emp-anika", "saffron", CS, 100), ("emp-dev", "saffron", ACC, 100), ("emp-ishaan", "saffron", NDR, 100),
    # Aurora: two employees sharing CS, each with a process of their own
    ("emp-neha", "kora", CS, 70), ("emp-neha", "kora", ACC, 30),
    ("emp-arjun", "kora", CS, 70), ("emp-arjun", "kora", RET, 30),
    # Banyan: single-employee brands
    ("emp-tanvi", "copper", CS, 60), ("emp-tanvi", "copper", ACC, 40),
    ("emp-yash", "ritu", CS, 50), ("emp-yash", "ritu", NDR, 50),
    ("emp-rhea", "zest", CS, 50), ("emp-rhea", "jute", CS, 30), ("emp-rhea", "jute", RET, 20),
    ("emp-aditya", "peepal", CS, 100),
    ("emp-zoya", "vayu", CS, 60), ("emp-zoya", "vayu", RNR, 40),
    # Banyan: three employees, two sharing CS
    ("emp-kabir", "ember", CS, 70), ("emp-kabir", "ember", RET, 30),
    ("emp-riya", "ember", CS, 70), ("emp-riya", "ember", NDR, 30),
    ("emp-om", "ember", ACC, 100),
    # Cedar: single-employee brands
    ("emp-aanya", "pebble", CS, 70), ("emp-aanya", "pebble", NDR, 30),
    ("emp-imran", "tiffin", CS, 60), ("emp-imran", "tiffin", ACC, 40),
    ("emp-divya", "rangoli", CS, 100),
    ("emp-harsh", "sattva", CS, 50), ("emp-harsh", "kulfi", CS, 50),
    ("emp-leela", "amrit", CS, 60), ("emp-leela", "amrit", RET, 40),
    # Cedar: two employees on separate processes
    ("emp-gauri", "bamboo", CS, 100), ("emp-manav", "bamboo", NDR, 100),
    # Delta: single-employee brands
    ("emp-pooja", "tara", CS, 100),
    ("emp-sameer", "dhaga", CS, 60), ("emp-sameer", "dhaga", ACC, 40),
    ("emp-nikhil", "ananda", CS, 60), ("emp-nikhil", "ananda", NDR, 40),
    ("emp-swati", "loom", CS, 70), ("emp-swati", "loom", RNR, 30),
    ("emp-rahul", "chai", CS, 100),
    # Delta: two employees sharing CS
    ("emp-ayesha", "monsoon", CS, 100), ("emp-tushar", "monsoon", CS, 100),
]

# Backups: pod leads cover their own pod; peers on the same shift help where possible.
# employee, brand, process, share. Tara Toys has none on purpose.
_BACKUP = [
    ("emp-meera", "nimbu", CS, 40), ("emp-meera", "nimbu", NDR, 20), ("emp-meera", "haldi", CS, 40),
    ("emp-meera", "saffron", CS, 40), ("emp-meera", "saffron", ACC, 30), ("emp-meera", "kora", CS, 40),
    ("emp-sana", "nimbu", CS, 25), ("emp-sana", "haldi", CS, 25),
    ("emp-ishaan", "saffron", CS, 25), ("emp-ishaan", "saffron", ACC, 25), ("emp-dev", "saffron", NDR, 25),
    ("emp-karan", "nimbu", NDR, 20), ("emp-karan", "nimbu", CS, 25),
    ("emp-arjun", "kora", ACC, 30), ("emp-neha", "kora", RET, 30),
    ("emp-riya", "ember", RET, 30), ("emp-kabir", "ember", NDR, 30), ("emp-om", "vayu", RNR, 25),
    ("emp-rohan", "copper", CS, 40), ("emp-rohan", "ritu", CS, 40), ("emp-rohan", "ritu", NDR, 25),
    ("emp-rohan", "vayu", CS, 40), ("emp-rohan", "peepal", CS, 40), ("emp-rohan", "ember", CS, 40),
    ("emp-aditya", "ritu", CS, 25), ("emp-aditya", "ritu", NDR, 25), ("emp-yash", "peepal", CS, 25),
    ("emp-om", "vayu", CS, 25), ("emp-zoya", "ember", ACC, 25), ("emp-rhea", "ritu", CS, 25),
    ("emp-aanya", "copper", CS, 25),  # cross-pod: Early shift cover is scarce
    ("emp-farah", "pebble", CS, 40), ("emp-farah", "pebble", NDR, 20), ("emp-farah", "tiffin", CS, 40),
    ("emp-farah", "tiffin", ACC, 30), ("emp-farah", "amrit", CS, 40),
    ("emp-farah", "bamboo", CS, 40),
    ("emp-divya", "tiffin", CS, 25), ("emp-divya", "pebble", CS, 25),
    ("emp-leela", "tiffin", ACC, 25), ("emp-leela", "pebble", NDR, 20), ("emp-divya", "amrit", CS, 25),
    ("emp-manav", "bamboo", CS, 25),
    ("emp-vikram", "dhaga", CS, 40), ("emp-vikram", "loom", CS, 40), ("emp-vikram", "chai", CS, 40),
    ("emp-vikram", "monsoon", CS, 40),
    ("emp-nikhil", "dhaga", CS, 25), ("emp-nikhil", "loom", CS, 25),
    ("emp-sameer", "loom", CS, 25),
]

# process id, rule type, weekday, date, min staff, note
COVERAGE_RULES = [
    (bp_id("ember", CS), "weekday", 5, None, 2, "Saturday is the brand's peak support day"),
    (bp_id("kora", CS), "date", None, date(2026, 12, 25), 0, "Client closes support on Christmas Day"),
    (bp_id("rangoli", CS), "date", None, date(2026, 12, 20), 1, "Year-end sale: opens on a Sunday"),
    (bp_id("monsoon", CS), "date", None, date(2026, 12, 31), 2, "New Year's Eve dispatch rush"),
]

# id, employee, type, status, start, end, reason
LEAVES = [
    ("leave-harsh", "emp-harsh", "planned", "approved", date(2026, 12, 14), date(2026, 12, 15), "Family wedding"),
    ("leave-anika", "emp-anika", "planned", "approved", date(2026, 12, 21), date(2026, 12, 23), "Travel"),
    ("leave-ishaan", "emp-ishaan", "planned", "approved", date(2026, 12, 22), date(2026, 12, 23), "Exam"),
    ("leave-meera", "emp-meera", "planned", "approved", date(2026, 12, 22), date(2026, 12, 22), "Personal"),
    ("leave-ayesha", "emp-ayesha", "planned", "approved", date(2026, 12, 30), date(2026, 12, 31), "Travel"),
    ("leave-imran", "emp-imran", "sick", "approved", date(2026, 12, 9), date(2026, 12, 9), "Fever"),
    ("leave-gauri", "emp-gauri", "comp_off", "approved", date(2026, 12, 18), date(2026, 12, 18), "Comp-off for October"),
    ("leave-priya", "emp-priya", "planned", "pending", date(2026, 12, 17), date(2026, 12, 18), "Sister's graduation"),
    ("leave-dev", "emp-dev", "unavailable", "pending", date(2026, 12, 8), date(2026, 12, 8), "Internet outage expected"),
    ("leave-karan", "emp-karan", "planned", "pending", date(2026, 12, 24), date(2026, 12, 24), "Personal"),
    ("leave-rahul", "emp-rahul", "planned", "rejected", date(2026, 12, 25), date(2026, 12, 25), "Christmas with family"),
]

COMP_OFF_OPENING = [("emp-gauri", 2), ("emp-imran", 1), ("emp-swati", 1)]

# employee, type, weekday, date, shift, weight
PREFERENCES = [
    ("emp-priya", "off_weekday", 6, None, None, 3),
    ("emp-karan", "off_weekday", 6, None, None, 2),
    ("emp-dev", "off_weekday", 5, None, None, 3),
    ("emp-yash", "off_weekday", 6, None, None, 4),
    ("emp-tanvi", "off_weekday", 4, None, None, 2),
    ("emp-riya", "off_date", None, date(2026, 12, 19), None, 5),
    ("emp-imran", "off_weekday", 6, None, None, 3),
    ("emp-leela", "off_date", None, date(2026, 12, 24), None, 4),
    ("emp-pooja", "off_weekday", 6, None, None, 5),
    ("emp-swati", "off_weekday", 3, None, None, 2),
    ("emp-rohan", "avoid_shift", None, None, L, 3),
    ("emp-tushar", "off_date", None, date(2026, 12, 31), None, 5),
]

SETTINGS = {"min_rest_minutes": 660, "fairness_spread_warning": 3}


def brand_processes():
    """Rows of (id, brand, process, calendar, mask, shift)."""
    rows = []
    for brand_id, _, _, procs in BRANDS:
        for entry in procs:
            process, calendar, shift = entry[0], entry[1], entry[2]
            mask = entry[3] if len(entry) > 3 else (0, 1, 2, 3, 4, 5, 6)
            rows.append((bp_id(brand_id, process), brand_id, process, calendar, mask, shift))
    return rows


def allocations():
    """Rows of (id, employee, brand process, role, share)."""
    rows = []
    for emp, brand, process, share in _REGULAR:
        bp = bp_id(brand, process)
        rows.append((f"al-{emp[4:]}-{bp}", emp, bp, "primary", share))
    for emp, brand, process, share in _BACKUP:
        bp = bp_id(brand, process)
        rows.append((f"al-{emp[4:]}-{bp}-b", emp, bp, "backup", share))
    return rows
