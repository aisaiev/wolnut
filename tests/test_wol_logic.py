import pytest
from unittest.mock import MagicMock
import tempfile
import os

from wolnut.config import ClientConfig, WolnutConfig, NutConfig, WakeOnConfig
from wolnut.state import ClientStateTracker


@pytest.fixture
def temp_status_file():
    """Create a temporary status file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        temp_path = f.name
    yield temp_path
    # Clean up
    if os.path.exists(temp_path):
        os.unlink(temp_path)


def test_force_wol_skips_online_check(temp_status_file):
    """Test that force_wol bypasses the online-before-shutdown check."""
    # Create clients with different force_wol settings
    clients = [
        ClientConfig(
            name="client-force-wol",
            host="192.168.1.100",
            mac="DE:AD:BE:EF:00:01",
            force_wol=True
        ),
        ClientConfig(
            name="client-normal",
            host="192.168.1.101",
            mac="DE:AD:BE:EF:00:02",
            force_wol=False
        ),
    ]
    
    # Create state tracker (both clients will be initialized as NOT having been online before shutdown)
    state_tracker = ClientStateTracker(clients, status_file=temp_status_file)
    
    # Test the logic for each client
    for client in clients:
        should_skip_wol = (
            not state_tracker.was_online_before_shutdown(client.name) 
            and not client.force_wol
        )
        
        if client.name == "client-force-wol":
            # Should NOT skip WOL because force_wol=True
            assert not should_skip_wol, f"Client {client.name} should not skip WOL (force_wol=True)"
        elif client.name == "client-normal":
            # Should skip WOL because was not online and force_wol=False
            assert should_skip_wol, f"Client {client.name} should skip WOL (was not online, force_wol=False)"


def test_normal_client_wol_when_was_online(temp_status_file):
    """Test that normal clients get WOL when they were online before shutdown."""
    clients = [
        ClientConfig(
            name="client-was-online",
            host="192.168.1.100",
            mac="DE:AD:BE:EF:00:01",
            force_wol=False
        ),
    ]
    
    state_tracker = ClientStateTracker(clients, status_file=temp_status_file)
    
    # Simulate the client being online first
    state_tracker.update("client-was-online", True)
    # Then mark all online clients as having been online before shutdown
    state_tracker.mark_all_online_clients()
    
    client = clients[0]
    should_skip_wol = (
        not state_tracker.was_online_before_shutdown(client.name) 
        and not client.force_wol
    )
    
    # Should NOT skip WOL because client was online before shutdown
    assert not should_skip_wol, "Client should not skip WOL (was online before shutdown)"


def test_force_wol_false_by_default():
    """Test that force_wol defaults to False when not specified."""
    client_without_force_wol = ClientConfig(
        name="client-default",
        host="192.168.1.100",
        mac="DE:AD:BE:EF:00:01"
        # force_wol not specified
    )
    
    assert client_without_force_wol.force_wol == False, "force_wol should default to False"


def test_force_wol_explicit_values():
    """Test that force_wol can be explicitly set to True or False."""
    client_force_true = ClientConfig(
        name="client-force-true",
        host="192.168.1.100",
        mac="DE:AD:BE:EF:00:01",
        force_wol=True
    )
    
    client_force_false = ClientConfig(
        name="client-force-false",
        host="192.168.1.101",
        mac="DE:AD:BE:EF:00:02",
        force_wol=False
    )
    
    assert client_force_true.force_wol == True, "force_wol should be True when explicitly set"
    assert client_force_false.force_wol == False, "force_wol should be False when explicitly set"