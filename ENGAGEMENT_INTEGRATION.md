# Engagement Features Integration Guide

This document maps all engagement feature trigger points and shows where `record_activity_event()` calls need to be added.

## Activity Event Types and Trigger Points

### ✅ Implemented (Test-Ready)
The engagement infrastructure is complete and tested:
- `engagement.record_activity_event()` function works
- `ActivityEvent` model with all required fields
- API endpoints for presence, activity feed, message receipts
- All tests passing (26 tests)

### 📋 Trigger Points to Implement

#### 1. **follow** — When user follows another user
**File**: `apps/economy/social.py`  
**Location**: `FollowView.post()` at line 1095  
**Code**:
```python
# After: Follow.objects.get_or_create(follower=request.user, following=target)
if created:
    from . import engagement
    engagement.record_activity_event(
        actor=request.user,
        subject=target,
        kind="follow",
        app_key="social",
        target="social:profile?username=" + target.username
    )
```

#### 2. **like** — When user likes a post
**File**: `apps/economy/social.py`  
**Location**: `SocialView.post()` (search for action="react" handling)  
**Code**:
```python
# After reaction is created
if reaction.kind == "like":
    engagement.record_activity_event(
        actor=request.user,
        subject=post.author,
        kind="like",
        app_key="postz",
        target=f"postz:post?id={post.id}"
    )
```

#### 3. **rate** — When user rates a take
**File**: `apps/economy/social.py`  
**Location**: `SocialView.post()` (search for action="rate" handling)  
**Code**:
```python
# After rating is created
engagement.record_activity_event(
    actor=request.user,
    subject=post.author,
    kind="rate",
    app_key="postz",
    target=f"postz:post?id={post.id}"
)
```

#### 4. **post_publish** — When user publishes a post
**File**: `apps/economy/postz.py`  
**Location**: `create_post()` function at line 418  
**Context**: After `Post.objects.create(...)`, add:
```python
# After post is created, notify followers
from . import engagement
# Notify followers that this post was published
# (Optional: can skip for non-public posts)
if p.visibility == "public":
    for follower in Follow.objects.filter(following=user).values_list('follower', flat=True):
        engagement.record_activity_event(
            actor=user,
            subject_id=follower,
            kind="post_publish",
            app_key="postz",
            target=f"postz:post?id={p.id}"
        )
```
**Note**: This is a broadcast event — consider if you want all followers notified or just trending posts.

#### 5. **collab_invite** — When user invites to collaboration
**File**: `apps/economy/collab.py`  
**Location**: `CollabDealsView.post()` (search for deal creation)  
**Code**:
```python
# After CollabDeal is created for each participant
for participant in deal.participants:
    if participant != request.user:  # Don't notify self
        engagement.record_activity_event(
            actor=request.user,
            subject=participant,
            kind="collab_invite",
            app_key="collab",
            target=f"collab:deal?id={deal.id}"
        )
```

#### 6. **collab_accept** — When user accepts collaboration
**File**: `apps/economy/collab.py`  
**Location**: `CollabDetailView` (search for status update to "accepted")  
**Code**:
```python
# After deal.status = "accepted"
for participant in deal.participants:
    if participant != request.user:
        engagement.record_activity_event(
            actor=request.user,
            subject=participant,
            kind="collab_accept",
            app_key="collab",
            target=f"collab:deal?id={deal.id}"
        )
```

#### 7. **collab_complete** — When collaboration is finished
**File**: `apps/economy/collab.py`  
**Location**: `CollabReleaseView` (when deal is released/completed)  
**Code**:
```python
# After deal.status = "released"
for participant in deal.participants:
    engagement.record_activity_event(
        actor=request.user,
        subject=participant,
        kind="collab_complete",
        app_key="collab",
        target=f"collab:deal?id={deal.id}"
    )
```

#### 8. **battle_invite** — When user invites to battle
**File**: `apps/economy/battlez.py`  
**Location**: `BattleChallengeView.post()` (when battle is created)  
**Code**:
```python
# After Battle.objects.create()
engagement.record_activity_event(
    actor=request.user,
    subject=opponent,  # The challenged user
    kind="battle_invite",
    app_key="battlez",
    target=f"battlez:battle?id={battle.id}"
)
```

