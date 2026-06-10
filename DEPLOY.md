# Deploy to Google Cloud Run

## דרישות מוקדמות
1. חשבון Google Cloud עם פרויקט פעיל
2. [gcloud CLI](https://cloud.google.com/sdk/docs/install) מותקן
3. Docker מותקן (לבנייה מקומית)

---

## פריסה ראשונה (ידנית)

```bash
# 1. כניסה ל-Google Cloud
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. הפעלת שירותים נדרשים
gcloud services enable run.googleapis.com artifactregistry.googleapis.com

# 3. בניית ה-image ודחיפה ל-Artifact Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/exam-shuffler

# 4. פריסה ל-Cloud Run
gcloud run deploy exam-shuffler \
  --image gcr.io/YOUR_PROJECT_ID/exam-shuffler \
  --platform managed \
  --region europe-west1 \
  --allow-unauthenticated \
  --memory 2Gi \
  --timeout 300 \
  --max-instances 5
```

בסיום תקבל URL כגון: `https://exam-shuffler-xxxx-ew.a.run.app`

---

## עדכון אוטומטי מ-GitHub (CI/CD)

### הגדרת Cloud Build trigger:
1. פתח את [Cloud Build Triggers](https://console.cloud.google.com/cloud-build/triggers)
2. לחץ "Create Trigger"
3. חבר לחשבון GitHub ובחר את ה-repo `exam-shuffler`
4. הגדר: Branch = `master`, Build configuration = `Dockerfile`
5. הוסף את קובץ `cloudbuild.yaml` לפרויקט (ראה למטה)

### cloudbuild.yaml (צור בתיקיית הפרויקט):
```yaml
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/exam-shuffler', '.']
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/exam-shuffler']
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - run
      - deploy
      - exam-shuffler
      - --image=gcr.io/$PROJECT_ID/exam-shuffler
      - --platform=managed
      - --region=europe-west1
      - --allow-unauthenticated
      - --memory=2Gi
      - --timeout=300
```

לאחר הוספת הקובץ ודחיפה ל-GitHub, כל push ל-master יפרוס אוטומטית.

---

## הרצה מקומית (לפיתוח)

```bash
# התקנת תלויות
pip install -r requirements.txt

# הרצה
python app.py
# פתח: http://localhost:8080
```

## הרצה דרך Docker מקומית

```bash
docker build -t exam-shuffler .
docker run -p 8080:8080 exam-shuffler
# פתח: http://localhost:8080
```
