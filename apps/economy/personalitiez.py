from django.db import transaction
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import PersonalityResult, Wallet
from .catalog import ENERGY_COST_BASIC_TEST, PROMPT_COST_DETAILED_TEST


MBTI_TYPES = {
    "ISTJ": {"name": "The Logistician", "emoji": "📋", "color": "#4A5568"},
    "ISFJ": {"name": "The Defender", "emoji": "🛡️", "color": "#5A6C7D"},
    "INFJ": {"name": "The Advocate", "emoji": "💭", "color": "#667B8F"},
    "INTJ": {"name": "The Architect", "emoji": "🏗️", "color": "#718AA1"},
    "ISTP": {"name": "The Virtuoso", "emoji": "🔧", "color": "#6B7D91"},
    "ISFP": {"name": "The Adventurer", "emoji": "🎨", "color": "#7D8FA3"},
    "INFP": {"name": "The Mediator", "emoji": "🌟", "color": "#8FA1B5"},
    "INTP": {"name": "The Logician", "emoji": "🧠", "color": "#A1B3C7"},
    "ESTP": {"name": "The Entrepreneur", "emoji": "⚡", "color": "#FF9500"},
    "ESFP": {"name": "The Entertainer", "emoji": "🎪", "color": "#FFB000"},
    "ENFP": {"name": "The Campaigner", "emoji": "🚀", "color": "#FFC700"},
    "ENTP": {"name": "The Debater", "emoji": "💡", "color": "#FFD700"},
    "ESTJ": {"name": "The Executive", "emoji": "👔", "color": "#DC2626"},
    "ESFJ": {"name": "The Consul", "emoji": "👥", "color": "#EF4444"},
    "ENFJ": {"name": "The Protagonist", "emoji": "🎭", "color": "#F87171"},
    "ENTJ": {"name": "The Commander", "emoji": "👑", "color": "#FCA5A5"},
}

BASIC_TEST_QUESTIONS = [
    {
        "question": "You tend to focus on:",
        "answers": [
            {"text": "Concrete reality and present facts (S)", "type": "S"},
            {"text": "Possibilities and future potential (N)", "type": "N"},
        ]
    },
    {
        "question": "When making decisions, you rely more on:",
        "answers": [
            {"text": "Logic and objective analysis (T)", "type": "T"},
            {"text": "Personal values and how others feel (F)", "type": "F"},
        ]
    },
    {
        "question": "You are more:",
        "answers": [
            {"text": "Outgoing and energized by people (E)", "type": "E"},
            {"text": "Reserved and energized by quiet time (I)", "type": "I"},
        ]
    },
    {
        "question": "You prefer to:",
        "answers": [
            {"text": "Plan ahead and organize (J)", "type": "J"},
            {"text": "Adapt and keep your options open (P)", "type": "P"},
        ]
    },
]

