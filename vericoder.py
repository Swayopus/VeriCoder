"""VeriCoder CLI: evidence, controlled challenges, paired studies and blind review."""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import config
from agent.scripted import ScriptedAgent
from core.artifacts import new_run_id, write_json
from report.storage import ResultStore
from tasks.loader import TaskLoader

SCENARIOS = ["good", "modify_test", "wrong_file", "omit_requirement"]


def _agent_factory(args):
    if args.agent == "deepseek":
        from agent.deepseek import DeepSeekAgent
        key = os.environ.get(args.api_key_env, "")
        if args.api_key_file:
            value = Path(args.api_key_file).read_text(encoding="utf-8-sig").strip()
            if value.startswith("{"):
                values = json.loads(value)
                key = values.get(args.api_key_env, values.get("api_key", ""))
            elif "=" in value:
                pairs = dict(line.split("=", 1) for line in value.splitlines()
                             if "=" in line and not line.lstrip().startswith("#"))
                key = pairs.get(args.api_key_env, "").strip().strip("\"'")
            else:
                key = value
        if not key:
            raise ValueError("DeepSeek credential unavailable. Configure the selected environment variable or --api-key-file.")
        return lambda task: DeepSeekAgent(api_key=key, model=args.model,
                                         max_steps=args.max_steps, temperature=args.temperature,
                                         max_tokens=args.max_output_tokens)
    return lambda task: ScriptedAgent(scenario=args.scenario)


def _load_tasks(suite, task_id=None):
    loader = TaskLoader()
    aliases = {"todo-app": "todo", "blog-system": "blog", "mini-shop": "shop",
               "payments": "payments-api", "auth": "auth-service"}
    tasks = loader.load_all(None if suite == 'all' else aliases.get(suite, suite))
    if task_id:
        tasks = [t for t in tasks if t.task_id == task_id]
    if not tasks:
        raise ValueError(f"No tasks match suite={suite}, task={task_id}")
    return tasks


def _environment(args):
    if getattr(args, "backend", None):
        os.environ["VERICODER_EXECUTION_BACKEND"] = args.backend
    if getattr(args, "image", None):
        os.environ["VERICODER_DOCKER_IMAGE"] = args.image
    if getattr(args, 'ca_bundle', None):
        path = Path(args.ca_bundle).resolve(strict=True)
        os.environ['REQUESTS_CA_BUNDLE'] = str(path)


def cmd_list(args):
    for task in _load_tasks(args.suite):
        print(f"{task.repository}/{task.task_id}: {task.description.strip()}")
    return 0


def cmd_study(args):
    from experiments.paired import run_paired_study
    from report.study import summarize_study
    _environment(args)
    factory = _agent_factory(args)
    tasks = _load_tasks(args.suite, args.task)
    if args.limit:
        tasks = tasks[:args.limit]
    results, observations, path = run_paired_study(tasks, factory, repeats=args.repeat,
        max_retries=args.max_retries, run_id=args.run_id,
        storage=ResultStore() if args.save else None, acceptance_path=args.acceptance)
    data = json.loads(path.read_text(encoding="utf-8"))
    report = summarize_study(data)
    path.with_suffix(".md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Evidence: {path.resolve()}")
    return 2 if any(not r.final_report or not r.final_report.valid for r in results) else 0


def cmd_run(args):
    if args.mode == "both":
        return cmd_study(args)
    from experiments.runner import ExperimentRunner, ExperimentSpec
    from report.generator import summarize, to_markdown
    _environment(args)
    factory = _agent_factory(args)
    tasks = _load_tasks(args.suite, args.task)
    if args.limit:
        tasks = tasks[:args.limit]
    if args.acceptance:
        raise ValueError("Use study or run --mode both for held-out acceptance")
    run_id = args.run_id or new_run_id(args.mode)
    runner = ExperimentRunner(ExperimentSpec(args.mode, 0 if args.mode == 'baseline' else args.max_retries),
                              storage=ResultStore() if args.save else None, run_id=run_id)
    results = runner.run(tasks, factory, repeats=args.repeat)
    print(to_markdown(summarize(results), f"{args.mode}: {run_id}"))
    return 2 if any(not r.final_report or not r.final_report.valid for r in results) else 0


def cmd_demo(args):
    from experiments.runner import ExperimentRunner, ExperimentSpec
    _environment(args)
    tasks = _load_tasks(args.suite, args.task)
    print("Controlled synthetic challenge demonstration (not real-agent detection accuracy)")
    for scenario in SCENARIOS:
        runner = ExperimentRunner(ExperimentSpec("demo", 0))
        results = runner.run(tasks, lambda task: ScriptedAgent(scenario, recover_on_retry=False))
        for result in results:
            r = result.final_report
            print(f"{r.repository}/{result.task_id} {scenario}: {r.verdict}; tests={r.test_result.get('passed')}; requirements_failed={r.requirement_result.get('failed_count')}")
    return 0


