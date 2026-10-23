import io, re, time, uuid
import pandas as pd
import pdfplumber
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

MAX_MB, MAX_PAGES, TTL = 10, 60, 600  # 10 MB, 60 pages, files live 10 min
STORE = {}  # token -> (expiry, DataFrame) ; memory only, nothing is written to disk
app = FastAPI(title="Bank Statement Converter")

DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}[ -][A-Za-z]{3,9}[ -,]+\d{2,4})"
DATE_RE = re.compile(rf"^\s*{DATE}\b")
AMT_RE = re.compile(r"(?<![\w.])\(?-?\d[\d,]*\.\d{2}\)?(?:\s?(?:Cr|Dr|CR|DR))?(?!\w)")
COLS = ["Date", "Description", "Debit", "Credit", "Balance"]


def num(s):
    if s is None or not str(s).strip():
        return None
    s = str(s).strip()
    neg = s.startswith(("(", "-")) or s.upper().endswith("DR")
    t = re.sub(r"[^\d.]", "", s)
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def parse_tables(pdf):
    rows, cmap = [], None
    for page in pdf.pages:
        for tb in page.extract_tables() or []:
            for r in tb:
                cells = [(c or "").replace("\n", " ").strip() for c in r]
                low = [c.lower() for c in cells]
                if any("date" in c for c in low) and any(k in " ".join(low) for k in ("debit", "credit", "withdraw", "deposit", "balance")):
                    m = {}
                    for i, c in enumerate(low):
                        if "date" in c and "date" not in m: m["date"] = i
                        elif any(k in c for k in ("desc", "particular", "narration", "detail", "remark")): m["desc"] = i
                        elif any(k in c for k in ("debit", "withdraw")) or c in ("dr", "dr."): m["debit"] = i
                        elif any(k in c for k in ("credit", "deposit")) or c in ("cr", "cr."): m["credit"] = i
                        elif "balance" in c: m["balance"] = i
                    cmap = m
                    continue
                if not cmap or len(cells) <= max(cmap.values()):
                    continue
                d = cells[cmap["date"]]
                if DATE_RE.match(d):
                    g = lambda k: num(cells[cmap[k]]) if k in cmap else None
                    deb, cre = g("debit"), g("credit")
                    rows.append([d, cells[cmap["desc"]] if "desc" in cmap else "",
                                 abs(deb) if deb else None, abs(cre) if cre else None, g("balance")])
                elif rows and "desc" in cmap and cells[cmap["desc"]] and not d:
                    rows[-1][1] = (rows[-1][1] + " " + cells[cmap["desc"]]).strip()
    return rows


def parse_text(pdf):
    rows, prev = [], None
    for page in pdf.pages:
        for line in (page.extract_text() or "").split("\n"):
            m = DATE_RE.match(line)
            amts = list(AMT_RE.finditer(line[m.end():])) if m else []
            if not m:
                if rows and not AMT_RE.search(line) and 2 < len(line) < 80:
                    rows[-1][1] = (rows[-1][1] + " " + line.strip()).strip()
                continue
            if not amts:
                continue
            rest = line[m.end():]
            desc = rest[:amts[0].start()].strip()
            vals = [num(a.group()) for a in amts]
            raw = [a.group().upper() for a in amts]
            deb = cre = bal = None
            if len(vals) >= 3:
                deb, cre, bal = abs(vals[-3]) or None, abs(vals[-2]) or None, vals[-1]
            else:
                amt = abs(vals[-2] if len(vals) == 2 else vals[0])
                bal = vals[-1] if len(vals) == 2 else None
                if prev is not None and bal is not None:
                    is_cr = bal > prev
                elif raw[0].endswith("CR") or re.search(r"\b(credit|deposit|salary|refund|interest)\b", desc, re.I):
                    is_cr = True
                else:
                    is_cr = False
                deb, cre = (None, amt) if is_cr else (amt, None)
            if bal is not None:
                prev = bal
            rows.append([m.group(1), desc, deb, cre, bal])
    return rows


def convert(data: bytes) -> pd.DataFrame:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise HTTPException(413, f"Too many pages (max {MAX_PAGES}).")
            rows = parse_tables(pdf)
            if len(rows) < 2:
                rows = parse_text(pdf)
    except HTTPException:
        raise
    except Exception as e:
        msg = "Password-protected PDFs are not supported." if "password" in str(e).lower() else "Could not read this PDF."
        raise HTTPException(400, msg)
    if not rows:
        raise HTTPException(422, "No transactions found. Scanned (image-only) PDFs are not supported.")
    return pd.DataFrame(rows, columns=COLS)


def purge():
    now = time.time()
    for k in [k for k, (exp, _) in STORE.items() if exp < now]:
        del STORE[k]


@app.post("/api/convert")
def api_convert(file: UploadFile = File(...)):
    purge()
    data = file.file.read(MAX_MB * 1024 * 1024 + 1)
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"File too large (max {MAX_MB} MB).")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, "Please upload a valid PDF file.")
    df = convert(data)
    del data
    token = uuid.uuid4().hex
    STORE[token] = (time.time() + TTL, df)
    return {
        "token": token, "total": len(df), "expires_in": TTL,
        "debit_total": round(float(df.Debit.sum()), 2), "credit_total": round(float(df.Credit.sum()), 2),
        "preview": df.head(100).astype(object).where(df.head(100).notna(), None).values.tolist(),
    }


@app.get("/api/download/{token}.{fmt}")
def api_download(token: str, fmt: str):
    purge()
    item = STORE.get(token)
    if not item or fmt not in ("xlsx", "csv"):
        raise HTTPException(404, "File expired or not found.")
    df, buf = item[1], io.BytesIO()
    if fmt == "csv":
        buf.write(df.to_csv(index=False).encode("utf-8-sig"))
        mt = "text/csv"
    else:
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df.to_excel(w, index=False, sheet_name="Statement")
            ws = w.sheets["Statement"]
            for col, width in zip("ABCDE", (14, 60, 14, 14, 16)):
                ws.column_dimensions[col].width = width
            for row in ws.iter_rows(min_row=2, min_col=3, max_col=5):
                for c in row:
                    c.number_format = "#,##0.00"
        mt = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    buf.seek(0)
    return StreamingResponse(buf, media_type=mt, headers={"Content-Disposition": f'attachment; filename="statement.{fmt}"'})


@app.delete("/api/file/{token}")
def api_delete(token: str):
    STORE.pop(token, None)
    return {"deleted": True}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
