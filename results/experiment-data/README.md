# Committed experiment data

Contains 480 completed JSON measurements (96 initial + four additional runs per condition) and three incomplete diagnostic logs. The incomplete logs have no `PLAYBACK_ENDED`, are explicitly marked in the manifest, and are excluded from comparison statistics.

All raw JSON is stored as deterministic gzip (`.json.gz`). Decompress with `gzip -dk FILE.json.gz`; decompressed bytes match the source. `manifest.jsonl` records SHA256 for original and compressed logs, condition, run status, and TCP/netem evidence where the runner captured it. `diagnostics.csv` summarizes the three incomplete runs.

`provenance.json` records source/media hashes, dependencies, Docker image, execution settings and counts. `combined-trials.csv`, `combined-comparison.csv`, `combined-bitrate-ci95.svg`, and `final-analysis.md` provide unified analysis for the 480 completed measurements. Batch-specific CSV/SVG files accompany them. Repetitive `source.patch` snapshots are excluded; they duplicate the entire dirty-worktree diff and are not QoE trial logs.