#### 9. **battle_enter** — When user joins a battle
**File**: `apps/economy/battlez.py`  
**Location**: `BattleEnterView.post()` (when battle entry is created)  
**Code**:
```python
# After BattleEntry.objects.create() for the opponent
engagement.record_activity_event(
    actor=request.user,
    subject=battle.creator,  # Notify the battle's creator
    kind="battle_enter",
    app_key="battlez",
    target=f"battlez:battle?id={battle.id}"
)
```

#### 10. **battle_win** — When user wins a battle
**File**: `apps/economy/battlez.py`  
**Location**: `BattleSettleView.post()` (when battle result is recorded)  
**Code**:
```python
# After winner is determined
if winner:
    for opponent in battle.opponents.exclude(id=winner.id):
        engagement.record_activity_event(
            actor=winner,
            subject=opponent,
            kind="battle_win",
            app_key="battlez",
            target=f"battlez:battle?id={battle.id}"
        )
```

#### 11. **take_score** — When user's take is coached/scored
**File**: `apps/economy/vocalcoach.py`  
**Location**: `SingZCoachView.post()` (after coaching completes)  
**Code**:
```python
# After take is scored, notify the uploader's followers (optional)
from . import engagement
engagement.record_activity_event(
    actor=coach_user,  # Or system user for AI coaching
    subject=take_owner,
    kind="take_score",
    app_key=instrument,  # "singz", "rapz", etc.
    target=f"{instrument}:coach?id={upload.id}"
)
```
**Note**: Only record if the score is good (>60 or >85) to avoid noise.

#### 12. **profile_view** — When user views another's profile
**File**: `apps/economy/social.py`  
**Location**: `MemberProfileView` or `PublicProfileView`  
**Code**:
```python
# In get() method, track profile views (optional — can be noisy)
# Only record if not viewing own profile
if target_user.id != request.user.id:
    engagement.record_activity_event(
        actor=request.user,
        subject=target_user,
        kind="profile_view",
        app_key="social",
        target="social:profile?username=" + target_user.username
    )
```
**Note**: This may generate a lot of events. Consider throttling or only recording for Premium users.

---

## Implementation Pattern

For each trigger point:

1. **Import the engagement module** at the top of the file:
   ```python
   from . import engagement
   ```

2. **Call record_activity_event after the action succeeds**:
   ```python
   engagement.record_activity_event(
       actor=request.user,           # Who did the action
       subject=target_user,          # Who receives the notification
       kind="<event_kind>",          # One of the 12 kinds above
       app_key="<app_name>",         # singz, rapz, postz, collab, battlez, social
       target="<app>:<screen>?params"  # Navigation target for the frontend
   )
   ```

3. **Test the implementation** by checking:
   - Activity events are created in the database
   - Correct actor and subject are set
   - app_key and target enable cross-pollination navigation
   - Events don't appear for self-actions (actor == subject)

---

## Frontend Integration

Once backend events are recorded, the frontend needs to:

1. **Fetch activity feed**: `GET /api/economy/activity-feed/my_feed/`
2. **Display events** with actor username and event description
3. **Navigate to source** using `app_key` + `target` via `goToSpot()`
4. **Mark as read**: `POST /api/economy/activity-feed/mark_read/`

Example response:
```json
{
  "events": [
    {
      "id": 123,
      "actor": {"id": 1, "username": "alice"},
      "kind": "follow",
      "kind_display": "Started following",
      "app_key": "social",
      "target": "social:profile?username=alice",
      "created_at": "2026-09-23T15:30:00Z",
      "read": false
    }
  ],
  "unread_count": 5,
  "offset": 0,
  "limit": 50
}
```

---

## Summary

- ✅ **Infrastructure**: Models, helpers, API views, serializers — all implemented and tested
- 📋 **Trigger points**: 12 specific locations identified for event recording
- 🔄 **Next steps**: Add `record_activity_event()` calls at each trigger point
- 🎨 **Frontend**: Display activity feed, enable navigation, mark events as read

Total work: ~2 hours to wire all 12 trigger points and test end-to-end.
