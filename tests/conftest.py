"""Repo-wide backstop, not a source of fixtures: no test in this suite may
ever make a real HTTP call. Most tests never would anyway, but the pricing
package (poe2craft.pricing) is a real network client by design -- this
autouse fixture makes an accidental real call in a test fail immediately and
loudly (rather than hang, or silently succeed against pathofexile.com)
instead of relying on every test author remembering to inject a fake
Transport. See docs/data_provenance.md."""
import pytest
import requests


@pytest.fixture(autouse=True)
def _block_real_network_calls(monkeypatch):
    def _forbidden(*args, **kwargs):
        raise AssertionError(
            "A test attempted a real HTTP request via requests.Session.send -- "
            "tests must use a fake Transport (see tests/unit/pricing_fakes.py), "
            "never the real network."
        )

    monkeypatch.setattr(requests.Session, "send", _forbidden)
