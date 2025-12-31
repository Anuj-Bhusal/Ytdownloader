# YouTube Downloader Web App

A web-based YouTube video downloader with a modern UI that works on all devices including iOS.

## Project Structure

```
yt-downloader-web/
├── frontend/           # Static website (host on Cloudflare Pages)
│   ├── index.html
│   ├── style.css
│   └── app.js
└── backend/            # Python API (host on Railway/Render)
    ├── app.py
    ├── requirements.txt
    └── Procfile
```

## Deployment Guide

### Step 1: Deploy Backend API (Railway - Free)

1. **Create a Railway Account**: Go to [railway.app](https://railway.app) and sign up with GitHub

2. **Create New Project**:
   - Click "New Project" → "Deploy from GitHub repo"
   - Connect your GitHub account
   - Create a new repo or use existing one

3. **Push Backend Code**:
   ```bash
   cd backend
   git init
   git add .
   git commit -m "Initial backend"
   git remote add origin https://github.com/YOUR_USERNAME/yt-downloader-api.git
   git push -u origin main
   ```

4. **Configure Railway**:
   - Railway will auto-detect Python and deploy
   - Add FFmpeg buildpack: Settings → Add Buildpack → `heroku/ffmpeg`
   - Get your API URL from the deployment (e.g., `https://yt-downloader-api-production.up.railway.app`)

### Step 2: Update Frontend with API URL

1. Open `frontend/app.js`
2. Change line 2:
   ```javascript
   const API_BASE_URL = 'https://YOUR-RAILWAY-URL.up.railway.app';
   ```

### Step 3: Deploy Frontend (Cloudflare Pages)

1. **Push Frontend to GitHub**:
   ```bash
   cd frontend
   git init
   git add .
   git commit -m "Initial frontend"
   git remote add origin https://github.com/YOUR_USERNAME/yt-downloader.git
   git push -u origin main
   ```

2. **Connect to Cloudflare Pages**:
   - Go to Cloudflare Dashboard → Pages
   - Click "Create a project" → "Connect to Git"
   - Select your frontend repository
   - Build settings: Leave blank (static site)
   - Click "Save and Deploy"

3. **Connect Your Domain**:
   - Go to your project in Cloudflare Pages
   - Custom domains → Add custom domain
   - Enter your domain (already connected to Cloudflare)
   - It will automatically configure DNS

## Alternative: Railway for Everything

Railway can also host static sites. You can deploy both frontend and backend as a monorepo.

## Features

- 🎬 Download videos in any resolution (up to 4K)
- 🎵 Extract audio as MP3 (320kbps)
- 📱 Fully responsive - works on mobile, tablet, desktop
- 🍎 iOS compatible
- 🌙 Dark mode UI
- ⚡ Fast and reliable

## Local Testing

### Backend:
```bash
cd backend
pip install -r requirements.txt
python app.py
```

### Frontend:
Just open `frontend/index.html` in a browser, or use a local server:
```bash
cd frontend
python -m http.server 8000
```

## Notes

- The backend requires FFmpeg for video/audio processing
- Railway's free tier has 500 hours/month
- Cloudflare Pages is completely free for static sites
- Large video downloads may timeout on free hosting tiers
