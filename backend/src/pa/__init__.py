"""Planning Analytics (IBM TM1) integration.

`PlanningAnalyticsClient` is the contract; `MockTM1Client` is a local
JSON-backed stand-in used until a real TM1 instance is provisioned. The
dashboard talks only to the interface, so swapping in a real client later
touches nothing else.
"""
from src.pa.client import PlanningAnalyticsClient, get_pa_client
from src.pa.mock_tm1 import MockTM1Client

__all__ = ["PlanningAnalyticsClient", "MockTM1Client", "get_pa_client"]
