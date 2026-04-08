# MusicConnectZ Quick Setup Guide

This guide helps any developer set up Google Maps and CORS for local or production use.

## 1. Google Maps API Key

1. Get your Google Maps API key from the Google Cloud Console.
2. Open the `.env` file in the project root.
3. Add or update this line:

   REACT_APP_GOOGLE_MAPS_API_KEY=your_actual_api_key_here

4. Save the file and restart your frontend server.

---

## 2. Django Backend CORS Setup

1. Make sure `django-cors-headers` is installed:

   pip install django-cors-headers

2. In your `settings.py`, add to `INSTALLED_APPS`:

   'corsheaders',

3. Add to the top of your `MIDDLEWARE` list:

   'corsheaders.middleware.CorsMiddleware',

4. Add this to your settings:

   CORS_ALLOWED_ORIGINS = [
       "https://musicconnectz.net",
       "https://www.musicconnectz.net",
   ]

5. Save and restart your backend server.

---

## 3. Need Help?

If you get stuck, ask Corey or check the README for more details!
