# Project: Second Brain

## Why pgvector instead of a standalone vector database

Wanted one fewer moving part running permanently on an 8GB machine.
PostgreSQL was already a known quantity, and pgvector turns it into a
perfectly adequate vector store for a personal-scale knowledge base -
nowhere near the point where a dedicated vector database would earn its
keep.

## Why the backend stays native, not Dockerized

Docker Desktop's own VM already costs real RAM on this machine. Adding the
backend into a container on top of that would be paying the virtualization
tax twice for no real benefit at this scale - native Python talking to a
containerized-only database is a fine middle ground.

## Open question

Whether the heuristic query router (keyword-marker based) will hold up once
there's a real mix of question types being asked day to day, or whether it
should move to a small classifier sooner rather than later.
