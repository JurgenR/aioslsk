import os
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from .constants import (
    UPNP_DEFAULT_CHECK_INTERVAL,
    UPNP_DEFAULT_LEASE_DURATION,
    UPNP_DEFAULT_SEARCH_TIMEOUT,
)
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
    lease_duration: int = UPNP_DEFAULT_LEASE_DURATION
    check_interval: int = UPNP_DEFAULT_CHECK_INTERVAL
    search_timeout: int = UPNP_DEFAULT_SEARCH_TIMEOUT


class ReconnectSettings(BaseModel, validate_assignment=True):
    auto: bool = False
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


class NetworkLimitSettings(BaseModel, validate_assignment=True):
    upload_speed_kbps: int = 0
    download_speed_kbps: int = 0


class NetworkSettings(BaseModel, validate_assignment=True):
    server: ServerSettings = Field(default_factory=ServerSettings)
    listening: ListeningSettings = Field(default_factory=ListeningSettings)
    peer: PeerSettings = Field(default_factory=PeerSettings)
    upnp: UpnpSettings = Field(default_factory=UpnpSettings)
    limits: NetworkLimitSettings = Field(default_factory=NetworkLimitSettings)


class UserInfoSettings(BaseModel, validate_assignment=True):
    description: Optional[str] = None
    picture: Optional[bytes] = None


class CredentialsSettings(BaseModel, validate_assignment=True):
    username: str
    password: str
    info: UserInfoSettings = Field(default_factory=UserInfoSettings)

    def are_configured(self) -> bool:
        """Returns whether the credentials are correctly configured"""
        return bool(self.username) and self.password is not None


class SearchSettings(BaseModel, validate_assignment=True):
    max_results: int = 100
    wishlist: List[WishlistSettingEntry] = Field(default_factory=list)


class TransferLimitSettings(BaseModel, validate_assignment=True):
    upload_slots: int = 2


class TransfersSettings(BaseModel, validate_assignment=True):
    limits: TransferLimitSettings = Field(default_factory=TransferLimitSettings)
    report_interval: float = 0.250


class SharesSettings(BaseModel, validate_assignment=True):
    scan_on_start: bool = True
    download: str = os.getcwd()
    directories: List[SharedDirectorySettingEntry] = Field(default_factory=list)


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
    credentials: CredentialsSettings = Field(default_factory=CredentialsSettings)  # type: ignore
    searches: SearchSettings = Field(default_factory=SearchSettings)
    shares: SharesSettings = Field(default_factory=SharesSettings)
    users: UsersSettings = Field(default_factory=UsersSettings)
    rooms: RoomsSettings = Field(default_factory=RoomsSettings)
    interests: InterestsSettings = Field(default_factory=InterestsSettings)
    transfers: TransfersSettings = Field(default_factory=TransfersSettings)
    debug: DebugSettings = Field(default_factory=DebugSettings)


def _main(args):
    import json
    import sys

    if args.command == 'generate':
        settings = Settings(
            credentials=CredentialsSettings(
                username=args.username,
                password=args.password
            )
        )

        dump = settings.model_dump(mode='json')
        json.dump(dump, sys.stdout, indent=2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Setting file tools")
    subparsers = parser.add_subparsers(dest='command')

    gen_parser = subparsers.add_parser('generate')
    gen_parser.add_argument('--username', '-u', default="TestUser")
    gen_parser.add_argument('--password', '-p', default="Pass0")

    args = parser.parse_args()
    _main(args)
