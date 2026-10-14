"""Helpers for locating and inspecting House of Commons Hansard XML.

Sprint 0 only *describes* the XML; parsing into models comes in Sprint 1,
once we have seen the real structure.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import requests
from defusedxml import ElementTree as ET

BASE_URL = "https://www.ourcommons.ca/Content/House"
LANG_CODES = {"en": "E", "fr": "F"}


def sitting_url(parliament: int, session: int, sitting: int, lang: str = "en") -> str:
    """Build the documented Hansard XML URL, e.g. .../House/441/Debates/001/HAN001-E.XML.

    The French pattern (-F.XML) is not documented; inspect_sitting tests it.
    """
    if lang not in LANG_CODES:
        raise ValueError(f"lang must be one of {sorted(LANG_CODES)}, got {lang!r}")
    num = f"{sitting:03d}"
    return f"{BASE_URL}/{parliament}{session}/Debates/{num}/HAN{num}-{LANG_CODES[lang]}.XML"


RETRY_STATUSES = {429, 500, 502, 503, 504}


def fetch(
    url: str, user_agent: str, timeout: int = 60, attempts: int = 4, backoff: float = 2.0
) -> bytes:
    """GET with retries on dropped connections, timeouts and temporary server errors
    (waits 2, 4, 8 s). A 404 is final and raised at once."""
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, headers={"User-Agent": user_agent}, timeout=timeout)
            if response.status_code in RETRY_STATUSES and attempt < attempts:
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            response.raise_for_status()
            return response.content
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status is None or status in RETRY_STATUSES
            if not retryable or attempt == attempts:
                raise
            time.sleep(backoff * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


def local_name(tag: str) -> str:
    """Drop any XML namespace: '{ns}Tag' -> 'Tag'."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else str(tag)


@dataclass
class StructureSummary:
    root_tag: str
    root_attrib: dict[str, str]
    element_count: int
    path_counts: Counter = field(default_factory=Counter)
    attributes: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    attribute_samples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    text_samples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def render(self, max_paths: int = 400) -> str:
        lines = [
            f"Root element : {self.root_tag}",
            f"Root attrs   : {self.root_attrib or '-'}",
            f"Elements     : {self.element_count}",
            f"Distinct paths: {len(self.path_counts)}",
            "",
            "== Element paths (count) ==",
        ]
        for i, (path, count) in enumerate(self.path_counts.items()):
            if i >= max_paths:
                lines.append(f"... {len(self.path_counts) - max_paths} more paths not shown")
                break
            lines.append(f"{count:>6}  {path}")
        lines += ["", "== Attributes by element (times seen) =="]
        for tag in sorted(self.attributes):
            attrs = ", ".join(f"{a}({n})" for a, n in self.attributes[tag].most_common())
            lines.append(f"{tag}: {attrs}")
        lines += ["", "== Attribute value samples =="]
        for key in sorted(self.attribute_samples):
            lines.append(f"{key}: {self.attribute_samples[key]}")
        lines += ["", "== Text samples (first few per path) =="]
        for path, samples in self.text_samples.items():
            lines.append(path)
            for s in samples:
                lines.append(f"    | {s}")
        return "\n".join(lines)


def summarize(xml_bytes: bytes, samples: int = 3, sample_chars: int = 160) -> StructureSummary:
    """Walk the whole tree and record which paths, attributes and texts occur."""
    root = ET.fromstring(xml_bytes)
    summary = StructureSummary(
        root_tag=local_name(root.tag), root_attrib=dict(root.attrib), element_count=0
    )

    stack = [(root, "")]
    while stack:
        el, parent_path = stack.pop()
        tag = local_name(el.tag)
        path = f"{parent_path}/{tag}"
        summary.element_count += 1
        summary.path_counts[path] += 1

        for name, value in el.attrib.items():
            name = local_name(name)
            summary.attributes[tag][name] += 1
            key = f"{tag}@{name}"
            seen = summary.attribute_samples[key]
            if len(seen) < samples and value not in seen:
                seen.append(value[:sample_chars])

        text = " ".join((el.text or "").split())
        if text and len(summary.text_samples[path]) < samples:
            summary.text_samples[path].append(text[:sample_chars])

        # push children reversed so document order is preserved when popping
        for child in reversed(list(el)):
            stack.append((child, path))

    return summary
