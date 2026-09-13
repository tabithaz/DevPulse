from dataclasses import dataclass


@dataclass(frozen=True)
class OwnershipResilience:
    top_owner_share: float
    effective_owners: float
    bus_factor: int
    status: str


def analyze_ownership_resilience(contributions: dict[str, int], critical_share: float = 0.5) -> OwnershipResilience:
    if not 0 < critical_share <= 1:
        raise ValueError("critical_share must be between 0 and 1")
    if not contributions:
        return OwnershipResilience(0.0, 0.0, 0, "unowned")
    if any(not isinstance(count, int) or isinstance(count, bool) or count < 0 for count in contributions.values()):
        raise ValueError("contribution counts must be non-negative integers")

    total = sum(contributions.values())
    if total == 0:
        return OwnershipResilience(0.0, 0.0, 0, "unowned")

    shares = sorted((count / total for count in contributions.values() if count > 0), reverse=True)
    top_owner_share = shares[0]
    effective_owners = 1 / sum(share * share for share in shares)

    cumulative = 0.0
    bus_factor = 0
    for share in shares:
        cumulative += share
        bus_factor += 1
        if cumulative >= critical_share:
            break

    if bus_factor == 1 and top_owner_share >= 0.7:
        status = "fragile"
    elif bus_factor <= 2:
        status = "moderate"
    else:
        status = "resilient"

    return OwnershipResilience(
        round(top_owner_share, 4),
        round(effective_owners, 2),
        bus_factor,
        status,
    )
