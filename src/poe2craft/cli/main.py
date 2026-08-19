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
from poe2craft.engine.omens import all_actions
from poe2craft.solver.model_learning import build_mdp
from poe2craft.solver.playback import run_trajectory
from poe2craft.solver.featurize import concretize
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
) -> None:
    """Launch the web GUI (FastAPI backend + browser SPA) at http://host:port."""
    import uvicorn

    # uvicorn's --reload re-imports "poe2craft.web.app:app" by string in a
    # fresh subprocess, so a gamedata_path override can't cross that boundary
    # as a live Python object -- relay it through the environment instead,
    # read once by web.app.create_app() at startup.
    if gamedata_path is not None:
        os.environ["POE2CRAFT_GAMEDATA_PATH"] = str(gamedata_path)
    typer.echo(f"Serving poe2craft at http://{host}:{port}")
    uvicorn.run("poe2craft.web.app:app", host=host, port=port, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
