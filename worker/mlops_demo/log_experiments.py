"""
Logs 4 comparable detection runs (Gemini Vision vs local YOLO) to MLflow,
then registers the winning model and promotes it to Production.

Usage:
    .venv/bin/python log_experiments.py
    .venv/bin/mlflow ui --backend-store-uri sqlite:///mlflow.db

All metrics below are synthetic (fixed, hand-picked numbers), evaluated
against a fictitious 500-clip annotated CCTV set (person/vehicle/package
events, IoU=0.5). Nothing here calls the real Gemini API or a real YOLO
model. Numbers are chosen to reflect a plausible real-world tradeoff:
Gemini has better accuracy, YOLO has far lower latency and cost.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mlflow
import pandas as pd
from mlflow.tracking import MlflowClient

HERE = Path(__file__).resolve().parent
EVAL_SET_TAG = "nightwatch-eval-v1 (500 clips: person/vehicle/package, IoU=0.5)"

mlflow.set_tracking_uri(f"sqlite:///{HERE / 'mlflow.db'}")
mlflow.set_experiment("nightwatch-detector-gemini-vs-yolo")

RUNS = [
    dict(
        name="gemini-2.0-flash-baseline",
        params=dict(
            model_type="gemini",
            model_name="gemini-2.0-flash",
            prompt_version="v1",
            confidence_threshold=0.5,
        ),
        metrics=dict(
            precision=0.86,
            recall=0.91,
            f1=0.885,
            avg_latency_ms=850,
            cost_per_1k_events_usd=12.40,
            false_positive_rate=0.09,
        ),
        confusion=dict(tp=910, fp=148, fn=90, tn=8852),
    ),
    dict(
        name="gemini-2.0-flash-tuned-prompt",
        params=dict(
            model_type="gemini",
            model_name="gemini-2.0-flash",
            prompt_version="v3",
            confidence_threshold=0.6,
        ),
        metrics=dict(
            precision=0.90,
            recall=0.89,
            f1=0.895,
            avg_latency_ms=820,
            cost_per_1k_events_usd=12.40,
            false_positive_rate=0.06,
        ),
        confusion=dict(tp=890, fp=99, fn=110, tn=8901),
    ),
    dict(
        name="yolov8n-local",
        params=dict(
            model_type="yolo",
            weights="yolov8n.pt",
            confidence_threshold=0.5,
            device="cpu",
        ),
        metrics=dict(
            precision=0.81,
            recall=0.78,
            f1=0.795,
            avg_latency_ms=45,
            cost_per_1k_events_usd=0.35,
            false_positive_rate=0.14,
        ),
        confusion=dict(tp=780, fp=183, fn=220, tn=8817),
    ),
    dict(
        name="yolov8s-local",
        params=dict(
            model_type="yolo",
            weights="yolov8s.pt",
            confidence_threshold=0.5,
            device="cpu",
        ),
        metrics=dict(
            precision=0.88,
            recall=0.85,
            f1=0.865,
            avg_latency_ms=95,
            cost_per_1k_events_usd=0.60,
            false_positive_rate=0.08,
        ),
        confusion=dict(tp=850, fp=116, fn=150, tn=8884),
    ),
]

REGISTERED_MODEL_NAME = "NightwatchDetector"


class StubDetector(mlflow.pyfunc.PythonModel):
    """A loadable stand-in model: wraps the run's config and returns a
    fake per-frame detection so the registered version can actually be
    loaded and called, not just referenced as a row in a table."""

    def __init__(self, run_name: str, model_type: str):
        self.run_name = run_name
        self.model_type = model_type

    def predict(self, model_input: pd.DataFrame) -> pd.DataFrame:
        frame_ids = (
            model_input.iloc[:, 0]
            if len(model_input.columns)
            else range(len(model_input))
        )
        return pd.DataFrame(
            {
                "frame_id": frame_ids,
                "detection": [f"person@0.90 ({self.run_name})"] * len(model_input),
            }
        )


def log_one_run(run_cfg: dict) -> tuple[str, str]:
    with mlflow.start_run(run_name=run_cfg["name"], nested=True) as run:
        mlflow.set_tag("eval_set", EVAL_SET_TAG)
        mlflow.log_params(run_cfg["params"])
        mlflow.log_metrics(run_cfg["metrics"])

        summary_path = HERE / f"_tmp_eval_summary_{run_cfg['name']}.json"
        summary_path.write_text(
            json.dumps(
                {"eval_set": EVAL_SET_TAG, "confusion_matrix": run_cfg["confusion"]},
                indent=2,
            )
        )
        mlflow.log_artifact(str(summary_path), artifact_path="eval")
        summary_path.unlink()

        model_info = mlflow.pyfunc.log_model(
            name="model",
            python_model=StubDetector(run_cfg["name"], run_cfg["params"]["model_type"]),
            input_example=pd.DataFrame({"frame_id": [1, 2, 3]}),
        )
        return run.info.run_id, model_info.model_uri


def log_comparison_chart(run_ids_and_cfgs: list[tuple[str, dict]]) -> None:
    names = [cfg["name"] for _, cfg in run_ids_and_cfgs]
    f1s = [cfg["metrics"]["f1"] for _, cfg in run_ids_and_cfgs]
    latencies = [cfg["metrics"]["avg_latency_ms"] for _, cfg in run_ids_and_cfgs]
    costs = [cfg["metrics"]["cost_per_1k_events_usd"] for _, cfg in run_ids_and_cfgs]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for ax, values, title, ylabel in [
        (axes[0], f1s, "F1 score", "F1"),
        (axes[1], latencies, "Avg inference latency", "ms / frame"),
        (axes[2], costs, "Cost", "USD / 1k events"),
    ]:
        bars = ax.bar(names, values, color=["#4C8BF5", "#4C8BF5", "#34A853", "#34A853"])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=30)
        for label in ax.get_xticklabels():
            label.set_ha("right")
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{value:g}",
                ha="center",
                va="bottom",
                fontsize=9,
            )
    fig.suptitle("Gemini Vision vs local YOLO — Nightwatch detector candidates")
    fig.tight_layout()

    chart_path = HERE / "_tmp_comparison_chart.png"
    fig.savefig(chart_path, dpi=150)
    plt.close(fig)
    mlflow.log_artifact(str(chart_path))
    chart_path.unlink()


def register_and_promote(model_uri_by_name: dict[str, str]) -> None:
    client = MlflowClient()
    try:
        client.create_registered_model(
            REGISTERED_MODEL_NAME,
            description=(
                "Object/event detector for Nightwatch camera events. "
                "Candidates evaluated: Gemini Vision (cloud, higher accuracy, "
                "higher cost/latency) vs local YOLOv8 (edge, lower accuracy, "
                "far lower cost/latency)."
            ),
        )
    except Exception:
        pass  # already exists if this script is re-run

    version_by_name = {}
    for cfg in RUNS:
        mv = client.create_model_version(
            name=REGISTERED_MODEL_NAME,
            source=model_uri_by_name[cfg["name"]],
        )
        client.update_model_version(
            name=REGISTERED_MODEL_NAME,
            version=mv.version,
            description=(
                f"{cfg['name']}: f1={cfg['metrics']['f1']}, "
                f"latency={cfg['metrics']['avg_latency_ms']}ms, "
                f"cost=${cfg['metrics']['cost_per_1k_events_usd']}/1k events."
            ),
        )
        version_by_name[cfg["name"]] = mv.version

    promoted_version = version_by_name["yolov8s-local"]
    client.set_registered_model_alias(
        REGISTERED_MODEL_NAME, "production", promoted_version
    )
    client.set_model_version_tag(
        REGISTERED_MODEL_NAME,
        promoted_version,
        "promotion_reason",
        "Best accuracy/cost/latency tradeoff at fleet scale: within 3pts F1 of "
        "the tuned Gemini prompt at ~9x lower latency and ~20x lower per-event cost.",
    )

    print(f"\nRegistered model: {REGISTERED_MODEL_NAME}")
    for name, version in version_by_name.items():
        marker = " <-- production" if version == promoted_version else ""
        print(f"  v{version}: {name}{marker}")


def main() -> None:
    run_id_by_name = {}
    model_uri_by_name = {}
    with mlflow.start_run(run_name="gemini-vs-yolo-comparison") as parent:
        for cfg in RUNS:
            run_id, model_uri = log_one_run(cfg)
            run_id_by_name[cfg["name"]] = run_id
            model_uri_by_name[cfg["name"]] = model_uri
        log_comparison_chart([(run_id_by_name[c["name"]], c) for c in RUNS])
        print(f"Parent comparison run: {parent.info.run_id}")

    register_and_promote(model_uri_by_name)

    print(
        "\nDone. Launch the UI with:\n"
        f"  cd {HERE} && .venv/bin/mlflow ui --backend-store-uri sqlite:///mlflow.db"
    )


if __name__ == "__main__":
    main()
