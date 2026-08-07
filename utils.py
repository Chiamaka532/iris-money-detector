import pandas as pd
import numpy as np
from fpdf import FPDF
import datetime

def load_sample_data():
    """Generates $50M fake spend with $3.2M in leaks for demo"""
    np.random.seed(42)
    vendors = ['Microsoft', 'AWS', 'Salesforce', 'Office Depot', 'FedEx', 'Vendor A', 'Vendor B']
    categories = ['SaaS', 'Cloud', 'Office Supplies', 'Shipping', 'Consulting']
    data = []
    for i in range(2000):
        data.append({
            "Company_Name": "DemoCo", "Vendor_Name": np.random.choice(vendors),
            "Invoice_ID": f"INV{1000+i}" if i % 50 != 0 else f"INV{1000+i-1}", # create duplicates
            "Date": pd.Timestamp('2024-01-01') + pd.Timedelta(days=np.random.randint(0,365)),
            "Amount": np.random.uniform(500, 50000), "Category": np.random.choice(categories),
            "Contract_ID": "" if np.random.rand() > 0.7 else f"CTR{np.random.randint(1,10)}"
        })
    return pd.DataFrame(data)

def generate_pdf_report(total, results):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, "IRIS PRO - Executive Leakage Report", 0, 1, 'C')
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Date: {datetime.date.today()}", 0, 1, 'C')
    pdf.ln(10)
    pdf.set_font("Arial", 'B', 14)
    pdf.cell(0, 10, f"TOTAL LEAKAGE IDENTIFIED: ${total:,.0f}", 0, 1)
    pdf.ln(5)
    for name, res in results.items():
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f"{name}: ${res['savings'].sum():,.0f}", 0, 1)
    pdf.output("IRIS_PRO_Report.pdf")
    return "IRIS_PRO_Report.pdf"
