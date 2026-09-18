# Scheduler repair — September 17, 2026

This is the staged repair/audit folder. The active scheduling files are separate from BotMonitor:

- `/home/stardustbreaker/MyBotz/run_market_bots.sh`
- `/home/stardustbreaker/MyBotz/stop_market_bots.sh`
- `/home/stardustbreaker/MyBotz/market_bot_scheduler.py`

They have no runtime dependency on BotMonitor, its virtual environment, or this staging folder.

## Changes applied

1. Corrected the two crontab paths from `/home/aaron/MyBotz/` to `/home/stardustbreaker/MyBotz/`.
2. Preserved weekday start at 09:30 and stop at 16:30 in the host's America/Detroit timezone.
3. Created isolated `venv` directories for options_covered, options_secured, and options_inverted, installing each repository's unchanged requirements.txt. Existing bot environments were preserved.
4. Interpreter discovery recognizes both `venv/bin/python` and `.venv/bin/python`, fixing ccexchange and ETFEnhancerLT startup.
5. Scheduling uses live process identity rather than trusting PID files: exact repository/script, same user, and process start-time checks before signalling. Repeated starts do not create duplicate bots. Stop handles verified launcher and worker processes.
6. Concurrent scheduler actions are guarded by an exclusive lock. Cron output is captured in `~/MyBotz/cron_logs/scheduler_cron.log`; each bot retains its own cron log.

Installed entries:

```cron
30 9 * * 1-5 /home/stardustbreaker/MyBotz/run_market_bots.sh >> /home/stardustbreaker/MyBotz/cron_logs/scheduler_cron.log 2>&1
30 16 * * 1-5 /home/stardustbreaker/MyBotz/stop_market_bots.sh >> /home/stardustbreaker/MyBotz/cron_logs/scheduler_cron.log 2>&1
```

All eight bots retain this existing market-hours schedule, including ccexchange. No schedule change to 24/7 crypto operation was made.

## Validation

- All eight environments passed `pip check` and dependency-only imports. No trading modules were imported or run by these tests.
- All eight launcher/main files passed syntax parsing.
- Four scheduler tests passed using harmless temporary Python processes: environment selection, exact identity matching, stale-PID rejection, and duplicate prevention plus launcher/worker shutdown.
- Deployment preflight marked all eight READY. At deployment, ETFEnhancer, momentum_master and options_direct were running; the remaining five were stopped.
- The cron service is active in America/Detroit time.
- Deployment did not start or stop any actual trading bot or change strategy/configuration/credential files. The next regular start is September 17 at 09:30 EDT. A successful preflight is not a claim that a live strategy cycle has completed.

Read-only preflight command:

```bash
~/MyBotz/run_market_bots.sh --check
```

The stop wrapper also accepts `--check`; it performs no stop action with that flag.

## Audit and backups

Original scripts and crontab are backed up under:

`/home/stardustbreaker/MyBotz/scheduler_backups/20260917T030106/`

This folder retains `crontab.before`, `crontab.proposed`, original script copies/hashes, package installation logs, `environment_validation.json`, `deployment.json`, and `installation_validation.json`.

An initial deployment preflight encountered an unrelated process whose working directory was inaccessible and correctly aborted before writing anything. The check was corrected to inspect working directories only for candidate Python bot processes; tests were rerun before successful deployment.
