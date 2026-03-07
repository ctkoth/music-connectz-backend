# PowerShell script to automate add/commit/push for backend and frontend

# Backend
Write-Host "Committing backend..."
cd "c:\Users\ctkot\OneDrive\Documents\music-connectz-backend django"
git add .
git commit -m "Automated commit from script"
git push

# Frontend
Write-Host "Committing frontend..."
cd "c:\Users\ctkot\OneDrive\Documents\music-connectz-frontend"
git add .
git commit -m "Automated commit from script"
git push

Write-Host "Done!"