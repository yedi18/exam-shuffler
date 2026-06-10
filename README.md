# מערבל מבחנים

כלי לערבול תשובות במבחני בחירה בעברית (PDF).

## מה זה עושה

- מזהה שאלות בפורמט "שאלה מספר N"
- מערבל את תוכן התשובות תחת כל שאלה
- האותיות א/ב/ג/ד/ה נשארות במקומן — רק התוכן מתחלף
- מחליף את "0000" בכותרת בקוד 4 ספרות ייחודי לפי הסיד

## הרצה

```bash
pip install -r requirements.txt
python app.py
```

פתח בדפדפן: http://localhost:8080

## CLI

```bash
python shuffle.py exam.pdf --seed 42
```

## דרישות

- Python 3.9+
- PyMuPDF, Flask, Pillow (ראה requirements.txt)
