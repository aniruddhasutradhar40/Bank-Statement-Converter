# Bank Statement Converter

PDF bank statement → Excel (.xlsx) / CSV. FastAPI + pdfplumber + pandas + openpyxl. No login, no paid APIs.

## লোকালি চালান
```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```
ব্রাউজারে খুলুন: http://127.0.0.1:8000

## GitHub-এ আপলোড
```bash
git init && git add . && git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USER/bank-converter.git
git push -u origin main
```

## Render (Free) এ Deploy
1. render.com → New → Web Service → GitHub repo সিলেক্ট করুন
2. Runtime: Python, Build: `pip install -r requirements.txt`
3. Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Instance type: Free → Deploy (Free প্ল্যানে কিছুক্ষণ অব্যবহৃত থাকলে প্রথম লোড ধীর হয়)

বিকল্প: Hugging Face Spaces (Docker SDK; Dockerfile-এ port 7860 দিন) বা Koyeb/Fly.io free tier।

## নিরাপত্তা
- ফাইল ডিস্কে সেভ হয় না, শুধু মেমোরিতে প্রসেস হয়
- রেজাল্ট ১০ মিনিট পর অটো-ডিলিট; "Delete my data now" বাটনে সাথে সাথে মুছে যায়
- সর্বোচ্চ ১০ MB / ৬০ পেজ, শুধু বৈধ PDF
- Scanned (ছবি-ভিত্তিক) PDF সাপোর্ট করে না (OCR লাগবে)
