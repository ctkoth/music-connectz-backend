# Recover the repo after the force-push (requirements.txt missing)

The force-push replaced the GitHub repo with your local tree, and your local copy
was missing requirements.txt (Render: "Could not open requirements file"). Other
root files (manage.py, the project package with settings.py / wsgi.py) may also be
missing. Do this:

## 1. See what's actually in the repo now
```bash
cd ~/music-connectz-backend
ls
git ls-files | grep -Ei 'requirements|manage.py|wsgi|settings' || echo "MISSING core files"
```

## 2A. If ONLY requirements.txt is missing (manage.py + project package still there)
Just add the one in this zip and push normally:
```bash
cp ~/path-to-unzip/music-connectz-backend/requirements.txt .
git add requirements.txt
git commit -m "Restore requirements.txt"
git push origin HEAD:main
```

## 2B. If manage.py / wsgi / settings are ALSO missing (the push clobbered the repo)
Recover the previous good commit. A force-push leaves the old commit reachable in
your local reflog:
```bash
cd ~/music-connectz-backend
git reflog --all | head -20
# find the commit from BEFORE your force-push (the last one that deployed OK),
# copy its short SHA, then:
git reset --hard <GOOD_SHA>

# re-apply the new apps + requirements on top of the restored repo
cp -r ~/path-to-unzip/music-connectz-backend/apps/* apps/
cp ~/path-to-unzip/music-connectz-backend/requirements.txt .
git add -A
git commit -m "Re-add SkillZ/OAuth + requirements onto restored repo"
git push origin HEAD:main        # normal push (no --force needed now)
```

If your local has no good reflog entry, your ORIGINAL clone (the folder you pushed
from successfully earlier today) still has the full project — push from THAT folder
instead, after copying the apps/ + requirements.txt into it.

## 3. Going forward — don't force-push from a partial copy
Always work from a full clone:
```bash
git clone https://github.com/ctkoth/music-connectz-backend.git
cd music-connectz-backend
cp -r ~/path-to-unzip/music-connectz-backend/apps/* apps/
cp ~/path-to-unzip/music-connectz-backend/requirements.txt .
git add -A && git commit -m "Add SkillZ + OAuth" && git push origin HEAD:main
```
A normal push onto a full clone never deletes files.
