# Railway ID Card Portal

See **README_HI.md** for Hindi setup, admin workflow, HRMS import format, Render + Neon deployment instructions, QR privacy notes and PDF dimensions.

Flask app entry point: `app.py`  
Start command: `gunicorn app:app --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`

## ID Card workflow enhancements

- Admin can upload/replace the issuing authority signature and maintain the authority name and designation from **Card & Logo Setup**.
- Employee signature upload is optional.
- After submission, users see separate Front and Back previews using the generated two-page PDF.
- Final PDF download is enabled only after the user checks both sides and confirms the preview. Direct PDF URL access is also protected by this confirmation.
- Existing databases receive an additive migration for the optional employee signature field at application startup.
