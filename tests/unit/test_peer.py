from pyslsk.peer import Peer


class TestPeer:

    def test_whenResetBranchValues_shouldResetBranchValues(self):
        peer = Peer("myuser")
        peer.branch_level = 1
        peer.branch_root = "root"

        peer.reset_branch_values()

        assert peer.branch_level is None
        assert peer.branch_root is None
