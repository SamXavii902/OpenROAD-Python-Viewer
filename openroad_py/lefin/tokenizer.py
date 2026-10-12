"""Fast stream tokenizer for LEF and DEF files."""

import io
from typing import Generator, Union, Optional, List


def tokenize_stream(stream: io.TextIOBase, pos_holder: Optional[List[int]] = None) -> Generator[str, None, None]:
    """Yields whitespace-separated tokens from a stream, skipping '#' comments
    and preserving quoted strings. Tokens ending with ';' yield ';' as a separate token.
    Optionally tracks bytes read in pos_holder[0].
    """
    in_quote = False
    quote_chars = []

    for line in stream:
        if pos_holder is not None:
            pos_holder[0] += len(line) + 1
        # Strip trailing newline
        line = line.rstrip("\r\n")
        idx = 0
        n = len(line)

        while idx < n:
            ch = line[idx]

            if in_quote:
                quote_chars.append(ch)
                if ch == '"':
                    in_quote = False
                    yield "".join(quote_chars)
                    quote_chars = []
                idx += 1
                continue

            # Skip whitespace
            if ch.isspace():
                idx += 1
                continue

            # Comment starts with '#'
            if ch == "#":
                break

            # Quoted string starts
            if ch == '"':
                in_quote = True
                quote_chars = ['"']
                idx += 1
                continue

            # Semicolon
            if ch == ";":
                yield ";"
                idx += 1
                continue

            # Accumulate normal token
            start = idx
            while idx < n and not line[idx].isspace() and line[idx] not in ('"', "#", ";"):
                idx += 1
            yield line[start:idx]

            # If ended right at a semicolon
            if idx < n and line[idx] == ";":
                yield ";"
                idx += 1

    if quote_chars:
        yield "".join(quote_chars)


class TokenReader:
    """Helper for reading tokens with peek, expect, and conversion methods."""

    def __init__(self, token_gen: Generator[str, None, None], pos_holder: Optional[List[int]] = None):
        self._gen = token_gen
        self._pos_holder = pos_holder
        self._peeked = None
        self.token_count = 0

    def get_bytes_read(self) -> int:
        return self._pos_holder[0] if self._pos_holder else 0

    def next(self) -> str:
        self.token_count += 1
        if self._peeked is not None:
            token = self._peeked
            self._peeked = None
            return token
        return next(self._gen)

    def peek(self) -> str:
        if self._peeked is None:
            try:
                self._peeked = next(self._gen)
            except StopIteration:
                return ""
        return self._peeked

    def has_next(self) -> bool:
        return bool(self.peek())

    def expect(self, expected: str) -> None:
        tok = self.next()
        if tok.upper() != expected.upper():
            raise ValueError(f"Expected '{expected}', got '{tok}'")

    def read_until_semicolon(self) -> list[str]:
        tokens = []
        while self.has_next():
            tok = self.next()
            if tok == ";":
                break
            tokens.append(tok)
        return tokens

    def skip_until(self, end_keyword: str, end_name: str = "") -> None:
        """Skips tokens until END <name> ; is encountered."""
        while self.has_next():
            tok = self.next()
            if tok.upper() == end_keyword.upper():
                if end_name:
                    p = self.peek()
                    if p.upper() == end_name.upper():
                        self.next()
                        if self.peek() == ";":
                            self.next()
                        break
                else:
                    if self.peek() == ";":
                        self.next()
                    break
