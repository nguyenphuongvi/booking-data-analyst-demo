# Export Documentation Intelligence — Original App / Public Presentation

This repository is the **original Streamlit app supplied by the project author**, prepared for a public presentation on Streamlit Community Cloud. It is **not** the separate QR-demo app. The operational pages remain: Dashboard, New Booking, Process Overview, Documents, Deadlines, Bookings, Tracking, B/L, Settings. A **Data Analysis** page was added to demonstrate the mathematical and statistical methods in the internship report.

## Important: public showcase, not the production system

- **Synthetic sample data only.** Use **Load synthetic booking sample** in the left sidebar, then open **Data Analysis**.
- Storage is a temporary per-Streamlit-session folder. It is **not permanent**, and the server can reset it at any time. Cross-session application storage is not used in this public build.
- Do not upload real packing lists, booking confirmations, customer information, DG documentation or company database files into a public demo.
- External Gemini AI calls are **disabled in this public build**. Offline extraction, rule-based parsing, manual review and analytics remain accessible. Some original AI-assisted extraction features may fall back to rules and manual review.
- Not a secure multi-user production document-management deployment. Use authenticated access, separate storage and a durable managed database before hosting any real data.

## Cloud deploy

1. Publish all files in this folder to a GitHub repository. On macOS, with `gh` already authenticated:

   ```bash
   cd ~/Downloads/booking_goc_streamlit_cloud
   bash publish_to_github_mac.sh booking-data-analyst-demo
   ```

2. Go to [Streamlit Community Cloud](https://share.streamlit.io/), create an app using GitHub:

   | Setting | Value |
   |---|---|
   | Repository | `YOUR_GITHUB_USER/booking-data-analyst-demo` |
   | Branch | `main` |
   | Main file path | `app.py` |

3. Deploy and verify the URL in a mobile browser using 4G/5G.
4. Convert **the actual deployed URL** to a QR code. The URL is not known before deployment.

Do not commit `.env`, `.streamlit/secrets.toml`, Excel sheets, SQLite databases, uploaded documents or any company file.

## Run locally as the public demo copy

```bash
cd ~/Downloads/booking_goc_streamlit_cloud
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.port 8503
```

This will **not replace** your original local project. This package makes a copy of it for public presentation. To return to the full operational local app, use your original private source — not this demo distribution.

## Data Analysis page

`cloud_demo.py` illustrates:

- Profiling: missing carriers, invalid ETD and unavailable lead-time pairs.
- One shipment = one distinct Booking ID; containers aggregated beforehand.
- Monthly shipment totals, MoM change, 3-month rolling average.
- Carrier share and HHI, POL→POD route composition.
- Lead time (`ETD - Booking Date`) and mean, median, standard deviation, Q1/Q3, IQR and P90.
- Explicit interpretation and limitations. All built-in values are **fabricated** and do not imply performance of the named business.

## Limitations checked

The source syntax, synthetic workbook, calculation functions and SQLite synchronization have been tested in the creation environment. Running Streamlit itself was **not** possible there because Streamlit was not installed and outgoing package installation was blocked. Cloud deployment can reveal environment-specific errors; view the Streamlit deployment log if that happens.
