"""`poe2craft` CLI: solve for an optimal crafting policy, replay it against the
real sampler, look up mechanic text, or launch the web GUI."""
from __future__ import annotations

import os
import random
from pathlib import Path
from typing import Optional

import typer

from poe2craft.cli.render import format_solve_summary, format_target, format_trajectory
from poe2craft.cli.spec import load_target_spec, resolve
from poe2craft.data.loader import load_gamedata
from poe2craft.domain.ids import BaseId, ModId
from poe2craft.domain.items import Rarity
from poe2craft.engine.omens import all_actions
from poe2craft.solver.model_learning import build_mdp
from poe2craft.solver.playback import run_trajectory
from poe2craft.solver.featurize import abstractify, concretize, item_from_report, start_state
from poe2craft.solver.policy import load_policy, save_policy
from poe2craft.solver.value_iteration import value_iteration

app = typer.Typer(help="Solve Path of Exile 2 item crafting as an MDP.")


@app.command()
def solve(
    spec: Path = typer.Argument(..., help="YAML target spec, see examples/"),
    n_trials: int = typer.Option(500, help="Monte Carlo trials per (state, action) pair"),
    seed: int = typer.Option(0, help="RNG seed, for reproducible solves"),
    out: Optional[Path] = typer.Option(None, help="Save the solved policy to this JSON file"),
    gamedata_path: Optional[Path] = typer.Option(None, help="Override the default compiled gamedata path"),
) -> None:
    """Learn the transition model and solve for the optimal policy."""
    gd = load_gamedata(gamedata_path)
    target_spec = load_target_spec(spec)
    target, state0 = resolve(gd, target_spec)
    actions = all_actions(gd, base_id=target.base_id)
    rng = random.Random(seed)

    typer.echo(format_target(target, gd))
    typer.echo("")
    typer.echo(f"Learning transition model ({n_trials} trials/pair) and solving...")
    mdp = build_mdp(gd, target, state0, actions, rng, n_trials=n_trials)
    result = value_iteration(mdp, actions, objective=target.objective)
    typer.echo("")
    typer.echo(format_solve_summary(result, target, state0, actions))

    if out is not None:
        save_policy(result, out)
        typer.echo(f"\nSaved policy to {out}")


@app.command()
def simulate(
    spec: Path = typer.Argument(..., help="YAML target spec used to produce the policy"),
    policy: Path = typer.Argument(..., help="Policy JSON file from `poe2craft solve --out ...`"),
    n: int = typer.Option(200, help="Number of real playthroughs to run"),
    seed: int = typer.Option(1, help="RNG seed"),
    verbose: int = typer.Option(0, help="Print this many full trajectories"),
    gamedata_path: Optional[Path] = typer.Option(None, help="Override the default compiled gamedata path"),
) -> None:
    """Replay a solved policy against the real sampler, as a statistical sanity
    check against the abstract model's predicted expected value."""
    gd = load_gamedata(gamedata_path)
    target_spec = load_target_spec(spec)
    target, state0 = resolve(gd, target_spec)
    actions = all_actions(gd, base_id=target.base_id)
    result = load_policy(policy)
    rng = random.Random(seed)

    successes = 0
    step_counts: list[int] = []
    for i in range(n):
        start_item = concretize(gd, target, state0, rng)
        traj = run_trajectory(gd, target, actions, result.policy, start_item, rng, target.max_steps)
        if traj.success:
            successes += 1
            step_counts.append(traj.step_count)
        if i < verbose:
            typer.echo(format_trajectory(traj.steps, traj.success, actions))
            typer.echo("")

    typer.echo(f"Simulated {n} runs: {successes}/{n} reached the target within {target.max_steps} steps ({successes / n:.1%})")
    if step_counts:
        typer.echo(f"Average steps among successes: {sum(step_counts) / len(step_counts):.2f}")
    predicted = -result.expected_value(state0)
    typer.echo(f"Solver's predicted expected steps/cost from start: {predicted:.2f}")


