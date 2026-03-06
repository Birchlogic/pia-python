DATA_ELEMENTS = [
    "PAN",
    "Aadhaar",
    "Mobile Number",
    "Email Address",
    "Loan Account Number",
    "Customer Name",
    "Residential Address",
    "Property Address",
    "Payment History",
    "EMI Amount",
    "Interest Rate"
]


def extract_data_elements(text):

    found = []

    for element in DATA_ELEMENTS:

        if element.lower() in text.lower():
            found.append(element)

    return list(set(found))