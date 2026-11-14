# TODO

Before treating this as more than a work-in-progress demo, the human owner must:

1. Review every committed file, especially the tool schemas, approvals, budget calculations, and Docker security settings.
2. Tune the step, token, and dollar limits in `src/agent_loop/models.py` for the intended model, prompts, and acceptable spend.
3. Add a results table to `README.md` with observed end-to-end runs, completion behavior, approval decisions, step counts, tokens, and actual cost.
4. Record a demo showing an approved write, a rejected write, a capped run, and a resumed snapshot.
