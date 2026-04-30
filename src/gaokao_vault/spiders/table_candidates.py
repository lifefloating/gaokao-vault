from __future__ import annotations


def candidate_tables(response, class_name: str, expected_headers: tuple[str, ...]):
    tables = response.css(f"table.{class_name}")
    candidates = tables if tables else response.css("table")
    return [table for table in candidates if _has_expected_header(table, expected_headers)]


def _has_expected_header(table, expected_headers: tuple[str, ...]) -> bool:
    for row in table.css("tr"):
        headers = [text for cell in row.css("th") if (text := _cell_text(cell))]
        if not headers:
            continue
        if any(_matches_header(header, expected_headers) for header in headers):
            return True
    return False


def _matches_header(header: str, expected_headers: tuple[str, ...]) -> bool:
    return any(expected in header for expected in expected_headers)


def _cell_text(cell) -> str:
    return "".join(part.strip() for part in cell.css("::text").getall() if part.strip())