@app.command()
def explain(
    name: str = typer.Argument(..., help="Currency/action/omen name"),
    gamedata_path: Optional[Path] = typer.Option(None, help="Override the default compiled gamedata path"),
) -> None:
    """Print poe2db-sourced mechanic text for a currency or omen."""
    gd = load_gamedata(gamedata_path)
    for c in gd.currency_mechanics:
        if name.lower() in (c["display_name"].lower(), c["action_kind"].lower()):
            typer.echo(c["description"])
            return
    for o in gd.omens:
        if name.lower() == o["name"].lower():
            typer.echo(o["effect"])
            return
    typer.echo(
        f"No mechanic text available for {name!r} yet -- poe2db omen/currency scraping "
        "(see docs/data_provenance.md, Phase 2) hasn't been populated in this gamedata build."
    )


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Host to bind (127.0.0.1 = this machine only)"),
    port: int = typer.Option(8000, help="Port to bind"),
    reload: bool = typer.Option(False, help="Auto-reload on code changes (development only)"),
    gamedata_path: Optional[Path] = typer.Option(None, help="Override the default compiled gamedata path"),
    pool_workers: Optional[int] = typer.Option(
        None, help="Worker processes for parallel solving (default: one per CPU core; 0 disables it)"
    ),
) -> None:
    """Launch the web GUI (FastAPI backend + browser SPA) at http://host:port."""
    import uvicorn

    # uvicorn's --reload re-imports "poe2craft.web.app:app" by string in a
    # fresh subprocess, so a gamedata_path override can't cross that boundary
    # as a live Python object -- relay it through the environment instead,
    # read once by web.app.create_app() at startup.
    if gamedata_path is not None:
        os.environ["POE2CRAFT_GAMEDATA_PATH"] = str(gamedata_path)

    if reload:
        # Windows' reload supervisor restarts the server subprocess by
        # hard-killing it (TerminateProcess), which runs no Python cleanup at
        # all -- any process-pool workers owned by that subprocess would be
        # orphaned on every single reload. --reload is dev-only, so this
        # costs nothing where it actually matters.
        os.environ["POE2CRAFT_POOL_WORKERS"] = "0"
        typer.echo("--reload: disabling the process pool (Windows reload hard-kills subprocesses, which would leak workers)")
    else:
        os.environ["POE2CRAFT_POOL_WORKERS"] = str(pool_workers if pool_workers is not None else (os.cpu_count() or 1))

    typer.echo(f"Serving poe2craft at http://{host}:{port}")
    uvicorn.run("poe2craft.web.app:app", host=host, port=port, reload=reload)


def _trade_client(league: Optional[str]):
    from poe2craft.pricing.config import TradeConfig
    from poe2craft.pricing.trade_client import TradeClient
    from poe2craft.pricing.transport import RequestsTransport

    # TradeConfig.load(), not from_env(): also picks up anything saved via
    # the web UI's Trade settings panel, so the CLI and the web app agree.
    config = TradeConfig.load()
    if league is not None:
        config = TradeConfig(poesessid=config.poesessid, league=league)
    return TradeClient(config, RequestsTransport())


def _find_base(gd, name: str) -> BaseId:
    matches = [b for b in gd.bases.values() if b.name == name]
    if not matches:
        raise typer.BadParameter(f"unknown base {name!r}")
    return matches[0].id


@app.command(name="mod-price")
def mod_price(
    mod_id: str = typer.Argument(..., help="Mod id, e.g. from `poe2craft explain` or data/compiled/poe2_gamedata.json"),
    base: str = typer.Option(..., help="Exact base item name, e.g. \"Amulet\""),
    league: Optional[str] = typer.Option(None, help="Overrides POE2CRAFT_TRADE_LEAGUE for this one call"),
    gamedata_path: Optional[Path] = typer.Option(None, help="Override the default compiled gamedata path"),
) -> None:
    """What premium does this modifier actually carry on trade? Queries
    pathofexile.com/trade2 live (see docs/data_provenance.md) -- this makes
    a real network request using POE2CRAFT_POESESSID/POE2CRAFT_TRADE_LEAGUE
    from your environment, never automatically otherwise."""
    from poe2craft.pricing.stat_matching import load_mod_stat_mapping
    from poe2craft.pricing.valuation import mod_premium

    gd = load_gamedata(gamedata_path)
    base_id = _find_base(gd, base)
    mapping = load_mod_stat_mapping()
    client = _trade_client(league)

    estimate = mod_premium(client, gd, mapping, base_id, ModId(mod_id))
    typer.echo(f"League: {client.league}")
    if estimate.divine_price is None:
        typer.echo("No premium estimate available.")
    else:
        typer.echo(f"Estimated premium: {estimate.divine_price:.3f} Divine Orb ({estimate.n_listings} listings considered)")
    for c in estimate.caveats:
        typer.echo(f"  note: {c}")


