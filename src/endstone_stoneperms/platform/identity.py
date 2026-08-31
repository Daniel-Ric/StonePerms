from endstone import Player

from ..domain.model import SubjectRef, UserRecord


def player_unique_id(player: Player) -> str:
    return str(player.unique_id)


def player_subject(player: Player) -> SubjectRef:
    return SubjectRef.user(player_unique_id(player))


def player_record(player: Player) -> UserRecord:
    xuid = str(player.xuid).strip() if player.xuid else None
    return UserRecord(unique_id=player_unique_id(player), last_name=player.name, xuid=xuid)
