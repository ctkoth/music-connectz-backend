"""Image ConnectZ — what each kind of picture IS, so a member picks a use, not a prompt.

A profile picture and a desktop wallpaper are different jobs: one has to read as
a circle 56 pixels wide, the other has to leave room for icons across 16:9. Asking
a member to know that and type it is how a free-text box produces a square
wallpaper with the subject under the clock. So every kind declares its shape, the
brief the model is given for it, where it gets USED (the door after it is made),
and whether it may take the member's own photo as a likeness.

The screen renders this list and decides nothing; a kind added here is a new chip
without a client release. Styles and moods are closed lists for the same reason a
funnel kind is: a value the model was never briefed on is a value that drifts.

Two lines that are not soft:

* **A likeness is only ever your own.** `me` sends the member's photo to keep
  their face; it is offered only on the kinds that are about the member and needs
  them to confirm it is them. Anyone else's face goes through `inspiration`,
  which takes palette and mood and is told never to reproduce a person.
* **Words in a picture are attempted, not promised.** Image models misspell; the
  screen says so beside the title field rather than after somebody prints a
  flyer with their name wrong.
"""

KINDS = {
    "profile_pic": {
        "label": "Profile picture", "emoji": "🙂", "aspect": "1:1", "likeness": True,
        "use": "Your picture on ProfileZ, posts and messages — it shows as a small circle.",
        "brief": ("A profile picture: one subject, head and shoulders, centred, with a simple uncluttered "
                  "background, readable when shown as a small circle."),
        "door": "avatar"},
    "avatar": {
        "label": "Avatar", "emoji": "🧑‍🎤", "aspect": "1:1", "likeness": True,
        "use": "A stylised character of you — an illustrated stand-in instead of a photo.",
        "brief": ("A stylised avatar character, illustrated rather than photographic, centred, simple "
                  "background, readable small."),
        "door": "avatar"},
    "song_cover": {
        "label": "Song cover", "emoji": "🎵", "aspect": "1:1", "likeness": True, "words": True,
        "use": "Artwork for a single — PostZ, DistributeZ, Spotify, SoundCloud.",
        "brief": ("Square cover art for a single song. Bold, striking at thumbnail size, one clear focal "
                  "point."),
        "door": "post"},
    "album_cover": {
        "label": "Album / EP cover", "emoji": "💿", "aspect": "1:1", "likeness": True, "words": True,
        "use": "Artwork for an album or EP.",
        "brief": ("Square album cover art with a cohesive concept, rich detail that rewards a closer look, "
                  "and a strong silhouette at thumbnail size."),
        "door": "post"},
    "playlist_cover": {
        "label": "Playlist cover", "emoji": "📃", "aspect": "1:1", "words": True,
        "use": "A cover for a PlaylistZ or streaming playlist.",
        "brief": "Square playlist cover art that sums up a mood, graphic and simple.",
        "door": "post"},
    "header": {
        "label": "Profile header / banner", "emoji": "🏞️", "aspect": "21:9",
        "use": "The wide banner across the top of a profile, channel or page.",
        "brief": ("A very wide banner image. Keep the important detail in the middle band; the edges and "
                  "lower-left corner are often covered by a profile picture or cropped."),
        "door": "file"},
    "wallpaper_phone": {
        "label": "Phone wallpaper", "emoji": "📱", "aspect": "9:16",
        "use": "A lock-screen or home-screen background.",
        "brief": ("A tall phone wallpaper. Leave the top third calm for the clock and keep the centre clear "
                  "of busy detail where app icons sit."),
        "door": "file"},
    "wallpaper_desktop": {
        "label": "Desktop wallpaper", "emoji": "🖥️", "aspect": "16:9",
        "use": "A computer background.",
        "brief": "A widescreen desktop wallpaper with calm areas where icons and windows go.",
        "door": "file"},
    "thumbnail": {
        "label": "Video thumbnail", "emoji": "▶️", "aspect": "16:9", "likeness": True, "words": True,
        "use": "The still for a YouTube video, VideoZ or a DirectZ release.",
        "brief": ("A video thumbnail: high contrast, one big readable subject, expressive, legible at a "
                  "small size."),
        "door": "post"},
    "story": {
        "label": "Story / reel cover", "emoji": "🎬", "aspect": "9:16", "likeness": True, "words": True,
        "use": "A vertical cover for an Instagram or TikTok story or reel.",
        "brief": "A vertical story image with the subject in the middle and the top and bottom kept clear.",
        "door": "post"},
    "post_square": {
        "label": "Square post", "emoji": "🟪", "aspect": "1:1", "likeness": True, "words": True,
        "use": "A feed post for PostZ or Instagram.",
        "brief": "A square social post image, eye-catching in a scrolling feed.",
        "door": "post"},
    "post_portrait": {
        "label": "Portrait post", "emoji": "📐", "aspect": "4:5", "likeness": True, "words": True,
        "use": "A taller feed post, which takes more of the screen on Instagram.",
        "brief": "A portrait 4:5 social post image, eye-catching in a scrolling feed.",
        "door": "post"},
    "flyer": {
        "label": "Event flyer / poster", "emoji": "📣", "aspect": "3:4", "likeness": True, "words": True,
        "use": "A flyer for a show, release party or open mic — VenueZ, posts, print.",
        "brief": ("An event poster with a clear hierarchy: a strong image and room for a headline and the "
                  "event details."),
        "door": "post"},
    "merch": {
        "label": "Merch design", "emoji": "👕", "aspect": "1:1", "words": True,
        "use": "A graphic for a t-shirt, hoodie or sticker — MerchZ.",
        "brief": ("A standalone merch graphic on a plain, solid background so it can be cut out: bold "
                  "shapes, limited colours, works printed on fabric."),
        "door": "file"},
    "logo": {
        "label": "Artist logo / emblem", "emoji": "🔰", "aspect": "1:1", "words": True,
        "use": "A mark for your name or brand.",
        "brief": ("A simple logo mark on a plain background: clean, scalable shapes, readable small, no "
                  "photographic detail."),
        "door": "file"},
}