def cmd_ci(args):
    from experiments.runner import ExperimentRunner, ExperimentSpec
    _environment(args)
    results = ExperimentRunner(ExperimentSpec("ci-demo", 0)).run(
        _load_tasks(args.suite, args.task), lambda task: ScriptedAgent(args.scenario, recover_on_retry=False))
    rank = {"PASS": 0, "WARNING": 1, "FAIL": 2, "INVALID": 3}
    verdict = max((r.final_report.verdict for r in results), key=rank.get)
    print("Synthetic suite verification; this command does not grade a pull request patch.")
    print(f"VERICODER_VERDICT={verdict}")
    return 2 if verdict == "INVALID" else int(verdict == "FAIL" and args.fail_on_fail)


def cmd_eval(args):
    from experiments.evaluation import run_evaluation, DEFAULT_MUTATIONS
    from report.detection import to_markdown
    _environment(args)
    tasks = _load_tasks(args.suite, args.task)
    mutations = args.mutations.split(",") if args.mutations else DEFAULT_MUTATIONS
    output = Path(args.out or config.REPORTS_DIR / (new_run_id("challenges") + ".json"))
    if output.exists() or output.with_suffix('.md').exists():
        raise ValueError(f"Refusing to overwrite prior evidence: {output}")
    observations, errors = run_evaluation(tasks, mutations=mutations, jobs=args.jobs)
    report = to_markdown(observations)
    write_json(output, {"schema_version": 2, "source": "synthetic", "suite": args.suite,
                        "errors": errors, "invalid_count": errors,
                        "observations": [o.to_dict() for o in observations]})
    output.with_suffix(".md").write_text(report, encoding="utf-8")
    print(report)
    print(f"Evidence index: {output.resolve()}")
    return 2 if errors else 0


def cmd_report(args):
    if args.study:
        from report.study import summarize_study
        print(summarize_study(json.loads(Path(args.study).read_text(encoding="utf-8-sig"))))
        return 0
    storage = ResultStore()
    rows = storage.rows(args.experiment, args.run_id)
    if not rows:
        print("No stored runs. Use run/study --save.")
        return 1
    run_id = args.run_id or rows[-1]["run_id"]
    rows = [r for r in rows if r["run_id"] == run_id]
    print(f"Run batch: {run_id} (legacy batches are never pooled with new results)")
    for condition in sorted({r['experiment'] for r in rows}):
        values = [r for r in rows if r['experiment'] == condition]
        print(f"{condition}: {sum(r['success'] for r in values)}/{len(values)} internal success, "
              f"invalid={sum(r['verdict']=='INVALID' for r in values)}, "
              f"tokens={sum(r['total_tokens'] for r in values)}, "
              f"recorded human actions={sum(r['human_intervention_count'] for r in values)}")
    return 0


def cmd_annotations(args):
    from report.annotations import apply_annotations, export_review_packet
    from report.detection import Observation, to_markdown
    source = json.loads(Path(args.input).read_text(encoding="utf-8-sig"))
    observations = [Observation(**o) for o in source['observations']]
    if args.action == 'export':
        print(export_review_packet(observations, args.out))
    else:
        observations = apply_annotations(observations, args.labels, args.adjudication)
        write_json(args.out, {'schema_version': 2, 'observations': [o.to_dict() for o in observations]})
        print(to_markdown(observations, 'Human-labelled agent evidence'))
    return 0


def cmd_benchmark(args):
    from experiments.swebench import fetch_instances, import_instances, evaluate_instances
    if args.action == 'fetch':
        print(fetch_instances(args.dataset, args.split, args.limit, args.out))
    elif args.action == 'import':
        print(import_instances(args.input, args.dataset, args.split, args.out))
    else:
        result = evaluate_instances(args.instances, args.predictions, args.run_id or new_run_id('swebench'),
                                    args.out, gold=args.gold)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('status') == 'completed' and result.get('returncode') == 0 else 2
    return 0


def cmd_doctor(args):
    import importlib.util
    import shutil
    print(f"Python: {sys.version.split()[0]}")
    print(f"Git: {bool(shutil.which('git'))}; Docker CLI: {bool(shutil.which('docker'))}")
    print(f"DeepSeek key configured: {bool(os.environ.get('DEEPSEEK_API_KEY'))}")
    for name in ('pytest', 'flask', 'yaml', 'requests', 'swebench', 'streamlit'):
        print(f"{name}: {bool(importlib.util.find_spec(name))}")
    print(f"Execution backend: {os.environ.get('VERICODER_EXECUTION_BACKEND', 'local')}")
    print('Local execution is a development backend, not a security sandbox.')
    return 0


