#!/usr/bin/env python3
"""
Standalone script to generate a reference HTML DFD from hardcoded
Customer Care data — verifies the renderer before running the full pipeline.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.dfd_html_renderer import DFDHTMLRenderer
from agent.dfd_validator import validate_dfd, format_validation_report

CUSTOMER_CARE_DFD = {
    "department": "Customer Care",
    "version": "1.0",
    "central_process": "ISFC Customer Care Department",
    "actors": [
        {
            "id": "customers",
            "name": "Customers",
            "type": "external",
            "color": "#fffde7",
            "business_processes": [
                {
                    "id": "bp_cc",
                    "name": "Customer Care",
                    "collection_sources": [
                        {
                            "name": "Registered Customers",
                            "data_elements": [
                                "Name", "Contact Information", "Loan ID",
                                "Query / Complaint / Grievance"
                            ]
                        },
                        {
                            "name": "Unregistered Customers",
                            "data_elements": ["Name", "Contact Information"]
                        }
                    ]
                },
                {
                    "id": "bp_compliance",
                    "name": "Compliance Calling",
                    "collection_sources": [
                        {
                            "name": "Excel based Questionnaire",
                            "data_elements": []
                        }
                    ]
                }
            ]
        },
        {
            "id": "internal",
            "name": "Internal Departments",
            "type": "internal",
            "color": "#fce4ec",
            "business_processes": [
                {
                    "id": "bp_datasci",
                    "name": "Data Science Department",
                    "collection_sources": [
                        {
                            "name": "Data regarding Customer EMI Payments",
                            "data_elements": []
                        }
                    ]
                }
            ]
        },
        {
            "id": "vendors",
            "name": "Vendors/Partners",
            "type": "vendor",
            "color": "#f1f8e9",
            "business_processes": []
        }
    ],
    "dispersal_sinks": [
        {
            "id": "sink_payment",
            "name": "Payment Reminders",
            "actor_id": "customers",
            "color": "#4caf50"
        },
        {
            "id": "sink_grievance",
            "name": "ISFC Grievance Department",
            "actor_id": "internal",
            "color": "#43a047"
        },
        {
            "id": "sink_sales",
            "name": "ISFC Sales Department",
            "actor_id": "internal",
            "color": "#7b1fa2"
        },
        {
            "id": "sink_audit",
            "name": "ISFC Field Audit and Anti-Fraud Department",
            "actor_id": "internal",
            "color": "#7b1fa2"
        },
        {
            "id": "sink_vendor",
            "name": "Kalyera Exotel for automated payment reminders",
            "actor_id": "vendors",
            "color": "#1565c0"
        }
    ],
    "storage_systems": [
        {"name": "One Drive", "type": "cloud"},
        {"name": "Salesforce CRM", "type": "cloud"},
        {"name": "Kalyera Exotel Repository", "type": "database"}
    ],
    "data_flows": [
        {"from_id": "bp_cc", "to_id": "central_process", "color": "#1565c0", "label": "Customer Data"},
        {"from_id": "bp_compliance", "to_id": "central_process", "color": "#e91e63", "label": "Compliance Data"},
        {"from_id": "bp_datasci", "to_id": "central_process", "color": "#9e9e9e", "label": "EMI Payment Data"},
        {"from_id": "central_process", "to_id": "sink_payment", "color": "#4caf50"},
        {"from_id": "central_process", "to_id": "sink_grievance", "color": "#43a047"},
        {"from_id": "central_process", "to_id": "sink_sales", "color": "#7b1fa2"},
        {"from_id": "central_process", "to_id": "sink_audit", "color": "#7b1fa2"},
        {"from_id": "central_process", "to_id": "sink_vendor", "color": "#1565c0"}
    ]
}

if __name__ == "__main__":
    # Validate
    result = validate_dfd(CUSTOMER_CARE_DFD)
    print(format_validation_report(result))
    print()

    # Render HTML
    renderer = DFDHTMLRenderer()
    html = renderer.render(CUSTOMER_CARE_DFD)

    out_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "data", "reports", "Customer_Care_DFD_preview.html"
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)

    print(f"HTML DFD written to: {out_path}")
    print("Open it in a browser to preview.")
