import re
from typing import List, AsyncIterator, Set


class SentenceChunker:
    """
    Sentence and clause boundary chunker for token-streaming TTS.
    Segments real-time streaming LLM tokens into natural, synthesizable clauses
    with sub-second Time-to-First-Audio (TTFA) while avoiding choppy single-word splits.
    """

    DEFAULT_ABBREVIATIONS: Set[str] = {
        "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.",
        "vs.", "etc.", "e.g.", "i.e.", "approx.", "st.", "no.",
        "dept.", "fig.", "al.", "inc.", "ltd.", "gen.", "col.",
        "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.",
        "sep.", "sept.", "oct.", "nov.", "dec.", "a.m.", "p.m.",
        "am.", "pm.",
    }

    def __init__(
        self,
        min_words: int = 4,
        clause_break_words: int = 8,
        abbreviations: Set[str] = None,
    ):
        self.min_words = min_words
        self.clause_break_words = clause_break_words
        self.abbreviations = abbreviations or set(self.DEFAULT_ABBREVIATIONS)
        self._buffer: str = ""

    def add_token(self, token: str) -> List[str]:
        """
        Feed an incoming token delta and return any ready sentence/clause chunks.
        """
        if not token:
            return []

        self._buffer += token
        return self._extract_ready_chunks()

    def _extract_ready_chunks(self) -> List[str]:
        ready_chunks: List[str] = []

        while True:
            split_idx = self._find_split_point(self._buffer)
            if split_idx is None:
                break

            candidate = self._buffer[:split_idx].strip()
            self._buffer = self._buffer[split_idx:].lstrip()

            if candidate:
                ready_chunks.append(candidate)

        return ready_chunks

    def _find_split_point(self, text: str) -> int | None:
        """
        Finds the earliest valid sentence or clause split point that satisfies
        minimum word constraints and avoids abbreviations/decimals.
        """
        # Primary punctuation patterns: . ! ? followed by space, or newline
        # Also supports clause breaks like ; or : when buffer is long enough
        pattern = re.compile(r'([.!?\n\r]+(?:\s+|$)|[;:]\s+)')

        for match in pattern.finditer(text):
            idx = match.end()
            candidate = text[:idx].strip()
            punct = match.group(1).strip()

            words = candidate.split()
            word_count = len(words)

            # Check if this period is part of a decimal number (e.g. 3.14)
            match_start = match.start(1)
            if punct == "." and match_start > 0 and match_start < len(text) - 1:
                before_char = text[match_start - 1]
                after_char = text[match_start + 1] if match_start + 1 < len(text) else ""
                if before_char.isdigit() and after_char.isdigit():
                    continue

            # Check if candidate ends with an abbreviation (e.g. "Dr.", "e.g.")
            if words:
                last_word = words[-1].lower().rstrip(",:;")
                if last_word in self.abbreviations:
                    continue

            # Check if candidate is ellipsis (...)
            if candidate.endswith("..."):
                continue

            # Check clause break conditions (; or :)
            if punct in (";", ":"):
                if word_count >= self.clause_break_words:
                    return idx
                continue

            # Sentence boundaries (. ! ? \n)
            # If newline break, allow shorter clause if at least 2 words
            if "\n" in match.group(1):
                if word_count >= 2:
                    return idx
            elif word_count >= self.min_words:
                return idx

        return None

    def flush(self) -> List[str]:
        """
        Flush and return any remaining text in the buffer.
        """
        remaining = self._buffer.strip()
        self._buffer = ""
        if remaining:
            return [remaining]
        return []

    async def chunk_stream(self, token_stream: AsyncIterator[str]) -> AsyncIterator[str]:
        """
        Consumes an asynchronous stream of token deltas and yields ready chunks.
        """
        async for delta in token_stream:
            for chunk in self.add_token(delta):
                yield chunk

        for trailing in self.flush():
            yield trailing
