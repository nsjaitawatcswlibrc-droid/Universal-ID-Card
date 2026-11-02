# Railway HRMS-Based Employee ID Card Portal

**Western Railway – Vadodara Division | Admin + Department Login + HRMS Lookup + QR + PDF**

यह एक deploy-ready Flask web application है। Admin HRMS Excel upload कर सकता है, department-wise login बना सकता है और ID-card sample/templates/logos upload कर सकता है। Department user HRMS ID खोजकर विवरण की पुष्टि करता है, mobile/station/photo जोड़ता है और submit के बाद front/back ID Card PDF डाउनलोड करता है।

## 1. इसमें क्या-क्या है

- Admin Dashboard: HRMS records, departments, department logins और generated cards का overview.
- HRMS Excel import: `HRMS ID`, `Name`, `Designation`, `Department`, `IPAS ID` और `Railway unit` कॉलम पहचानता है। `.xlsx`/`.xlsm` फाइल के साथ बिना extension वाली Excel 2007+ workbook भी स्वीकार करता है। आपकी उपलब्ध workbook में header दूसरी row में है; importer ऊपर की 12 rows में header खोजता है।
- Department-wise access: हर Login ID एक Department से जुड़ा रहता है। Login user दूसरे विभाग के कर्मचारी का कार्ड नहीं बना सकता।
- Employee confirmation: HRMS से मिले Name, Designation और Department के लिए Yes/No step.
- No चुनने पर Name, Designation और Department edit किए जा सकते हैं। Correction मूल HRMS master को नहीं बदलता; केवल उस ID-card submission में सेव होता है।
- Mobile, Station और employee photo की manual entry.
- QR Code: HRMS ID, Name, Designation, Department, Station, PF No. और Mobile Number का JSON payload.
- Submit के बाद PDF: दो पेज, पहला Front और दूसरा Back, standard ID-1 size (85.6 × 54 mm).
- Admin के लिए submitted cards की सूची और PDF re-download.
- HRMS, कार्ड आवेदन, photos और uploaded design assets database में सेव होते हैं। PostgreSQL इस्तेमाल करने पर Render restart/redeploy के बाद डेटा बना रहता है।

## 2. Local computer पर चलाएँ

Python 3.11 या 3.12 की सलाह है। Terminal / Command Prompt में:

```bash
cd railway_id_card_portal
python -m venv .venv
```

Windows:

```bat
.venv\Scripts\activate
```

Mac/Linux:

```bash
source .venv/bin/activate
```

फिर:

```bash
pip install -r requirements.txt
```

पहली बार application चलाने पर Admin account बन जाएगा:

- Login ID: `admin`
- Temporary Password: `Brc@2026!`

```bash
python app.py
```

Browser में `http://127.0.0.1:5000` खोलें। पहले login पर नया password बदलना अनिवार्य है। Public/production website के लिए नीचे दिए गए Environment Variables अवश्य सेट करें; ऊपर दिया temporary password केवल local initial setup के लिए है।

## 3. Admin setup का क्रम

1. Admin Login करें और नया password सेट करें।
2. **HRMS Data Upload** में अपनी `.xlsx` / `.xlsm` source workbook upload करें।
3. **Department Logins** में हर Department का Login ID और temporary password बनाएँ। Department नाम HRMS source से dropdown में आएँगे।
4. **Card & Logo Setup** में अलग-अलग upload करें:
   - Reference ID Card Sample (केवल Admin preview)
   - Blank Front Template (optional)
   - Blank Back Template (optional)
   - Railway / Ashoka Logo
   - Vadodara Division Logo
5. Department user अपने ID से login करेगा।
6. HRMS ID डालकर details fetch करेगा; Yes/No confirmation करेगा।
7. Mobile, current station और photo भरेगा। Submit करने पर PDF download खुलेगा।

**Template note:** Existing sample में वास्तविक कर्मचारी की निजी जानकारी है। इसलिए उसे source-code/public assets में शामिल नहीं किया गया है। Admin login के बाद Reference Sample के रूप में upload करें। Front/Back template के लिए वास्तविक blank artwork दें। Blank template में text/photo की जगह खाली होनी चाहिए; app उसके ऊपर dynamic details draw करेगा।

## 4. Render + Neon deployment

GitHub repository में इस folder की सभी files upload करें। Render पर **New → Web Service** चुनकर repository connect करें।

- Runtime: Python 3
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT`

Render Environment में ये variables सेट करें:

| Key | Value |
|---|---|
| `SECRET_KEY` | लंबी random secret string (किसी से साझा न करें) |
| `DATABASE_URL` | Neon का PostgreSQL connection string |
| `ADMIN_USERNAME` | Admin Login ID, जैसे `admin` |
| `ADMIN_PASSWORD` | मजबूत temporary admin password (कम से कम 10 characters) |
| `COOKIE_SECURE` | `true` |

यदि Neon URL `postgres://` से शुरू हो, app उसे `postgresql://` में normalize कर देता है। Neon connection string private रखें। Render deployment में SQLite का उपयोग न करें; Neon PostgreSQL जोड़ें ताकि HRMS records, photos और card templates persistent रहें।

## 5. ID Card PDF का format

- Front and Back अलग-अलग PDF pages पर हैं।
- Page size: 85.6 mm × 54 mm (standard ID-1 card dimensions).
- Front: Division header, HRMS ID, Name, Designation, Department, Station, PF No., Mobile No. और photo.
- Back: Return instructions और QR Code.
- Print करते समय actual size / 100% scale चुनें। Duplex printing में short-edge flip setting का preview लें।

## 6. जरूरी सुरक्षा और संचालन नोट्स

- Employee photo को server पर JPEG में compress करके 100 KB तक रखा जाता है।
- QR Code में mobile number और PF number सहित कर्मचारी की जानकारी plain text JSON के रूप में है। QR scan करने वाला कोई भी व्यक्ति इन fields को पढ़ सकता है। इसे केवल अधिकृत ID-card उपयोग के लिए रखें; अधिक privacy चाहिए तो QR में full details की जगह secure verification URL/ID इस्तेमाल करना बेहतर होगा।
- Department Login को केवल उसके assigned department के HRMS records पर access मिलता है।
- Department user correction करता है तो मूल HRMS record नहीं बदलता। Admin को source correction की आवश्यकता हो तो HRMS workbook update करके फिर upload करना होगा।
- Uploaded image assets database में रखे जाते हैं, website के public static folder में नहीं। Reference sample केवल Admin route से खुलता है।
- Production में मजबूत `SECRET_KEY`, private Neon URL, HTTPS और access-controlled Admin accounts इस्तेमाल करें।

## 7. वर्तमान scope / बाद में जोड़ने योग्य बातें

यह version card generation workflow और Admin/Department login के लिए काम करने वाला baseline है। Blank templates के dynamic field positions आपके final blank artwork को देखकर fine-tune किए जा सकते हैं। वर्तमान workflow में department submit के तुरंत बाद PDF download उपलब्ध है; separate Admin approval, signature image placement, card cancellation/reprint register जैसी सुविधाएँ अगली iteration में जोड़ी जा सकती हैं।
