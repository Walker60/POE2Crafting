"""SessionStore: plain Python object tests, no HTTP layer -- create/get/mutate/
TTL eviction."""
import random
import time

from poe2craft.domain.ids import BaseId
from poe2craft.domain.items import Item, Rarity
from poe2craft.solver.featurize import AbstractState
from poe2craft.solver.value_iteration import SolveResult
from poe2craft.web.session import SESSION_TTL_SECONDS, SessionStore


def _fake_result() -> SolveResult:
    state = AbstractState(rarity=Rarity.RARE, prefix_count=0, suffix_count=0, status=(0,))
    return SolveResult(value={state: -1.0}, policy={}, converged=True, iterations=1)


def _fake_item() -> Item:
    return Item(base_id=BaseId("base1"), ilvl=10, rarity=Rarity.NORMAL)


def test_create_returns_a_retrievable_session():
    store = SessionStore()
    state = AbstractState(rarity=Rarity.NORMAL, prefix_count=0, suffix_count=0, status=(0,))
    session = store.create(target=None, actions={}, result=_fake_result(), current_state=state, current_item=_fake_item(), rng=random.Random(0), n_trials=100)
    fetched = store.get(session.session_id)
    assert fetched is session
    assert fetched.current_state == state


def test_get_unknown_id_returns_none():
    store = SessionStore()
    assert store.get("does-not-exist") is None


def test_mutating_the_fetched_session_persists():
    store = SessionStore()
    state0 = AbstractState(rarity=Rarity.NORMAL, prefix_count=0, suffix_count=0, status=(0,))
    session = store.create(target=None, actions={}, result=_fake_result(), current_state=state0, current_item=_fake_item(), rng=random.Random(0), n_trials=100)

    fetched = store.get(session.session_id)
    state1 = AbstractState(rarity=Rarity.RARE, prefix_count=1, suffix_count=0, status=(2,))
    fetched.current_state = state1

    assert store.get(session.session_id).current_state == state1


def test_delete_removes_the_session():
    store = SessionStore()
    state = AbstractState(rarity=Rarity.NORMAL, prefix_count=0, suffix_count=0, status=(0,))
    session = store.create(target=None, actions={}, result=_fake_result(), current_state=state, current_item=_fake_item(), rng=random.Random(0), n_trials=100)
    assert store.delete(session.session_id) is True
    assert store.get(session.session_id) is None
    assert store.delete(session.session_id) is False  # already gone


def test_expired_session_is_evicted_on_next_access():
    store = SessionStore()
    state = AbstractState(rarity=Rarity.NORMAL, prefix_count=0, suffix_count=0, status=(0,))
    session = store.create(target=None, actions={}, result=_fake_result(), current_state=state, current_item=_fake_item(), rng=random.Random(0), n_trials=100)

    # Backdate last_used_at past the TTL rather than sleeping for real.
    session.last_used_at = time.time() - SESSION_TTL_SECONDS - 1

    assert store.get(session.session_id) is None
