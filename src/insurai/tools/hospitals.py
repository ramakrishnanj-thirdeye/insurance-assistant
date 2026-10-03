"""check_hospital (spec 05): network status and up to three Network alternatives (same city, specialty)."""

from typing import Any

from insurai.tools.base import fetch_all, fetch_one, tool
from insurai.tools.ids import not_found, validate_id
from insurai.tools.schemas import (
    AccessDenied,
    Disambiguation,
    HospitalCheck,
    HospitalSummary,
    Match,
    NotFound,
    ToolContext,
)
from insurai.tools.sources import sql_source

NETWORK = "Network"
MAX_ALTERNATIVES = 3
MAX_MATCHES = 10
_COLUMNS = "hospital_id, hospital_name, city, network_status, specialty"


@tool
def check_hospital(
    ctx: ToolContext, hospital_id: str | None = None, name: str | None = None, city: str | None = None
) -> HospitalCheck | Disambiguation | NotFound | AccessDenied:
    """Hospital network status and specialty by ID or name (and optional city), with Network alternatives."""
    if hospital_id is not None:
        if bad := validate_id("hospital", hospital_id):
            return bad
        row = fetch_one(f"SELECT {_COLUMNS} FROM silver.hospitals WHERE hospital_id = ?", [hospital_id])
        return _check(row) if row else not_found("hospital", hospital_id)
    if name and name.strip():
        return _by_name(name, city)
    return NotFound(entity="hospital", message="Give a hospital ID (like HOSP1257) or a hospital name.")


def _by_name(name: str, city: str | None) -> HospitalCheck | Disambiguation | NotFound:
    city_clause, city_params = (" AND lower(city) = lower(trim(?))", [city]) if city else ("", [])
    rows = fetch_all(
        f"SELECT {_COLUMNS} FROM silver.hospitals WHERE lower(hospital_name) = lower(trim(?)){city_clause}"
        " ORDER BY hospital_id",
        [name, *city_params],
    )
    if not rows:  # fall back to a substring match on the name
        rows = fetch_all(
            f"SELECT {_COLUMNS} FROM silver.hospitals"
            f" WHERE contains(lower(hospital_name), lower(trim(?))){city_clause} ORDER BY hospital_id",
            [name, *city_params],
        )
    if not rows:
        return NotFound(entity="hospital", message="No hospital with that name. Try the hospital ID.")
    if len(rows) == 1:
        return _check(rows[0])
    shown = rows[:MAX_MATCHES]
    return Disambiguation(
        entity="hospital",
        total_matches=len(rows),
        matches=[Match(id=r["hospital_id"], city=r["city"], specialty=r["specialty"]) for r in shown],
        message=f"{len(rows)} hospitals match that name. Which hospital ID do you mean?",
        sources=[sql_source("hospitals", r["hospital_id"]) for r in shown],
    )


def _check(row: dict[str, Any]) -> HospitalCheck:
    alternatives = [
        HospitalSummary.model_validate(r)
        for r in fetch_all(
            f"""SELECT {_COLUMNS} FROM silver.hospitals
                WHERE network_status = ? AND city = ? AND specialty = ? AND hospital_id <> ?
                ORDER BY hospital_id LIMIT ?""",
            [NETWORK, row["city"], row["specialty"], row["hospital_id"], MAX_ALTERNATIVES],
        )
    ]
    refs = [sql_source("hospitals", row["hospital_id"])]
    refs += [sql_source("hospitals", a.hospital_id) for a in alternatives]
    return HospitalCheck.model_validate({**row, "alternatives": alternatives, "sources": refs})
