# BodieZ demo clips still needed

Snapshot from `python manage.py bodiez_video_audit` on 2026-10-08 — **37 of 71 exercises have a clip; 34 listed below.**
Re-run the command for the live list; this file is a dated record, not the source of truth.

## Seated / lying (22) — record these first

These are what a member who can't stand or walk is offered, so a missing clip here
is a gap for exactly the people the "What I can do" filter exists for.

| Muscle | Exercise | Equipment | Position | Needs | Suggested file |
|---|---|---|---|---|---|
| abs | Crunch | bodyweight | lying | neither limb required | `crunch.mp4` |
| abs | Russian Twist | bodyweight | seated | arms | `russian-twist.mp4` |
| abs | Seated Ab Crunch | machine | seated | arms | `seated-ab-crunch.mp4` |
| back | Chest-Supported Dumbbell Row | dumbbell | lying | arms | `chest-supported-dumbbell-row.mp4` |
| back | Lat Pulldown (Cable) | cable | seated | arms | `lat-pulldown-cable.mp4` |
| back | Seated Band Row | band | seated | arms | `seated-band-row.mp4` |
| biceps | Bicep Curl | dumbbell | standing/seated | arms | `bicep-curl.mp4` |
| biceps | EZ Bar Curl | ez_bar | standing/seated | arms | `ez-bar-curl.mp4` |
| biceps | Seated Hammer Curl | dumbbell | seated | arms | `seated-hammer-curl.mp4` |
| cardio | Rowing Machine | machine | seated | arms, legs | `rowing-machine.mp4` |
| cardio | Seated Arm Crank | machine | seated | arms | `seated-arm-crank.mp4` |
| chest | Dumbbell Fly | dumbbell | lying | arms | `dumbbell-fly.mp4` |
| chest | Pec Deck | machine | seated | arms | `pec-deck.mp4` |
| chest | Seated Band Chest Press | band | seated | arms | `seated-band-chest-press.mp4` |
| glutes | Glute Bridge | bodyweight | lying | legs | `glute-bridge.mp4` |
| glutes | Seated Hip Abduction | machine | seated | legs | `seated-hip-abduction.mp4` |
| lower_legs | Seated Calf Raise | machine | seated | legs | `seated-calf-raise.mp4` |
| shoulders | Face Pull | band | standing/seated | arms | `face-pull.mp4` |
| shoulders | Seated Machine Shoulder Press | machine | seated | arms | `seated-machine-shoulder-press.mp4` |
| upper_legs | Lying Leg Curl | machine | lying | legs | `lying-leg-curl.mp4` |
| upper_legs | Seated Leg Curl | machine | seated | legs | `seated-leg-curl.mp4` |
| upper_legs | Seated Leg Extension | machine | seated | legs | `seated-leg-extension.mp4` |

## Standing / floor / kneeling (12)

| Muscle | Exercise | Equipment | Position | Needs | Suggested file |
|---|---|---|---|---|---|
| abs | Hanging Leg Raise | bodyweight | standing | arms, legs | `hanging-leg-raise.mp4` |
| abs | Plank | bodyweight | floor | arms, legs | `plank.mp4` |
| back | Pull-Up | bodyweight | standing | arms | `pull-up.mp4` |
| cardio | Running | bodyweight | standing | legs | `running.mp4` |
| full_body | Burpee | bodyweight | standing | arms, legs | `burpee.mp4` |
| full_body | Clean and Press | barbell | standing | arms, legs | `clean-and-press.mp4` |
| full_body | Kettlebell Clean and Press | kettlebell | standing | arms, legs | `kettlebell-clean-and-press.mp4` |
| full_body | Kettlebell Swing | kettlebell | standing | arms, legs | `kettlebell-swing.mp4` |
| full_body | Turkish Get-Up | kettlebell | floor | arms, legs | `turkish-get-up.mp4` |
| lower_legs | Calf Raise | machine | standing | legs | `calf-raise.mp4` |
| upper_legs | Kettlebell Goblet Squat | kettlebell | standing | arms, legs | `kettlebell-goblet-squat.mp4` |
| upper_legs | Lunge | dumbbell | standing | arms, legs | `lunge.mp4` |

## How a clip gets onto an exercise

1. Add the `.mp4` to `ctkoth/mcz-media` under `exercise-demos/` (never in either app repo).
2. Wire it with a one-line data migration that sets `demo_url` to
   `/exercise-demos/<file>.mp4` (percent-encode spaces). Uploading alone does nothing:
   `demo_url` is the only link between a file and an exercise (see migrations 0177, 0178).
3. Suggested filenames are kebab-case like the clips already wired; any name works as
   long as the migration points at it.
