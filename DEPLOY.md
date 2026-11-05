# Deploy BoatKeeper Online — Step-by-Step Guide

This guide shows you how to deploy BoatKeeper online for free using **Render.com**. Your employees will be able to access it from any device, anywhere.

---

## Option 1: Deploy with Render.com (Recommended — Free)

Render.com offers free Python web app hosting. No credit card required.

### Step 1: Put your code on GitHub

1. Go to **https://github.com** and sign in (or create a free account)
2. Click the **"+"** icon (top right) → **New repository**
3. Repository name: `boatkeeper`
4. Leave it **Public**, click **Create repository**
5. Open PowerShell and run these commands:

```powershell
cd C:\Users\flore\PycharmProjects\PythonProject1\online
git init
git add .
git commit -m "Initial BoatKeeper app"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/boatkeeper.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your GitHub username.

### Step 2: Create a Render account

1. Go to **https://render.com**
2. Click **Get Started for Free**
3. Sign up using your GitHub account (easiest option)

### Step 3: Deploy the app

1. In Render dashboard, click **"+ New"** → **"Web Service"**
2. Connect your `boatkeeper` GitHub repository
3. Fill in the settings:
   - **Name**: `boatkeeper`
   - **Region**: Choose closest to you (e.g., Frankfurt)
   - **Root Directory**: `online` (if you pushed the whole project) or leave blank if only the `online` folder is in the repo
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:application`
   - **Instance Type**: **Free**

4. Click **Create Web Service**
5. Wait 2–5 minutes for the build to complete
6. Your app will be live at: `https://boatkeeper-xxxx.onrender.com`

### Step 4: Set a secure secret key (Important!)

1. In your Render service, go to **Environment** tab
2. Add a variable:
   - **Key**: `SECRET_KEY`
   - **Value**: Any random long string (e.g., `my-super-secret-boatkeeper-key-2026`)
3. Click **Save Changes** — the app will restart automatically

### Step 5: Log in and set up

1. Open your app URL
2. Log in with: **username**: `admin`, **password**: `admin123`
3. Go to **Admin** panel and change your password
4. Create employee accounts

### Step 6: Share with employees

Send them the URL (e.g., `https://boatkeeper-xxxx.onrender.com`). They log in with the accounts you created.

---

## Option 2: Deploy with PythonAnywhere (Alternative — Free)

### Step 1: Create account

1. Go to **https://www.pythonanywhere.com**
2. Sign up for a free account

### Step 2: Upload your files

1. Go to **Files** tab
2. Click **Upload file** and upload all files from the `online/` folder:
   - `app.py`
   - `requirements.txt`
   - The `templates/` folder
   - The `static/` folder

### Step 3: Install dependencies

1. Go to **Consoles** → **Open Bash**
2. Run:
```bash
pip install -r ~/requirements.txt
```

### Step 4: Configure the web app

1. Go to **Web** tab → **Add a new Web app**
2. Choose **Manual configuration**, Python 3.10
3. Go to **Code** section:
   - WSGI configuration file: Edit and replace with:
```python
import sys
sys.path.insert(0, '/home/YOUR_USERNAME/')
from app import application
```
4. Go to **Virtualenv** section:
   - Enter your virtualenv path (or leave blank for system Python)

### Step 5: Set environment variable

1. Go to **Variables** in the Web tab
2. Add: `SECRET_KEY` = your random secret string
3. Click **Save**

### Step 6: Start the app

1. Click **Reload** your web app
2. Your app will be at: `https://YOUR_USERNAME.pythonanywhere.com`

---

## Important Notes

### Free tier limitations

- **Render.com**: The free tier "sleeps" after 15 minutes of inactivity. The first request after sleeping takes ~30 seconds to wake up.
- **PythonAnywhere**: Free tier has limited features but stays awake.

### Data persistence

- Your SQLite database (`boatkeeper.db`) is stored on the server
- On Render.com, the database file persists as long as your service exists
- **Backup regularly**: Download the database file periodically

### Security

- **Change the default admin password** immediately after first login
- Set a strong `SECRET_KEY` environment variable
- Only share employee login credentials with your team

### Upgrading later

If you need more power or no sleep:
- Render.com paid plans start at $7/month
- PythonAnywhere paid plans start at £4/month

---

## Quick Summary

| Step | Action | Time |
|------|--------|------|
| 1 | Push code to GitHub | 5 min |
| 2 | Create Render account | 2 min |
| 3 | Deploy on Render | 5 min |
| 4 | Set SECRET_KEY | 1 min |
| 5 | Log in & create employees | 5 min |
| **Total** | | **~18 minutes** |

After deployment, your employees access the app from any browser — phone, tablet, or desktop. All data is shared in one central database.
