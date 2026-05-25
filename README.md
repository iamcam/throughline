# Pod Knowledge Engine

If you ever wondered about the knowledge and information discussed in a podcast, this is your tool.


This project contains backend and frontend components for a podcast knowledge engine.

This engine ingests select podcast episodes, transcribes + diarizes speaker, and conversational RAG to serve as a topic-specific knowledgebase.

Backend/Frontend component details are available in the `frontend` and `backend` directory README files.

## General Approach

Project development is directed through thoughtful discussion with Claude Sonnet about code, architecture, and user-facing concerns like usability, expectations, and utility. The intent is a hybrid development approach - managing the product and code guidelines as a human while allowing the language model to pair program. While possible to allow a coding agent full control over decisions with only guiding input from a human (me), I've decided to take a more hands-on approach as both a learning exercise into new topics while using experience to guide and let the models shine where they do best.

This project is not vibe-coded. It's intentionally allowing tools to do what they are best at without surrendering knowledge, wisdom, and discernment... a bicycle for the mind.

The following files were developed in collaboration with Claude Sonnet 4.6. Architectural decisions, tradeoffs, and product direction were my decisions; the model contributed structure, detail, and implementation guidance.

* `ARCHITECTURE.md` - system design, protocols, dependencies, schema, API reference - the primary guide
* `IMPLEMENTATION_PLAN.md` - includes the sequential development phases.
* `FUTURE_SCOPE.md` - my thoughts around areas for improvement after the initial development milestone, post v1
* `OPERATIONS.md` - information about deployment, demo auth, hosting guides, etc.

...and of course, all subject to change.
