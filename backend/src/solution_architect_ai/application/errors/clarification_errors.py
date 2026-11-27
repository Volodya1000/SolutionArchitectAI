from solution_architect_ai.application.errors.chat_errors import ChatError, Conflict


class ClarificationConflict(Conflict):
    pass


class PermissionDenied(ChatError):
    pass
