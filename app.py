"""
app.py — Web interface for the exam answer shuffler.
Run locally:  python app.py
Deploy:       gunicorn --bind 0.0.0.0:8080 --timeout 300 app:app
"""

import io
import random
import tempfile
from pathlib import Path

from flask import Flask, jsonify, render_template_string, request, send_file

from shuffle import shuffle_exam

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

HTML = """<!DOCTYPE html>
<html dir="rtl" lang="he">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>מערבל מבחנים</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:"Segoe UI",Arial,sans-serif;background:#f0f4f8;color:#1e293b;min-height:100vh}
  header{background:#2563eb;color:#fff;padding:22px 0;text-align:center}
  header h1{font-size:1.7rem;font-weight:700}
  header p{font-size:.92rem;color:#bfdbfe;margin-top:4px}
  main{max-width:500px;margin:32px auto;padding:0 16px}
  .card{background:#fff;border-radius:12px;padding:28px;box-shadow:0 2px 8px #0001}
  .drop-zone{border:2px dashed #cbd5e1;border-radius:10px;background:#e0e7ef;
    padding:36px 20px;text-align:center;cursor:pointer;transition:border-color .2s}
  .drop-zone:hover,.drop-zone.over{border-color:#2563eb;background:#dbeafe}
  .drop-zone .icon{font-size:2.4rem}
  .drop-zone .hint{color:#64748b;font-size:.95rem;margin-top:8px}
  .drop-zone .chosen{color:#2563eb;font-size:.88rem;margin-top:6px;font-style:italic}
  #file-input{display:none}
  .row{display:flex;align-items:center;gap:10px;margin:18px 0 0}
  .row label{font-size:.93rem;white-space:nowrap}
  .row input{width:110px;padding:7px 10px;border:1px solid #cbd5e1;border-radius:7px;
    font-size:.93rem;text-align:center}
  .row .hint-sm{color:#64748b;font-size:.83rem}
  button#go{width:100%;margin-top:18px;padding:13px;background:#2563eb;color:#fff;
    border:none;border-radius:8px;font-size:1rem;font-weight:700;cursor:pointer;transition:background .2s}
  button#go:hover{background:#1d4ed8}
  button#go:disabled{background:#93c5fd;cursor:not-allowed}
  .status{text-align:center;margin-top:14px;font-size:.9rem;color:#64748b;min-height:20px}
  .status.err{color:#dc2626}
  .status.ok{color:#16a34a}
  progress{width:100%;height:6px;border-radius:4px;margin-top:8px;display:none}
  button#dl{display:none;width:100%;margin-top:12px;padding:11px;background:#16a34a;
    color:#fff;border:none;border-radius:8px;font-size:.97rem;font-weight:600;cursor:pointer}
  button#dl:hover{background:#15803d}
</style>
</head>
<body>
<header>
  <h1>🔀&nbsp; מערבל מבחנים</h1>
  <p>העלה קובץ PDF של מבחן — התשובות יעורבלו אוטומטית</p>
</header>
<main>
<div class="card">
  <div class="drop-zone" id="drop-zone" onclick="document.getElementById('file-input').click()">
    <div class="icon">📄</div>
    <div class="hint">גרור PDF לכאן &nbsp;או&nbsp; לחץ לבחירה</div>
    <div class="chosen" id="chosen-name"></div>
    <input type="file" id="file-input" accept=".pdf">
  </div>

  <div class="row">
    <label>סיד (אופציונלי):</label>
    <input type="number" id="seed" placeholder="אקראי">
    <span class="hint-sm">השאר ריק לסיד אקראי</span>
  </div>

  <button id="go" onclick="doShuffle()">ערבל !</button>
  <progress id="prog"></progress>
  <div class="status" id="status"></div>
  <button id="dl">📂&nbsp; הורד את הקובץ המוגמר</button>
</div>
</main>

<script>
const dz = document.getElementById('drop-zone');
const fi = document.getElementById('file-input');
let chosenFile = null, dlBlob = null, dlName = '';

fi.addEventListener('change', () => { if(fi.files[0]) setFile(fi.files[0]); });
dz.addEventListener('dragover', e => { e.preventDefault(); dz.classList.add('over'); });
dz.addEventListener('dragleave', () => dz.classList.remove('over'));
dz.addEventListener('drop', e => {
  e.preventDefault(); dz.classList.remove('over');
  const f = e.dataTransfer.files[0];
  if(f && f.name.endsWith('.pdf')) setFile(f);
  else setStatus('יש לגרור קובץ PDF בלבד', 'err');
});

function setFile(f) {
  chosenFile = f;
  document.getElementById('chosen-name').textContent = f.name;
  document.getElementById('status').textContent = '';
  document.getElementById('dl').style.display = 'none';
  dlBlob = null;
}

function setStatus(msg, cls='') {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = 'status ' + cls;
}

async function doShuffle() {
  if(!chosenFile) { setStatus('יש לבחור קובץ PDF תחילה', 'err'); return; }
  const btn = document.getElementById('go');
  const prog = document.getElementById('prog');
  btn.disabled = true;
  prog.style.display = 'block';
  document.getElementById('dl').style.display = 'none';
  setStatus('מעבד...');

  const fd = new FormData();
  fd.append('file', chosenFile);
  const seed = document.getElementById('seed').value.trim();
  if(seed) fd.append('seed', seed);

  try {
    const res = await fetch('/shuffle', { method:'POST', body:fd });
    if(!res.ok) {
      const j = await res.json().catch(() => ({error: res.statusText}));
      throw new Error(j.error || res.statusText);
    }
    const disp = res.headers.get('Content-Disposition') || '';
    const m = disp.match(/filename="?([^"]+)"?/);
    dlName = m ? m[1] : 'shuffled.pdf';
    dlBlob = await res.blob();
    setStatus('✅  הושלם! סיד: ' + (dlName.match(/\\d+/) || [''])[0], 'ok');
    const dlBtn = document.getElementById('dl');
    dlBtn.style.display = 'block';
    dlBtn.onclick = () => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(dlBlob);
      a.download = dlName;
      a.click();
    };
  } catch(e) {
    setStatus('❌  שגיאה: ' + e.message, 'err');
  } finally {
    btn.disabled = false;
    prog.style.display = 'none';
  }
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/shuffle", methods=["POST"])
def shuffle_endpoint():
    if "file" not in request.files:
        return jsonify(error="לא נבחר קובץ"), 400

    f = request.files["file"]
    if not f.filename.lower().endswith(".pdf"):
        return jsonify(error="יש לשלוח קובץ PDF בלבד"), 400

    seed_str = request.form.get("seed", "").strip()
    seed = int(seed_str) if seed_str.isdigit() else random.randint(0, 2**31)

    with tempfile.TemporaryDirectory() as tmp_dir:
        input_path = Path(tmp_dir) / "input.pdf"
        output_path = Path(tmp_dir) / f"shuffled_{seed}.pdf"
        f.save(input_path)

        try:
            shuffle_exam(input_path, output_path, seed)
            buf = io.BytesIO(output_path.read_bytes())

        except Exception as e:
            return jsonify(error=str(e)), 500

    buf.seek(0)
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"shuffled_{seed}.pdf",
        mimetype="application/pdf",
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
