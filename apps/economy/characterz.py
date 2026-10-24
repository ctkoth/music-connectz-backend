"""CharacterZ: FaceZ with PersonalitieZ, and a voice.

Every member can make characters; the tier says how many (CHARACTER_LIMIT, a
recommendation and Corey's to move). The voice reuses VoiceZ's cleaner and data block,
so a character's dialogue in MangaZ is written from exactly the description a VoiceZ
voice is, framed as data and never as instructions.

The look is a drawing or the member's own face. A FaceZ face tagged as another member,
or anyone else's upload, is refused; any look needs the member's attestation.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import personalityz, voicez
from .media import stable_media_url
from .models import Character, Face, Upload, membership_for

CHARACTER_LIMIT = {"free": 3, "premium": 10, "statz": 50, "debug": 50}
LOOKS_MAX = 300
LIKENESS = ("A character's look is a drawing, or your own face — never another real person's. "
            "Putting a real person into AI-made pages without their say-so is not something this does.")


def limit_for(user):
    return CHARACTER_LIMIT.get(membership_for(user).tier, CHARACTER_LIMIT["free"])


def voice_of(c):
    return voicez.VoiceSpec.from_fields({"name": c.name, "bio": c.bio, "personality": c.personality,
                                         "spec": c.spec, "sample": c.sample})


def prompt_block(c):
    """How a character is described to a model writing their lines: the VoiceZ data
    block (framed as data) plus the declared personality and their look in words."""
    v = voice_of(c)
    bits = [voicez.data_block(v, sample_chars=400, bio_chars=600)]
    p = voicez.personality_line(c.personality)
    if p:
        bits.append(p)
    bits.append("Tone: " + voicez.summary(v))
    if c.looks:
        bits.append("Looks (for drawing them consistently): " + voicez._defang(c.looks))
    return f"CHARACTER {voicez._defang(c.name)}:\n" + "\n".join(bits)


def character_dict(c, request=None):
    img = ""
    if c.upload_id:
        img = stable_media_url(c.upload, request) or ""
    elif c.face_id and c.face.image:
        try:
            img = request.build_absolute_uri(c.face.image.url) if request else c.face.image.url
        except Exception:
            img = ""
    return {"id": c.id, "name": c.name, "image": img, "face_id": c.face_id, "upload_id": c.upload_id,
            "looks": c.looks, "bio": c.bio, "personality": c.personality,
            "spec": {**voicez.DIAL_DEFAULTS, **(c.spec or {})}, "sample": c.sample,
            "voice_summary": voicez.summary(voice_of(c))}


def _look(request, data, cur=None):
    """(face, upload, error) for the look in this body, checked against the likeness rule."""
    face = cur.face if cur else None
    upload = cur.upload if cur else None
    if "face_id" in data:
        face = None
        if data.get("face_id") not in (None, ""):
            face = Face.objects.filter(pk=data.get("face_id"), owner=request.user).first()
            if not face:
                return None, None, "That face isn't one of yours."
            if face.tagged_id and face.tagged_id != request.user.id:
                return None, None, "That face is tagged as another member. " + LIKENESS
    if "upload_id" in data:
        upload = None
        if data.get("upload_id") not in (None, ""):
            upload = Upload.objects.filter(pk=data.get("upload_id"), user=request.user).first()
            if not upload or not (upload.content_type or "").startswith("image"):
                return None, None, "That isn't one of your images."
    if (face or upload) and not (data.get("look_attested") or (cur and cur.look_attested and
                                                                 "face_id" not in data and "upload_id" not in data)):
        return None, None, "Confirm the look is a drawing or your own face. " + LIKENESS
    return face, upload, ""


class CharactersView(APIView):
    """GET your characters and the rules; POST make one."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = Character.objects.filter(user=request.user).select_related("face", "upload")
        return Response({"characters": [character_dict(c, request) for c in rows],
                         "limit": limit_for(request.user), "tiers": CHARACTER_LIMIT,
                         "dials": voicez.dials_payload(), "personality": personalityz.AXES,
                         "likeness": LIKENESS})

    def post(self, request):
        if Character.objects.filter(user=request.user).count() >= limit_for(request.user):
            return Response({"detail": f"Your tier holds {limit_for(request.user)} characters — remove one, or "
                                       "upgrade in MembershipZ for more.", "limit": limit_for(request.user)},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            fields = voicez.clean_payload(request.data)
        except voicez.Invalid as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        face, upload, err = _look(request, request.data)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        c = Character.objects.create(user=request.user, face=face, upload=upload,
                                     look_attested=bool(face or upload),
                                     looks=voicez._clean(request.data.get("looks"))[:LOOKS_MAX], **fields)
        return Response(character_dict(c, request), status=status.HTTP_201_CREATED)


class CharacterDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get(self, request, pk):
        return Character.objects.filter(pk=pk, user=request.user).select_related("face", "upload").first()

    def patch(self, request, pk):
        c = self._get(request, pk)
        if not c:
            return Response({"detail": "Not your character."}, status=status.HTTP_404_NOT_FOUND)
        try:
            fields = voicez.clean_payload(request.data, current={"spec": c.spec})
        except voicez.Invalid as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        face, upload, err = _look(request, request.data, c)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        for k, v in fields.items():
            setattr(c, k, v)
        c.face, c.upload, c.look_attested = face, upload, bool(face or upload)
        if "looks" in request.data:
            c.looks = voicez._clean(request.data.get("looks"))[:LOOKS_MAX]
        c.save()
        return Response(character_dict(c, request))

    def delete(self, request, pk):
        c = self._get(request, pk)
        if not c:
            return Response({"detail": "Not your character."}, status=status.HTTP_404_NOT_FOUND)
        c.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
