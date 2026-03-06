SYSTEM_LIST = [
    "Salesforce",
    "Ameyo",
    "WhatsApp",
    "OneDrive",
    "Microsoft 365",
    "Excel"
]


def extract_systems(text):

    systems = []

    for s in SYSTEM_LIST:

        if s.lower() in text.lower():
            systems.append(s)

    return list(set(systems))