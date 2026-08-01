# Nightwatch MLOps demo — Gemini vs YOLO in MLflow

A self-contained MLflow demo comparing Gemini Vision against local YOLO as a
candidate Nightwatch event detector, ending with a promoted Model Registry
version. All metrics are synthetic/fixed (not real API or model runs) —
built for walking someone through a working MLflow setup on a screenshare.

## Setup (one-time)

```bash
cd worker/mlops_demo
python3.13 -m venv .venv   # use 3.13, not 3.14 — mlflow's UI server currently
                            # breaks on 3.14 (importlib.abc.Traversable removed)
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python log_experiments.py
.venv/bin/mlflow ui --backend-store-uri sqlite:///mlflow.db
# open http://127.0.0.1:5000
```

Re-running `log_experiments.py` adds another set of 4 runs and a new set of
registry versions (registered model creation is skipped if it already exists)
— delete `mlflow.db` and `mlruns/` first for a clean slate.

## What it logs

- **Experiment** `nightwatch-detector-gemini-vs-yolo`, one parent run
  `gemini-vs-yolo-comparison` containing 4 nested child runs:
  `gemini-2.0-flash-baseline`, `gemini-2.0-flash-tuned-prompt`,
  `yolov8n-local`, `yolov8s-local`.
- Each child run logs params (model type, weights/prompt version, confidence
  threshold), metrics (precision, recall, F1, avg latency, cost per 1k
  events, false positive rate), and a loadable stub `pyfunc` model.
- **Model Registry** `NightwatchDetector` with 4 versions (one per run) and
  a `production` alias pointing at v4 (`yolov8s-local`).

## What each artifact shows (one sentence each)

- **`eval/_tmp_eval_summary_<run>.json`** (per run) — the raw TP/FP/FN/TN
  confusion-matrix counts that run's precision/recall/F1 were computed from.
- **`_tmp_comparison_chart.png`** (on the parent run) — a side-by-side bar
  chart of F1, latency, and cost-per-1k-events across all four candidates.
- **Registered model description** (`NightwatchDetector`) — why this model
  exists: Gemini (cloud, accurate, expensive/slow) vs YOLO (edge, cheaper,
  faster) as competing Nightwatch detector candidates.
- **Version description** (per registry version) — that version's run name
  and headline F1/latency/cost numbers, for scanning the registry table.
- **`promotion_reason` tag** (on the promoted version) — why v4 was chosen:
  within 3 points of F1 vs the best Gemini prompt, at ~9x lower latency and
  ~20x lower cost per 1k events.

## The story to tell on a screenshare

1. Open the experiment, show 4 runs with side-by-side metric columns.
2. Open the parent run, show the comparison chart artifact.
3. Open the Models tab, show `NightwatchDetector` with 4 versions and the
   `production` alias badge on v4.
4. Open v4, point at the `promotion_reason` tag — the promotion wasn't
   "pick the highest metric," it was a cost/latency tradeoff decision, which
   is the actual judgment call MLOps is for.
5. Optionally, load it live to prove it's a real, loadable model, not just a
   row in a table:
   ```python
   import mlflow, pandas as pd
   mlflow.set_tracking_uri("sqlite:///mlflow.db")
   model = mlflow.pyfunc.load_model("models:/NightwatchDetector@production")
   model.predict(pd.DataFrame({"frame_id": [101, 102]}))
   ```
