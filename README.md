# Call CRM

A simple multi-user calling CRM built with Streamlit and SQLite.

## Run locally
1. Install Python 3.10 or newer.
2. Open a terminal in this folder.
3. Run: `pip install -r requirements.txt`
4. Run: `streamlit run app.py`
5. Open the local URL shown by Streamlit.

## First login
- Username: `admin`
- Password: `admin123`
- Change the administrator password immediately in **User Management**.

## Included
- Up to 9 user accounts (including admin)
- Lead ownership / assignment
- Call and email activity notes
- Follow-up dates and overdue/today/upcoming colour indicators
- CSV and XLSX import; CSV export
- Dashboard and user-wise call counts
- Password hashing

## Your uploaded workbook
The importer recognises Client Name, Contact No, Distt., State, Proposal Send and Remark.
Other columns in the workbook are retained in an "Imported Extra Notes" field.

## Important deployment note
This starter version stores data in `crm_data.db` on the machine running Streamlit. For a small team on one server, all users should access the same running app instance and the same database file. Do not deploy multiple app instances with separate local databases. For reliable internet-based team use, backups, and concurrent access, move the database to hosted PostgreSQL before production deployment. Use HTTPS and unique passwords. The app does not send emails; it records email addresses and email activity/notes.
