# LLM RPG Demo Engine

This repository contains a very minimal proof‑of‑concept backend for the
`LLM 文字 RPG` engine described in the project planning documents.  The
implementation uses [FastAPI](https://fastapi.tiangolo.com/) to expose a few
JSON endpoints and keeps all game state in memory.  It does **not** call
any large language models and instead generates narrative output using
simple rule‑based heuristics.  It also does not persist data to a real
database.  The purpose of this demo is to exercise the core loop of
creating a session, handling player input, updating world state and
returning a narrative response.

## Project structure

```
llm_rpg_engine/
├── backend/
│   └── app.py      # FastAPI application with session handling and turn logic
└── README.md        # this file
```

You can extend the project by adding a real database, replacing the
heuristic narrative generator with calls to your preferred LLM and
building a rich front‑end client.

## Requirements

The backend depends on packages that should already be installed in
OpenAI's development environment:

* Python 3.8+
* [FastAPI](https://fastapi.tiangolo.com/)
* [Uvicorn](https://www.uvicorn.org/)

If these packages are not available on your machine you can install
them with `pip install fastapi uvicorn`.

## Running the server

```
cd llm_rpg_engine/backend
uvicorn app:app --reload --port 8000
```

This starts the development server on port 8000.  You can then test
the API using `curl` or any HTTP client.

## Endpoints

* `POST /saves` – Create a new save slot and return the session identifier.
* `GET /saves` – List existing session identifiers.
* `GET /sessions/{session_id}/snapshot` – Return the current player state.
* `POST /sessions/{session_id}/turn` – Advance the game by one turn.  The
  request body should be JSON like `{ "action": "观察四周" }`.  The
  response includes the narrative text, a list of recommended actions and
  the updated player state.
* `GET /debug/sessions/{session_id}/logs` – Return a list of raw event logs
  recorded during the session.  Useful for debugging.

## Caveats

This demo intentionally omits many features of a production‐ready game
engine.  Notably:

* **Persistence**: All game state is stored in memory.  Restarting the
  server will reset everything.  The planning documents recommend
  PostgreSQL for persistent storage and Redis for caching.
* **Narrative quality**: The narrative responses are very simple.  In the
  full project you should call a large language model with the current
  context and NPC memories to generate rich descriptions and dialogue.
* **Security**: There is no authentication or input sanitisation.  A
  secure version would require user accounts and proper validation.
* **Front‑end**: There is no front‑end included in this demo.  The
  planning documents recommend building a Next.js client to interact
  with the API.

Nevertheless, this code demonstrates the core loop and provides a
foundation you can build upon when you are ready to implement the full
system.