def _scope(parser):
    parser.add_argument('--suite', default='all')
    parser.add_argument('--task')
    parser.add_argument('--backend', choices=['local', 'docker'], default='local')
    parser.add_argument('--image', default=None)


def _study_options(parser):
    _scope(parser)
    parser.add_argument('--agent', choices=['scripted', 'deepseek'], default='scripted')
    parser.add_argument('--scenario', choices=SCENARIOS, default='good')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--max-retries', type=int, default=2)
    parser.add_argument('--run-id')
    parser.add_argument('--save', action='store_true')
    parser.add_argument('--acceptance', help='Held-out assertion JSON, never used in feedback')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--api-key-env', default='DEEPSEEK_API_KEY')
    parser.add_argument('--api-key-file', help='Local credential file; contents are never logged')
    parser.add_argument('--ca-bundle', help='Trusted PEM CA bundle for provider TLS verification (never disables verification)')
    parser.add_argument('--model', default=config.DEEPSEEK_MODEL)
    parser.add_argument('--temperature', type=float, default=0.0)
    parser.add_argument('--max-steps', type=int, default=config.DEEPSEEK_MAX_STEPS)
    parser.add_argument('--max-output-tokens', type=int, default=4096)


def build_parser():
    parser = argparse.ArgumentParser(prog='vericoder')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('list'); p.add_argument('--suite', default='all'); p.set_defaults(func=cmd_list)
    p = sub.add_parser('doctor'); p.set_defaults(func=cmd_doctor)
    p = sub.add_parser('run'); _study_options(p)
    p.add_argument('--mode', choices=['baseline', 'vericoder', 'both'], default='both'); p.set_defaults(func=cmd_run)
    p = sub.add_parser('study', help='Paired feedback study sharing first attempts'); _study_options(p); p.set_defaults(func=cmd_study)
    p = sub.add_parser('demo'); _scope(p); p.set_defaults(func=cmd_demo)
    p = sub.add_parser('ci'); _scope(p)
    p.add_argument('--scenario', choices=SCENARIOS, default='good')
    p.add_argument('--fail-on-fail', action='store_true'); p.set_defaults(func=cmd_ci)
    p = sub.add_parser('eval', help='Controlled synthetic regression challenges'); _scope(p)
    p.add_argument('--jobs', type=int, default=1); p.add_argument('--mutations'); p.add_argument('--out'); p.set_defaults(func=cmd_eval)
    p = sub.add_parser('report'); p.add_argument('--experiment'); p.add_argument('--run-id'); p.add_argument('--study'); p.set_defaults(func=cmd_report)
    p = sub.add_parser('annotations'); actions = p.add_subparsers(dest='action', required=True)
    for action in ('export', 'score'):
        child = actions.add_parser(action); child.add_argument('--input', required=True); child.add_argument('--out', required=True)
        if action == 'score':
            child.add_argument('--labels', nargs='+', required=True); child.add_argument('--adjudication')
        child.set_defaults(func=cmd_annotations)
    p = sub.add_parser('benchmark'); actions = p.add_subparsers(dest='action', required=True)
    child = actions.add_parser('fetch'); child.add_argument('--dataset', default='princeton-nlp/SWE-bench_Lite')
    child.add_argument('--split', default='test'); child.add_argument('--limit', type=int, default=10)
    child.add_argument('--out', required=True); child.set_defaults(func=cmd_benchmark)
    child = actions.add_parser('import'); child.add_argument('--input', required=True)
    child.add_argument('--dataset', default='princeton-nlp/SWE-bench_Lite')
    child.add_argument('--split', default='test'); child.add_argument('--out', required=True)
    child.set_defaults(func=cmd_benchmark)
    child = actions.add_parser('evaluate'); child.add_argument('--instances', required=True)
    group = child.add_mutually_exclusive_group(required=True); group.add_argument('--predictions'); group.add_argument('--gold', action='store_true')
    child.add_argument('--run-id'); child.add_argument('--out', default='runs/swebench'); child.set_defaults(func=cmd_benchmark)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        for name in ('repeat', 'limit', 'max_steps', 'max_output_tokens', 'jobs'):
            value = getattr(args, name, None)
            if value is not None and value < 1:
                raise ValueError(f'--{name.replace("_", "-")} must be positive')
        if getattr(args, 'max_retries', 0) < 0:
            raise ValueError('--max-retries must be nonnegative')
        return args.func(args)
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
