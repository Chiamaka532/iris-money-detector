import streamlit as st
import pandas as pd
from engines import run_duplicate_engine, run_price_engine, run_saas_engine, run_offcontract_engine
from connectors import get_qb_auth_url, get_qb_tokens, fetch_qb_transactions
from utils import load_sample_data, generate_pdf_report

st.set_page_config(page_title="IRIS PRO", layout="wide", initial_sidebar_state="expanded")

st.title("IRIS PRO: PE Spend Leakage Command Center")
st.caption("Autonomous AI that finds 2-7% of portfolio company spend in 48 hours")

if 'df' not in st.session_state:
    st.session_state.df = load_sample_data()
if 'results' not in st.session_state:
    st.session_state.results = None

with st.sidebar:
    st.header("1. Data Intake")
    upload_method = st.selectbox("Upload Method", ["Demo Mode", "Upload Money Image", "Upload Excel/CSV/Zip", "Connect QuickBooks"])

    df = st.session_state.df # start with current df

    if upload_method == "Demo Mode":
        st.info("Using sample data")
        df = load_sample_data()

    elif upload_method == "Upload Excel/CSV/Zip":
        file = st.file_uploader("Drop GL + Vendor + Contract Files", type=['csv', 'xlsx', 'zip'])
        if file:
            try:
                if file.name.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)

                # AUTO-FIX COLUMNS
                df.columns = df.columns.str.strip().str.lower()
                df = df.rename(columns={
                    'date': 'Date',
                    'invoice date': 'Date',
                    'vendor': 'Vendor_Name',
                    'vendor_name': 'Vendor_Name',
                    'supplier': 'Vendor_Name',
                    'amount': 'Amount',
                    'total': 'Amount',
                    'total amount': 'Amount',
                    'cost': 'Amount',
                    'category': 'Category',
                    'class': 'Category',
                    'department': 'Category',
                    'contract id': 'Contract_ID',
                    'contract_id': 'Contract_ID'
                })

                # Add missing columns with defaults
                for col in ['Date', 'Vendor_Name', 'Amount', 'Category']:
                    if col not in df.columns:
                        df[col] = "" if col!= 'Amount' else 0
                if 'Contract_ID' not in df.columns:
                    df['Contract_ID'] = ""

                st.success(f"✅ Data Loaded: {len(df)} rows")
                st.write("Columns:", df.columns.tolist())

            except Exception as e:
                st.error(f"❌ Error loading file: {e}")

    elif upload_method == "Connect QuickBooks":
        if "qb_token" not in st.session_state:
            auth_url = get_qb_auth_url()
            st.markdown(f"[Click to Connect QB]({auth_url})")
            auth_code = st.text_input("Paste Code from URL")
            if st.button("Authorize"):
                tokens = get_qb_tokens(auth_code)
                st.session_state["qb_token"] = tokens["access_token"]
                st.session_state["qb_company"] = tokens["realmId"]
                st.rerun()
        else:
            st.success("QB Connected")
            if st.button("Pull 12 Months Data"):
                df = fetch_qb_transactions(st.session_state["qb_token"], st.session_state["qb_company"])

    elif upload_method == "Upload Money Image":
        file = st.file_uploader("Upload Money Image", type=["jpg", "jpeg", "png"])
        if file:
            from PIL import Image
            image = Image.open(file)
            st.image(image, caption="Uploaded Image", width='stretch')
            st.success("Image Loaded! Now add your model prediction code here")

    st.session_state.df = df # save at the end

    st.divider()
    if st.button("RUN FULL LEAKAGE SCAN", type="primary", width='stretch'):
        if df.empty:
            st.warning("Please upload data or select Demo Mode first")
        else:
            with st.spinner("Running 4 AI Engines..."):
                try:
                    dup = run_duplicate_engine(df)
                    price = run_price_engine(df)
                    saas = run_saas_engine(df)
                    off = run_offcontract_engine(df)
                    st.session_state.results = {"Duplicates": dup, "Price Variance": price, "SaaS Waste": saas, "Off-Contract": off}
                    st.success("Scan Complete")
                except Exception as e:
                    st.error(f"Engine error: {e}")

if st.session_state.results:
    st.header("2. Leakage Dashboard")
    total_leakage = sum([r['savings'].sum() for r in st.session_state.results.values()])
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("TOTAL LEAKAGE FOUND", f"${total_leakage:,.0f}")
    c2.metric("Duplicate Payments", f"${st.session_state.results['Duplicates']['savings'].sum():,.0f}")
    c3.metric("Price Variance", f"${st.session_state.results['Price Variance']['savings'].sum():,.0f}")
    c4.metric("SaaS + Off-Contract", f"${st.session_state.results['SaaS Waste']['savings'].sum() + st.session_state.results['Off-Contract']['savings'].sum():,.0f}")

    for name, res in st.session_state.results.items():
        with st.expander(f"{name} - ${res['savings'].sum():,.0f} Found"):
            st.dataframe(res['data'], width='stretch')
            st.download_button(f"Download {name} CSV", res['data'].to_csv(), f"{name}.csv")

    st.divider()
    if st.button("Generate PE Board PDF Report", type="primary"):
        pdf_path = generate_pdf_report(total_leakage, st.session_state.results)
        with open(pdf_path, "rb") as f:
            st.download_button("Download Board Report", f, "IRIS_PRO_Report.pdf")
