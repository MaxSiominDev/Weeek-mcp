from __future__ import annotations


class WeeekError(Exception):
    pass


class SessionExpired(WeeekError):
    def __init__(self) -> None:
        super().__init__(
            "The stored Weeek browser session is no longer valid, and nothing can "
            "be read without one.\n"
            "Run `weeek-mcp login --cookie` and paste a fresh 'Cookie:' request "
            "header from DevTools -> Network -> any request to api.weeek.net.\n"
            "Copy the whole line: the remember_app_* cookie beside the session is "
            "what lets it renew itself instead of lapsing again in two hours."
        )


class TaskNotFound(WeeekError):
    def __init__(self, task_id: int) -> None:
        super().__init__(
            f"Weeek has no task {task_id} visible to this session. Check the link, "
            "and that you are a member of the workspace the task lives in."
        )


class ApiError(WeeekError):
    def __init__(self, status: int, code: int | None, message: str) -> None:
        self.status, self.code, self.message = status, code, message
        super().__init__(f"Weeek API error (HTTP {status}, code {code}): {message}")


class UnexpectedResponse(WeeekError):
    def __init__(self, status: int, content_type: str, url: str) -> None:
        super().__init__(
            f"Weeek returned {content_type or 'an unknown content type'} rather than "
            f"JSON (HTTP {status}) for {url}. This usually means the endpoint moved."
        )
