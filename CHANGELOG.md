# Changelog

All notable changes are recorded here. This project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Independent architecture chats with PostgreSQL history, durable streamed
  answers, server cancellation and recovery after interruption.
- Light, Dark and System themes, persistent drafts, keyboard operation and
  responsive chat layout.
- Local Docker Compose runtime with fake LLM, LM Studio and optional vLLM
  profiles using an OpenAI-compatible API.
- Shared local and CI quality checks, pre-commit and pre-push hooks, and isolated
  integration/E2E checks that preserve the developer's active model and data.

### Fixed

- Incomplete answer markers remain attached to their original messages.
- Retrying an acknowledged command preserves a newer draft across navigation.
- SSE recovers after temporary server errors and slow history requests.
- Oversized messages retain their text and receive a useful validation message.

### Changed

- Separated application DTOs and errors, clarified transactional storage
  responsibilities, and strengthened Python typing across source, tests and tools.
- Reduced streaming database round trips while preserving partial-answer
  durability and cancellation ordering.
- Context selection accounts for system/template overhead and keeps dialog turns
  intact when trimming history.
- Container endpoints are configurable; PDF builds run only for publication
  inputs, while application quality runs once per PR update and on main.