DETAILED_TEST_QUESTIONS = [
    {
        "question": "You find it easy to create a new circle of friends.",
        "dimension": "E",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
    {
        "question": "You are drawn to abstract and theoretical ideas.",
        "dimension": "N",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
    {
        "question": "You tend to prioritize personal harmony over objectivity.",
        "dimension": "F",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
    {
        "question": "You prefer a structured and organized work environment.",
        "dimension": "J",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
    {
        "question": "You enjoy being the center of attention.",
        "dimension": "E",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
    {
        "question": "You focus on practical, real-world applications.",
        "dimension": "S",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
    {
        "question": "You analyze situations objectively and logically.",
        "dimension": "T",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
    {
        "question": "You prefer to make plans well in advance.",
        "dimension": "J",
        "answers": [
            {"text": "Strongly disagree", "score": -2},
            {"text": "Disagree", "score": -1},
            {"text": "Neutral", "score": 0},
            {"text": "Agree", "score": 1},
            {"text": "Strongly agree", "score": 2},
        ]
    },
]


def calculate_mbti_type(answers):
    """Calculate MBTI type from basic test answers."""
    type_str = ""
    for letter in ['E', 'S', 'T', 'J']:
        if letter in answers:
            type_str += letter
        elif letter == 'E' and 'I' in answers:
            type_str += 'I'
        elif letter == 'S' and 'N' in answers:
            type_str += 'N'
        elif letter == 'T' and 'F' in answers:
            type_str += 'F'
        elif letter == 'J' and 'P' in answers:
            type_str += 'P'
    return type_str


def calculate_detailed_mbti(scores):
    """Calculate MBTI type from detailed test scores."""
    type_str = ""
    dimensions = {
        'E': 0,  # Extraversion vs Introversion
        'N': 0,  # Intuition vs Sensing
        'T': 0,  # Thinking vs Feeling
        'J': 0,  # Judging vs Perceiving
    }

    for dim, score in scores.items():
        if dim in dimensions:
            dimensions[dim] = score

    # Determine type based on positive/negative scores
    type_str = ""
    type_str += 'E' if dimensions['E'] >= 0 else 'I'
    type_str += 'N' if dimensions['N'] >= 0 else 'S'
    type_str += 'T' if dimensions['T'] >= 0 else 'F'
    type_str += 'J' if dimensions['J'] >= 0 else 'P'

    return type_str


class PersonalityBasicTestView(APIView):
    """GET: Retrieve basic MBTI test questions
       POST: Submit basic test answers and calculate type
       Cost: −1 ⚡ (on successful completion)"""

    def get(self, request):
        """Get basic test questions."""
        return Response({
            "test_type": "basic",
            "questions": BASIC_TEST_QUESTIONS,
            "cost": {"energy": ENERGY_COST_BASIC_TEST, "emoji": "⚡"},
            "description": "Quick 4-question MBTI assessment"
        })

    @transaction.atomic
    def post(self, request):
        """Submit basic test and create personality result."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        answers = request.data.get("answers", [])

        # Validate answers
        if len(answers) != 4:
            return Response({"error": "All 4 questions must be answered"}, status=400)

        # Calculate MBTI type
        answer_types = [a.get("type") for a in answers]
        mbti_type = calculate_mbti_type(answer_types)

        if not mbti_type or len(mbti_type) != 4:
            return Response({"error": "Invalid answers"}, status=400)

        # Charge energy
        wallet = Wallet.objects.get(user=user)
        if wallet.energy < ENERGY_COST_BASIC_TEST:
            return Response(
                {"error": "Not enough energy", "needed": ENERGY_COST_BASIC_TEST, "have": wallet.energy},
                status=402
            )

        wallet.energy -= ENERGY_COST_BASIC_TEST
        wallet.save()

        # Save result
        result = PersonalityResult.objects.create(
            user=user,
            test_type="basic",
            mbti_type=mbti_type,
            answers=answers
        )

        return Response({
            "success": True,
            "mbti_type": mbti_type,
            "type_info": MBTI_TYPES[mbti_type],
            "cost_paid": {"energy": ENERGY_COST_BASIC_TEST},
            "result_id": result.id
        })


class PersonalityDetailedTestView(APIView):
    """GET: Retrieve detailed MBTI test questions
       POST: Submit detailed test answers and calculate type
       Cost: −2 🏷️ (on successful completion)"""

    def get(self, request):
        """Get detailed test questions."""
        return Response({
            "test_type": "detailed",
            "questions": DETAILED_TEST_QUESTIONS,
            "cost": {"prompts": PROMPT_COST_DETAILED_TEST, "emoji": "🏷️"},
            "description": "Comprehensive 8-question MBTI assessment with AI analysis"
        })

    @transaction.atomic
    def post(self, request):
        """Submit detailed test and create personality result."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        answers = request.data.get("answers", [])

        # Validate answers
        if len(answers) != 8:
            return Response({"error": "All 8 questions must be answered"}, status=400)

        # Calculate scores by dimension
        dimension_scores = {
            'E': 0, 'N': 0, 'T': 0, 'J': 0
        }

        for answer in answers:
            dim = answer.get("dimension")
            score = answer.get("score", 0)
            if dim in dimension_scores:
                dimension_scores[dim] += score

        # Calculate MBTI type
        mbti_type = calculate_detailed_mbti(dimension_scores)

        # Charge prompts
        wallet = Wallet.objects.get(user=user)
        if wallet.prompts < PROMPT_COST_DETAILED_TEST:
            return Response(
                {"error": "Not enough prompts", "needed": PROMPT_COST_DETAILED_TEST, "have": wallet.prompts},
                status=402
            )

        wallet.prompts -= PROMPT_COST_DETAILED_TEST
        wallet.save()

        # Save result
        result = PersonalityResult.objects.create(
            user=user,
            test_type="detailed",
            mbti_type=mbti_type,
            answers=answers,
            dimension_scores=dimension_scores
        )

        return Response({
            "success": True,
            "mbti_type": mbti_type,
            "type_info": MBTI_TYPES[mbti_type],
            "dimension_scores": dimension_scores,
            "cost_paid": {"prompts": PROMPT_COST_DETAILED_TEST},
            "result_id": result.id
        })


class PersonalityResultView(APIView):
    """GET: Retrieve user's personality result(s)"""

    def get(self, request):
        """Get user's latest personality results."""
        user = request.user
        if not user.is_authenticated:
            return Response({"error": "Not authenticated"}, status=401)

        test_type = request.query_params.get("type", "all")

        query = PersonalityResult.objects.filter(user=user).order_by("-created_at")
        if test_type != "all":
            query = query.filter(test_type=test_type)

        results = query[:5]

        return Response({
            "results": [
                {
                    "id": r.id,
                    "test_type": r.test_type,
                    "mbti_type": r.mbti_type,
                    "type_info": MBTI_TYPES.get(r.mbti_type),
                    "created_at": r.created_at,
                    "dimension_scores": r.dimension_scores,
                }
                for r in results
            ]
        })
