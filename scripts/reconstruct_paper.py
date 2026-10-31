"""Project verified frozen records onto the current paper's numeric displays.

No dataset access, network experiment or new performance measurement is made.
Core-only mode retains saved aggregate CIs; full mode also runs both frozen
record auditors with their original NumPy environment.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def confined(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Path outside artifact: {name}")
    return path


def check_artifact(root, identity):
    manifest = confined(root, identity["manifest_file"])
    if digest(manifest) != identity["manifest_sha256"]:
        raise ValueError(f"Unexpected frozen manifest: {manifest}")
    entries = read(manifest)
    if identity["manifest_file"] == "MANIFEST.json":
        entries = {row["path"]: row["sha256"] for row in entries["files"]}
    for name, expected in entries.items():
        if digest(confined(root, name)) != expected:
            raise ValueError(f"Frozen file mismatch: {name}")
    return {"tag": identity["tag"], "manifest_sha256": digest(manifest),
            "verified_files": len(entries)}


def export(out, name, rows):
    (out / (name + ".json")).write_text(
        json.dumps(rows, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    if rows and isinstance(rows, list) and isinstance(rows[0], dict):
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with (out / (name + ".csv")).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v
                              for k, v in row.items()} for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-v1", type=Path)
    parser.add_argument("--artifact-v1-1", type=Path)
    parser.add_argument("--core-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.core_only and (args.artifact_v1 or args.artifact_v1_1):
        parser.error("Use either --core-only or both artifact paths")
    if not args.core_only and not (args.artifact_v1 and args.artifact_v1_1):
        parser.error("Both frozen artifact roots are required, or use --core-only")
    out = args.output.resolve()
    artifact_roots = [p.resolve() for p in (args.artifact_v1, args.artifact_v1_1) if p]
    if any(out == p or out.is_relative_to(p) for p in artifact_roots):
        parser.error("Output must be outside the frozen artifact roots")
    # Avoid mixing outputs from different editions or a partial previous run.
    if out.exists() and any(out.iterdir()):
        parser.error("Output must be a new or empty directory")
    manifest = read(ROOT / "configs/paper_manifest.json")
    for name, expected in manifest["data_files"].items():
        if digest(confined(ROOT, name)) != expected:
            raise ValueError(f"Saved display source mismatch: {name}")
    out.mkdir(parents=True, exist_ok=True)
    labels = manifest["mode_labels"]

    def label(key):
        if key in labels:
            return labels[key]
        # Historical source identifiers remain unchanged in a separate field.
        return "External encrypted ANN, ef=" + key.rsplit("_", 1)[-1]

    core = read(ROOT / "paper_data/core_summary.json")
    modes = ("full", "fine_only", "coarse_only", "scan", "flat_fine", "flat_scan")
    scale = {(r["dataset"], r["n"], r["method"]): r for r in core["scale_rows"]}
    ablation = []
    for ds, n in (("coco", 50000), ("flickr30k", 25000)):
        for mode in modes:
            r = scale[ds, n, mode]
            ablation.append(dict(dataset=ds, gallery=n, configuration=label(mode),
                source_method=mode, full_vectors=r["mean_records"],
                traffic_MB=r["mean_bytes"] / 1e6,
                traffic_MB_ci95=[v / 1e6 for v in r["mean_bytes_query_bootstrap_ci95"]],
                rounds=r["mean_rounds"], median_ms=r["median_ms"]))
    export(out, "table_II", ablation)
    export(out, "figure_3_scale", core["scale_rows"])
    export(out, "figure_5_updates", core["update_rows"])
    export(out, "neighbor_fidelity", core["quality"])
    (out / "figure_4_windows.csv").write_bytes(
        (ROOT / "paper_data/windows_network_display.csv").read_bytes())
    audit = dict(manuscript_edition=manifest["manuscript_edition"],
        core_sources_verified=True, new_measurements=0,
        table_II_source="Saved aggregates; original CI fields are retained, not resampled",
        artifacts=[], tables={"II": len(ablation)},
        complete_current_numeric_tables=False)

    if not args.core_only:
        import numpy as np
        if np.__version__ != "1.26.4":
            raise RuntimeError("Frozen bootstrap auditors require NumPy 1.26.4")
        v1, v11 = artifact_roots
        for root, key in ((v1, "v1"), (v11, "v1_1")):
            audit["artifacts"].append(check_artifact(root, manifest["artifacts"][key]))
        old = out / "artifact_v1_recomputed"
        fresh = out / "artifact_v1_1_recomputed"
        for root, dest in ((v1, old), (v11, fresh)):
            subprocess.run([sys.executable, str(root / "reproduce.py"),
                            "--output", str(dest)], check=True)

        panel = [dict(dataset=r["dataset"], configuration=label(r["mode"]),
            source_method=r["mode"], queries=r["queries"], traffic_MB=r["mean_MB"],
            median_ms=r["median_ms"], median_ms_ci95=r["median_ms_ci95"])
            for r in read(fresh / "panel_work/summary.json")["summaries"] if r["group"] == "all"]
        mixed = [dict(dataset=r["dataset"], queries_per_replacement=r["query_interval"],
            configuration=label(r["mode"]), source_method=r["mode"],
            traffic_MB_per_query=r["total_application_MB"] / r["queries"],
            amortized_mean_ms=r["mean_ms_per_query_including_updates"],
            amortized_mean_ms_ci95=r["mean_ms_per_query_ci95"],
            upload_kB_per_operation=r["update_upload_bytes_mean"] / 1000,
            owner_ms_per_operation=r["owner_ms_per_update"])
            for r in read(old / "table_VI.json") if r["mode"] in ("flat_fine", "directory_fine")]
        images = [dict(dataset=r["dataset"], images=r["images"],
            auto_stored_kB=r["auto_stored_mean"] / 1000,
            sidecar_stored_kB=r["sidecar_stored_mean"] / 1000,
            auto_decode_ms=r["auto_decode_median"], sidecar_decode_ms=r["sidecar_decode_median"])
            for r in read(old / "table_VII.json")]
        local = [dict(dataset=r["dataset"], configuration=label(r["method"]),
            source_method=r["method"], traffic_MB=r["mean_MB"],
            median_ms=r["median_full_ms"], float_set_recall=r["mean_float64_set_recall"],
            float_set_recall_ci95=r["float64_recall_ci95"],
            integer_ordered_agreement_percent=100 * r["integer_ordered_exact_fraction"])
            for r in read(old / "table_VIII.json") if r["method"] != "fine_only"]
        network = [dict(profile=r["profile"], configuration=label(r["method"]),
            source_method=r["method"], traffic_MB=r["mean_MB"],
            median_ms=r["median_ms"], median_ms_ci95=r["median_ms_ci95"], p95_ms=r["p95_ms"])
            for r in read(fresh / "network_recomputed.json")]
        for name, rows, count in (("III", panel, 6), ("IV", mixed, 8),
                                 ("V", images, 2), ("VI", local, 10), ("VII", network, 9)):
            if len(rows) != count:
                raise ValueError(f"Unexpected current Table {name} row count")
            export(out, "table_" + name, rows)
            audit["tables"][name] = len(rows)
        audit.update(complete_current_numeric_tables=True,
            original_record_audit=read(old / "reproduction_audit.json"),
            fresh_record_audit=read(fresh / "reconstruction_pass.json"))
    audit["passed"] = True
    (out / "paper_reconstruction_audit.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "tables": audit["tables"],
                      "complete_current_numeric_tables": audit["complete_current_numeric_tables"],
                      "new_measurements": 0}, indent=2))


if __name__ == "__main__":
    main()