STYLES = {
    "photo": "Photo-real", "illustration": "Illustration", "anime": "Anime / manga", "render3d": "3D render",
    "neon": "Neon", "watercolor": "Watercolour", "oil": "Oil painting", "pixel": "Pixel art",
    "minimal": "Minimal / flat", "collage": "Collage", "vintage": "Vintage film", "graffiti": "Graffiti / street",
    "comic": "Comic book", "surreal": "Surreal", "y2k": "Y2K / chrome",
}
MOODS = {
    "dark": "Dark", "bright": "Bright", "dreamy": "Dreamy", "aggressive": "Aggressive", "calm": "Calm",
    "euphoric": "Euphoric", "melancholy": "Melancholy", "luxury": "Luxurious", "gritty": "Gritty",
    "romantic": "Romantic", "playful": "Playful", "epic": "Epic",
}

LIKENESS_NOTE = ("Your photo keeps your face in it. Only use a photo of yourself — "
                 "for anyone else's look, use Inspiration, which borrows style and never a person.")
WORDS_NOTE = "Image models often misspell words in a picture. Check any text before you post or print it."
TEXT_MAX = 60
COLOURS_MAX = 80

LIKENESS_WRAP = (
    "The attached photo is of the person this picture is for, and they asked for their own likeness. Keep their "
    "face recognisably theirs. Do not change their apparent age, skin tone, ethnicity or body shape. ")


def catalogue():
    """What GET hands the screen: every kind, style and mood, and the two notes."""
    return {
        "kinds": [{"key": k, **{f: v for f, v in d.items() if f != "brief"},
                   "likeness": bool(d.get("likeness")), "words": bool(d.get("words"))}
                  for k, d in KINDS.items()],
        "styles": [{"key": k, "label": v} for k, v in STYLES.items()],
        "moods": [{"key": k, "label": v} for k, v in MOODS.items()],
        "likeness_note": LIKENESS_NOTE, "words_note": WORDS_NOTE,
        "text_max": TEXT_MAX, "colours_max": COLOURS_MAX,
    }


def clean_options(data):
    """(kind, style, mood, colours, text) from a request — unknown values become blank,
    never a refusal, and the free text is capped."""
    kind = str(data.get("kind") or "")
    kind = kind if kind in KINDS else ""
    style = str(data.get("style") or "")
    mood = str(data.get("mood") or "")
    words_ok = bool(KINDS.get(kind, {}).get("words"))
    return (kind,
            style if style in STYLES else "",
            mood if mood in MOODS else "",
            " ".join(str(data.get("colours") or "").split())[:COLOURS_MAX],
            " ".join(str(data.get("text") or "").split())[:TEXT_MAX] if words_ok else "")


def build_prompt(prompt, kind="", style="", mood="", colours="", text=""):
    """The member's description, framed by what the kind needs. The description comes
    LAST so the member's words win any conflict with the framing."""
    k = KINDS.get(kind)
    bits = []
    if k:
        bits.append(k["brief"] + f" Compose it for a {k['aspect']} frame.")
    if style:
        bits.append(f"Style: {STYLES[style]}.")
    if mood:
        bits.append(f"Mood: {MOODS[mood]}.")
    if colours:
        bits.append(f"Colours: {colours}.")
    if text:
        bits.append(f'Include this text, spelled exactly: "{text}". No other words.')
    elif k:
        bits.append("No words, letters or logos in the picture.")
    bits.append("Original artwork only: no real brands, no copyrighted characters.")
    return " ".join(bits) + ("\nWhat it should show: " + prompt if prompt else "")
