"""DisabilitieZ — accessibility through disability declarations.

A member declares disabilities from a medical source (CDC, WHO, ICD-11) so the
platform can auto-suggest accessibility features and filter for community. Not
a diagnosis, not a measurement — a DECLARATION of what a member wants the app
to know about them.

Every disability leads to feature suggestions:
- Wheelchair → seated-only exercise mode in BodieZ (auto-enabled with explanation)
- Deaf/Hard of hearing → captions toggle, sound-off defaults, visual feedback
- Blind/Low vision → contrast/font size controls, screen reader support
- Mobility issues → seated/lying exercises, grip-alternative equipment
- Chronic pain → low-impact exercise filters, rest tracking in BodieZ
- ADHD → focus timers, simplification of complex screens
- Autism → sensory settings (motion, animations), communication clarity options
- Depression/Anxiety → motivational tone options, pressure-free interfaces

Sourced from:
- CDC (https://www.cdc.gov/ncbddd/disability-and-health/disability-types.html)
- WHO ICD-11 Mental, Behavioral or Neurodevelopmental Disorders
- FDA Accessibility guidance
"""

# Disability types sourced from CDC, WHO, and medical literature.
# Key = database value, displayed name = what members see.
# Grouped by category for clarity in the UI.
DISABILITIES = {
    # Mobility & Physical
    "wheelchair": ("Wheelchair user", "Movement and mobility"),
    "mobility_limited": ("Limited mobility", "Movement and mobility"),
    "chronic_pain": ("Chronic pain", "Movement and mobility"),
    "arthritis": ("Arthritis", "Movement and mobility"),
    "paralysis": ("Paralysis", "Movement and mobility"),

    # Sensory
    "deaf": ("Deaf", "Hearing and communication"),
    "hard_of_hearing": ("Hard of hearing", "Hearing and communication"),
    "blind": ("Blind", "Vision and sight"),
    "low_vision": ("Low vision", "Vision and sight"),
    "color_blind": ("Color blind", "Vision and sight"),

    # Neurological
    "adhd": ("ADHD", "Attention and focus"),
    "autism": ("Autism spectrum", "Sensory and social"),
    "dyslexia": ("Dyslexia", "Learning and reading"),
    "dyscalculia": ("Dyscalculia", "Learning and math"),
    "stroke": ("Stroke recovery", "Neurological"),
    "tbi": ("Traumatic brain injury", "Neurological"),
    "epilepsy": ("Epilepsy", "Neurological"),

    # Mental Health
    "depression": ("Depression", "Mental health"),
    "anxiety": ("Anxiety disorder", "Mental health"),
    "bipolar": ("Bipolar disorder", "Mental health"),
    "ptsd": ("PTSD", "Mental health"),
    "ocd": ("OCD", "Mental health"),

    # Other
    "fatigue": ("Chronic fatigue", "Energy and endurance"),
    "speech": ("Speech impediment", "Communication"),
    "intellectual": ("Intellectual disability", "Cognitive"),
}

# Accessibility features auto-enabled (with explanation) when these
# disabilities are declared. Map disability key → {feature: {why, default_val}}.
ACCESSIBILITY_TRIGGERS = {
    "wheelchair": {
        "seated_only_mode": {
            "label": "Seated-only exercise mode",
            "why": "Filter BodieZ exercises to seated and lying positions, " +
                   "skipping standing exercises that aren't adapted for wheelchair users. " +
                   "You can customize this anytime.",
            "default": True,
        }
    },
    "mobility_limited": {
        "seated_only_mode": {
            "label": "Seated-only exercise mode",
            "why": "BodieZ exercises are filtered to seated and lying positions by default. " +
                   "Turn this off anytime to see all exercises.",
            "default": True,
        }
    },
    "blind": {
        "high_contrast_mode": {
            "label": "High contrast mode",
            "why": "Improves text readability with bold colors and strong contrast.",
            "default": True,
        },
        "larger_text": {
            "label": "Larger text by default",
            "why": "Increases base font size across the app.",
            "default": True,
        }
    },
    "low_vision": {
        "high_contrast_mode": {
            "label": "High contrast mode",
            "why": "Improves text readability with enhanced color contrast.",
            "default": True,
        },
        "larger_text": {
            "label": "Larger text",
            "why": "Increases font size for easier reading.",
            "default": True,
        }
    },
    "deaf": {
        "always_captions": {
            "label": "Always show captions",
            "why": "Video content is captioned for deaf and hard-of-hearing members.",
            "default": True,
        },
        "visual_feedback": {
            "label": "Visual notifications (instead of sound)",
            "why": "Sound alerts are replaced with visual cues (flashes, color changes).",
            "default": True,
        }
    },
    "hard_of_hearing": {
        "visual_feedback": {
            "label": "Visual notifications (in addition to sound)",
            "why": "Sound alerts are reinforced with visual cues for clarity.",
            "default": True,
        }
    },
    "adhd": {
        "focus_mode": {
            "label": "Focus mode (reduce distractions)",
            "why": "Hide non-essential UI elements and notifications. " +
                   "Helps maintain focus on the task at hand.",
            "default": False,  # Optional, not auto-enabled
        }
    },
    "autism": {
        "reduce_animations": {
            "label": "Reduce animations and motion",
            "why": "Disables or slows animations that may be visually overwhelming.",
            "default": True,
        },
        "sensory_friendly": {
            "label": "Sensory-friendly mode",
            "why": "Softens colors, reduces flashing, minimizes sudden changes.",
            "default": False,
        }
    },
}

def apply_accessibility_features(profile, disabilities):
    """Auto-apply accessibility features based on declared disabilities.

    Called when a member declares disabilities. Updates
    accessibility_preferences with suggested features. Members can
    customize after. Returns the updated preferences dict.
    """
    prefs = dict(profile.accessibility_preferences)  # Start with existing prefs

    for disability in disabilities:
        if disability in ACCESSIBILITY_TRIGGERS:
            triggers = ACCESSIBILITY_TRIGGERS[disability]
            for feature, config in triggers.items():
                # Only set if not already customized (preserve user choice)
                if feature not in prefs:
                    prefs[feature] = {
                        "enabled": config.get("default", False),
                        "label": config["label"],
                        "why": config["why"],
                        "set_by": disability,  # Track which disability triggered it
                    }

    return prefs


def explain_accessibility_feature(feature_key):
    """Get the explanation for why an accessibility feature is enabled.

    Returns {label, why, recommended_for} or None if not found.
    """
    for disability, features in ACCESSIBILITY_TRIGGERS.items():
        if feature_key in features:
            config = features[feature_key]
            return {
                "label": config["label"],
                "why": config["why"],
                "recommended_for": DISABILITIES.get(disability, ("", ""))[0],
            }
    return None
