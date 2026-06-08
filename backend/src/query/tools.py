# src/query/tools.py

TOOLS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Search podcast transcript content for specific topics, opinions, or facts. "
                "Use this when the user asks what was said about something, what a speaker "
                "thinks about a topic, or wants to find a specific moment in an episode. "
                "Do not use for greetings, clarifications, or questions answerable from "
                "the conversation history alone. "
                "If previous search results already contain sufficient information to answer "
                "the question, do not search again — synthesize from what you have."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query. Write this as a descriptive phrase, not a question — e.g. 'Marcus views on consciousness' not 'What does Marcus think about consciousness?'",
                    },
                    "speaker_name": {
                        "type": "string",
                        "description": "Filter results to a specific speaker by display name. Optional.",
                    },
                    "episode_id": {
                        "type": "string",
                        "description": "Filter results to a specific episode UUID. Optional.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return. Defaults to 5.",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_episode_context",
            "description": (
                "Retrieve the transcript excerpt surrounding a specific timestamp in an episode. "
                "Use this when the user wants to explore a specific moment in more depth, or when "
                "a prior search result surfaced a citation the user wants to expand on."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "episode_id": {
                        "type": "string",
                        "description": "UUID of the episode.",
                    },
                    "timestamp_ms": {
                        "type": "integer",
                        "description": "Timestamp in milliseconds to retrieve context around.",
                    },
                    "padding_ms": {
                        "type": "integer",
                        "description": "Milliseconds of context to include before and after the timestamp. Defaults to 30000 (30 seconds).",
                        "default": 30000,
                    },
                },
                "required": ["episode_id", "timestamp_ms"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_speaker_profile",
            "description": (
                "Get information about a speaker across the knowledge base: which episodes "
                "they appear in and their speaking time. Use when the user asks about a "
                "specific person rather than a specific topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "speaker_name": {
                        "type": "string",
                        "description": "Display name of the speaker to look up.",
                    },
                },
                "required": ["speaker_name"],
            },
        },
    },
]