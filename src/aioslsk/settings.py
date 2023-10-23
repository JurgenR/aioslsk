from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from .network.network import ListeningConnectionErrorMode
from .shares.model import DirectoryShareMode


class SharedDirectorySettingEntry(BaseModel, validate_assignment=True):
    path: str
    share_mode: DirectoryShareMode = DirectoryShareMode.EVERYONE
    users: List[str] = Field(default_factory=list)


class WishlistSettingEntry(BaseModel, validate_assignment=True):
    query: str
    enabled: bool = True


class UpnpSettings(BaseModel, validate_assignment=True):
    enabled: bool = True
    lease_duration: int = 0


class ReconnectSettings(BaseModel, validate_assignment=True):
    auto: bool = True
    timeout: int = 10


class ServerSettings(BaseModel, validate_assignment=True):
    hostname: str = 'server.slsknet.org'
    port: int = 2416
    reconnect: ReconnectSettings = ReconnectSettings()


class ListeningSettings(BaseModel, validate_assignment=True):
    error_mode: ListeningConnectionErrorMode = ListeningConnectionErrorMode.CLEAR
    port: int = 60000
    obfuscated_port: int = 60001


class PeerSettings(BaseModel, validate_assignment=True):
    obfuscate: bool = False


class NetworkSettings(BaseModel, validate_assignment=True):
    server: ServerSettings = Field(default_factory=ServerSettings)
    listening: ListeningSettings = Field(default_factory=ListeningSettings)
    peer: PeerSettings = Field(default_factory=PeerSettings)
    upnp: UpnpSettings = Field(default_factory=UpnpSettings)


class UserInfoSettings(BaseModel, validate_assignment=True):
    description: Optional[str] = None
    picture: Optional[str] = None


class CredentialsSettings(BaseModel, validate_assignment=True):
    username: str
    password: str
    info: UserInfoSettings = Field(default_factory=UserInfoSettings)


class SearchSettings(BaseModel, validate_assignment=True):
    wishlist: List[WishlistSettingEntry] = Field(default_factory=list)


class SharingLimitSettings(BaseModel, validate_assignment=True):
    upload_slots: int = 2
    upload_speed_kbps: int = 0
    download_speed_kbps: int = 0


class SharesSettings(BaseModel, validate_assignment=True):
    download: str = None
    directories: List[SharedDirectorySettingEntry] = Field(default_factory=list)
    limits: SharingLimitSettings = Field(default_factory=SharingLimitSettings)


class RoomsSettings(BaseModel, validate_assignment=True):
    auto_join: bool = True
    private_room_invites: bool = True
    favorites: Set[str] = Field(default_factory=set)


class UsersSettings(BaseModel, validate_assignment=True):
    friends: Set[str] = Field(default_factory=set)
    blocked: Set[str] = Field(default_factory=set)


class InterestsSettings(BaseModel, validate_assignment=True):
    liked: Set[str] = Field(default_factory=set)
    hated: Set[str] = Field(default_factory=set)


class DebugSettings(BaseModel, validate_assignment=True):
    search_for_parent: bool = True
    ip_overrides: Dict[str, str] = Field(default_factory=dict)
    log_connection_count: bool = False


class Settings(BaseSettings, validate_assignment=True):
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    credentials: CredentialsSettings = Field(default_factory=CredentialsSettings)
    searches: SearchSettings = Field(default_factory=SearchSettings)
    shares: SharesSettings = Field(default_factory=SharesSettings)
    users: UsersSettings = Field(default_factory=UsersSettings)
    rooms: RoomsSettings = Field(default_factory=RoomsSettings)
    interests: InterestsSettings = Field(default_factory=InterestsSettings)
    debug: DebugSettings = Field(default_factory=DebugSettings)


if __name__ == '__main__':
    import json
    with open(r"C:\Users\jurgen\Desktop\my_settings.json", 'r') as fh:
        mysettings = json.load(fh)
    import pdb; pdb.set_trace()