@app.command(name="trade-compare")
def trade_compare(
    spec: Path = typer.Argument(..., help="YAML target spec, see examples/ -- must use objective: cost"),
    current_mod: list[str] = typer.Option(
        [], "--current-mod", help='Present mod as "mod_id:tier_ilvl", repeatable -- the item as it actually is right now'
    ),
    rarity: str = typer.Option("rare", help="Current item's rarity: normal/magic/rare"),
    league: Optional[str] = typer.Option(None, help="Overrides POE2CRAFT_TRADE_LEAGUE for this one call"),
    n_trials: int = typer.Option(300, help="Monte Carlo trials per (state, action) pair"),
    seed: int = typer.Option(0, help="RNG seed"),
    gamedata_path: Optional[Path] = typer.Option(None, help="Override the default compiled gamedata path"),
) -> None:
    """Keep crafting vs. buy the target vs. sell the current item and
    restart, in real Divine-Orb terms -- the in-process CLI counterpart to
    the web UI's "Compare vs. market" panel. Makes a real trade2 request,
    same caveats as `mod-price`."""
    from poe2craft.pricing.stat_matching import load_mod_stat_mapping
    from poe2craft.pricing.valuation import estimate_buy_price, estimate_sell_value, recommend

    gd = load_gamedata(gamedata_path)
    target_spec = load_target_spec(spec)
    if target_spec.objective != "cost":
        raise typer.BadParameter("trade-compare needs a spec with objective: cost, so every number is in Divine Orb terms")
    target, state0 = resolve(gd, target_spec)
    actions = all_actions(gd, base_id=target.base_id)
    rng = random.Random(seed)

    mod_reports = []
    for entry in current_mod:
        mid, _, ilvl = entry.partition(":")
        if not ilvl:
            raise typer.BadParameter(f'--current-mod {entry!r} must be "mod_id:tier_ilvl"')
        mod_reports.append((ModId(mid), int(ilvl)))
    item = item_from_report(gd, target.base_id, target.ilvl, Rarity(rarity), mod_reports)

    typer.echo("Solving current state...")
    item_state = abstractify(target, item)
    mdp = build_mdp(gd, target, item_state, actions, rng, n_trials=n_trials)
    result = value_iteration(mdp, actions, objective=target.objective)
    craft_cost = -result.expected_value(item_state)

    typer.echo("Solving from an empty item (for the restart comparison)...")
    fresh_state = start_state(gd, target, Rarity.NORMAL, frozenset())
    if fresh_state in result.value:
        fresh_craft_cost = -result.expected_value(fresh_state)
    else:
        fresh_mdp = build_mdp(gd, target, fresh_state, actions, rng, n_trials=n_trials)
        fresh_result = value_iteration(fresh_mdp, actions, objective=target.objective)
        fresh_craft_cost = -fresh_result.expected_value(fresh_state)

    mapping = load_mod_stat_mapping()
    client = _trade_client(league)
    typer.echo(f"League: {client.league}")
    typer.echo("Querying pathofexile.com/trade2...")
    buy = estimate_buy_price(client, gd, mapping, target)
    sell = estimate_sell_value(client, gd, mapping, item)
    restart_net_cost = fresh_craft_cost - sell.divine_price if sell.divine_price is not None else None
    recommendation = recommend(craft_cost, buy.divine_price, restart_net_cost)

    typer.echo("")
    typer.echo(f"Keep crafting:     {craft_cost:.3f} Divine Orb (expected, from here)")
    typer.echo(f"Buy the target:    {buy.divine_price:.3f} Divine Orb ({buy.n_listings} listings)" if buy.divine_price is not None else "Buy the target:    insufficient data")
    if sell.divine_price is not None:
        typer.echo(f"Sell current item: {sell.divine_price:.3f} Divine Orb ({sell.n_listings} listings)")
        typer.echo(f"Sell + restart:    {restart_net_cost:.3f} Divine Orb net cost (negative = net profit)")
    else:
        typer.echo("Sell current item: insufficient data")
    typer.echo("")
    typer.echo(f"Recommendation: {recommendation}")
    for c in list(buy.caveats) + list(sell.caveats):
        typer.echo(f"  note: {c}")


@app.command()
def doctor() -> None:
    """Diagnostics -- currently just a Windows multiprocessing spawn-safety
    check for the process pool used to parallelize solving. Run this after
    any change to the installed entry point (packaging/version bumps) or
    environment (new AV policy, etc.) that might affect child-process
    creation -- it exercises the hazard through the real installed
    `poe2craft` command, not a throwaway script."""
    from poe2craft.solver.parallel import self_test_pool

    ok, pids = self_test_pool(max_workers=4, n_tasks=20)
    status = "OK" if ok else "FAILED"
    typer.echo(f"process pool: {status} -- {len(pids)} distinct worker PID(s): {sorted(pids)}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
