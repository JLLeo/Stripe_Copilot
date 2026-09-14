"""
read_attachment — a long customer message, read in pieces.

A message over the attachment threshold never enters working memory whole:
it is stored as an Attachment and a short stub with its id, size and opening
takes its place (ADR 0006). The model reads what it needs by offset. A piece
is plain text under a one-line header, so a cap that shortens it leaves the
text readable, and an attachment can only be read from the session it came
from — the lookup is by id and session, so another session's cannot be named.
"""

from __future__ import annotations

from typing import Any

from app import database
from app.harness.tools import Tool, ToolContext, ToolRegistry, ToolResult

DEFAULT_PIECE_CHARS = 4000
HEADER_ROOM_CHARS = 200  # kept free under the result cap so the header and the text always fit together


def make_read_attachment(result_cap_chars: int):
    max_piece = max(500, result_cap_chars - HEADER_ROOM_CHARS)

    def read_attachment(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        try:
            attachment_id = int(args.get("id"))  # type: ignore[arg-type]
            offset = max(0, int(args.get("offset") or 0))
            limit = int(args.get("limit") or DEFAULT_PIECE_CHARS)
        except (TypeError, ValueError):
            return ToolResult.error("read_attachment needs a numeric id, and numeric offset and limit if given.")
        limit = max(1, min(limit, max_piece))
        attachment = database.get_attachment(attachment_id, ctx.session_id)
        if attachment is None:
            return ToolResult.error(f"No attachment {attachment_id} in this conversation. The customer's stub names the id to use.")
        content: str = attachment["content"]
        piece = content[offset:offset + limit]
        end = offset + len(piece)
        next_offset = end if end < len(content) else None
        header = (
            f"[attachment {attachment_id}: characters {offset:,}–{end:,} of {len(content):,}; "
            f"next offset {next_offset if next_offset is not None else 'none — end of attachment'}]"
        )
        return ToolResult(content=header + "\n" + piece)

    return read_attachment


def register(registry: ToolRegistry, *, result_cap_chars: int) -> None:
    registry.register(Tool(
        name="read_attachment",
        description=(
            "Read part of a long message the customer sent, which was kept as an attachment instead of being "
            "placed in the conversation. Give the id from the customer's stub, an offset, and how many characters "
            f"to read (default {DEFAULT_PIECE_CHARS}). Read the pieces you need before answering; the header of each "
            "piece tells you the next offset."
        ),
        parameters={
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "The attachment id named in the customer's message stub."},
                "offset": {"type": "integer", "minimum": 0, "description": "Character offset to start from (default 0)."},
                "limit": {"type": "integer", "minimum": 1, "description": f"Characters to read (default {DEFAULT_PIECE_CHARS}; large values are clipped)."},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        run=make_read_attachment(result_cap_chars),
    ))
