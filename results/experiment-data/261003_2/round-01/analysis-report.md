# 第1ラウンド全体分析

対象: `results/261003_2/round-01`。全96条件（CC 2 × ABR 2 × TCP信号8 × netem 3）、各1試行。

## 実行と技術的妥当性

- completed 96/96、失敗・タイムアウト0/96。各再生は約596秒の全長を再生し、PLAYBACK_ENDEDを記録。
- TCP_SIGNAL_UPDATE 113,510件、HEARTBEAT 57,512件、PLAYBACK_ENDED 96件。各条件レビュー evidence の10検査項目は96件すべて通過。
- 実CC、設定ABR/信号、session_id・connection_id、DASH media socket、netem profileとseed、描画品質とbitrate index整合、実行時エラーなし、signal fresh、信号offでguardrailなしを確認。
- netem profileはstable-8mbit (8 Mbit/s, 20±2 ms, 0%)、constrained-2mbit (2 Mbit/s, 60±10 ms, 0.5%)、high-rtt-loss (4 Mbit/s, 120±20 ms, 1%)。各ログのqdisc表示はrate/delay/jitter/loss/seedを含み検査通過。
- 欠損率はHEARTBEATのtcpMetrics欠損数/HEARTBEAT数。96件平均0.918%、最大5.509%。信号ageMsは各記録値の平均約266 ms（条件差あり）。API側 freshness_ms=0は最新サンプル時点の鮮度であり、別定義のageMsと混同しない。
- 失敗率は失敗/全試行。ここでは0%。各条件n=1のため分散・95%CIは算出不能で、比較CSVもCI欄は空欄。

## 条件軸ごとの記述統計

各値はその軸の水準に該当する条件を単純平均した記述値。ネットワーク条件など他の軸を周辺化したn=48/32/12であり、因果効果を示さない。

### 起動遅延 (秒)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 1.031 | 48 |
| CC: cubic | 0.877 | 48 |
| ABR: bola | 0.952 | 48 |
| ABR: throughput | 0.956 | 48 |
| 信号: cwnd | 0.946 | 12 |
| 信号: cwnd-loss | 0.944 | 12 |
| 信号: loss | 1.021 | 12 |
| 信号: none | 0.930 | 12 |
| 信号: rtt | 0.964 | 12 |
| 信号: rtt-cwnd | 0.956 | 12 |
| 信号: rtt-cwnd-loss | 0.973 | 12 |
| 信号: rtt-loss | 0.898 | 12 |
| netem: constrained-2mbit | 0.923 | 32 |
| netem: high-rtt-loss | 1.444 | 32 |
| netem: stable-8mbit | 0.495 | 32 |

### 停止時間 (秒)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 0.000 | 48 |
| CC: cubic | 0.000 | 48 |
| ABR: bola | 0.000 | 48 |
| ABR: throughput | 0.000 | 48 |
| 信号: cwnd | 0.000 | 12 |
| 信号: cwnd-loss | 0.000 | 12 |
| 信号: loss | 0.000 | 12 |
| 信号: none | 0.000 | 12 |
| 信号: rtt | 0.000 | 12 |
| 信号: rtt-cwnd | 0.000 | 12 |
| 信号: rtt-cwnd-loss | 0.000 | 12 |
| 信号: rtt-loss | 0.000 | 12 |
| netem: constrained-2mbit | 0.000 | 32 |
| netem: high-rtt-loss | 0.000 | 32 |
| netem: stable-8mbit | 0.000 | 32 |

### 停止回数 (回)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 0.000 | 48 |
| CC: cubic | 0.000 | 48 |
| ABR: bola | 0.000 | 48 |
| ABR: throughput | 0.000 | 48 |
| 信号: cwnd | 0.000 | 12 |
| 信号: cwnd-loss | 0.000 | 12 |
| 信号: loss | 0.000 | 12 |
| 信号: none | 0.000 | 12 |
| 信号: rtt | 0.000 | 12 |
| 信号: rtt-cwnd | 0.000 | 12 |
| 信号: rtt-cwnd-loss | 0.000 | 12 |
| 信号: rtt-loss | 0.000 | 12 |
| netem: constrained-2mbit | 0.000 | 32 |
| netem: high-rtt-loss | 0.000 | 32 |
| netem: stable-8mbit | 0.000 | 32 |

### 時間加重表示ビットレート (Mbps)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 1.341 | 48 |
| CC: cubic | 0.731 | 48 |
| ABR: bola | 1.053 | 48 |
| ABR: throughput | 1.018 | 48 |
| 信号: cwnd | 1.069 | 12 |
| 信号: cwnd-loss | 1.066 | 12 |
| 信号: loss | 1.089 | 12 |
| 信号: none | 1.151 | 12 |
| 信号: rtt | 0.986 | 12 |
| 信号: rtt-cwnd | 0.950 | 12 |
| 信号: rtt-cwnd-loss | 0.992 | 12 |
| 信号: rtt-loss | 0.985 | 12 |
| netem: constrained-2mbit | 0.912 | 32 |
| netem: high-rtt-loss | 0.790 | 32 |
| netem: stable-8mbit | 1.406 | 32 |

### 描画品質切替数 (回)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 10.000 | 48 |
| CC: cubic | 17.958 | 48 |
| ABR: bola | 12.104 | 48 |
| ABR: throughput | 15.854 | 48 |
| 信号: cwnd | 14.167 | 12 |
| 信号: cwnd-loss | 13.917 | 12 |
| 信号: loss | 14.000 | 12 |
| 信号: none | 8.833 | 12 |
| 信号: rtt | 14.000 | 12 |
| 信号: rtt-cwnd | 18.083 | 12 |
| 信号: rtt-cwnd-loss | 13.333 | 12 |
| 信号: rtt-loss | 15.500 | 12 |
| netem: constrained-2mbit | 35.812 | 32 |
| netem: high-rtt-loss | 5.125 | 32 |
| netem: stable-8mbit | 1.000 | 32 |

### Guardrail適用数 (回)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 0.062 | 48 |
| CC: cubic | 8.042 | 48 |
| ABR: bola | 4.000 | 48 |
| ABR: throughput | 4.104 | 48 |
| 信号: cwnd | 2.583 | 12 |
| 信号: cwnd-loss | 2.417 | 12 |
| 信号: loss | 0.083 | 12 |
| 信号: none | 0.000 | 12 |
| 信号: rtt | 6.750 | 12 |
| 信号: rtt-cwnd | 6.750 | 12 |
| 信号: rtt-cwnd-loss | 7.000 | 12 |
| 信号: rtt-loss | 6.833 | 12 |
| netem: constrained-2mbit | 11.656 | 32 |
| netem: high-rtt-loss | 0.500 | 32 |
| netem: stable-8mbit | 0.000 | 32 |

### TCP RTT平均 (ms)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 92.471 | 48 |
| CC: cubic | 164.805 | 48 |
| ABR: bola | 129.299 | 48 |
| ABR: throughput | 127.976 | 48 |
| 信号: cwnd | 130.108 | 12 |
| 信号: cwnd-loss | 131.701 | 12 |
| 信号: loss | 131.700 | 12 |
| 信号: none | 131.278 | 12 |
| 信号: rtt | 127.961 | 12 |
| 信号: rtt-cwnd | 125.999 | 12 |
| 信号: rtt-cwnd-loss | 125.934 | 12 |
| 信号: rtt-loss | 124.421 | 12 |
| netem: constrained-2mbit | 126.027 | 32 |
| netem: high-rtt-loss | 143.451 | 32 |
| netem: stable-8mbit | 116.435 | 32 |

### CWND平均 (パケット)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 47.621 | 48 |
| CC: cubic | 96.592 | 48 |
| ABR: bola | 72.951 | 48 |
| ABR: throughput | 71.262 | 48 |
| 信号: cwnd | 72.144 | 12 |
| 信号: cwnd-loss | 72.886 | 12 |
| 信号: loss | 71.740 | 12 |
| 信号: none | 72.268 | 12 |
| 信号: rtt | 72.975 | 12 |
| 信号: rtt-cwnd | 72.698 | 12 |
| 信号: rtt-cwnd-loss | 72.285 | 12 |
| 信号: rtt-loss | 69.857 | 12 |
| netem: constrained-2mbit | 27.633 | 32 |
| netem: high-rtt-loss | 47.682 | 32 |
| netem: stable-8mbit | 141.005 | 32 |

### 推定TCPロス率平均 (%)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 0.731 | 48 |
| CC: cubic | 0.538 | 48 |
| ABR: bola | 0.636 | 48 |
| ABR: throughput | 0.634 | 48 |
| 信号: cwnd | 0.676 | 12 |
| 信号: cwnd-loss | 0.569 | 12 |
| 信号: loss | 0.564 | 12 |
| 信号: none | 0.662 | 12 |
| 信号: rtt | 0.614 | 12 |
| 信号: rtt-cwnd | 0.707 | 12 |
| 信号: rtt-cwnd-loss | 0.613 | 12 |
| 信号: rtt-loss | 0.672 | 12 |
| netem: constrained-2mbit | 0.666 | 32 |
| netem: high-rtt-loss | 1.238 | 32 |
| netem: stable-8mbit | 0.000 | 32 |

### HEARTBEAT TCP信号欠損率 (%)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 1.022 | 48 |
| CC: cubic | 0.814 | 48 |
| ABR: bola | 0.897 | 48 |
| ABR: throughput | 0.939 | 48 |
| 信号: cwnd | 1.266 | 12 |
| 信号: cwnd-loss | 1.934 | 12 |
| 信号: loss | 0.334 | 12 |
| 信号: none | 0.904 | 12 |
| 信号: rtt | 0.807 | 12 |
| 信号: rtt-cwnd | 1.099 | 12 |
| 信号: rtt-cwnd-loss | 0.543 | 12 |
| 信号: rtt-loss | 0.459 | 12 |
| netem: constrained-2mbit | 0.704 | 32 |
| netem: high-rtt-loss | 1.069 | 32 |
| netem: stable-8mbit | 0.981 | 32 |

### 信号ageMs平均 (ms)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 267.092 | 48 |
| CC: cubic | 266.078 | 48 |
| ABR: bola | 268.020 | 48 |
| ABR: throughput | 265.151 | 48 |
| 信号: cwnd | 268.967 | 12 |
| 信号: cwnd-loss | 256.803 | 12 |
| 信号: loss | 263.352 | 12 |
| 信号: none | 277.679 | 12 |
| 信号: rtt | 260.285 | 12 |
| 信号: rtt-cwnd | 272.890 | 12 |
| 信号: rtt-cwnd-loss | 262.738 | 12 |
| 信号: rtt-loss | 269.968 | 12 |
| netem: constrained-2mbit | 275.810 | 32 |
| netem: high-rtt-loss | 272.791 | 32 |
| netem: stable-8mbit | 251.154 | 32 |

### バッファ平均 (秒)

| 軸 | 平均値 | 条件試行数 |
|---|---:|---:|
| CC: bbr | 23.447 | 48 |
| CC: cubic | 17.719 | 48 |
| ABR: bola | 20.720 | 48 |
| ABR: throughput | 20.445 | 48 |
| 信号: cwnd | 20.956 | 12 |
| 信号: cwnd-loss | 20.801 | 12 |
| 信号: loss | 20.766 | 12 |
| 信号: none | 21.901 | 12 |
| 信号: rtt | 20.197 | 12 |
| 信号: rtt-cwnd | 19.565 | 12 |
| 信号: rtt-cwnd-loss | 20.313 | 12 |
| 信号: rtt-loss | 20.163 | 12 |
| netem: constrained-2mbit | 15.200 | 32 |
| netem: high-rtt-loss | 19.824 | 32 |
| netem: stable-8mbit | 26.725 | 32 |

## 主な観測

- 96条件すべて完了し、停止時間・停止回数はいずれも0。これは今回の約596秒再生の観測事実であり、一般条件への保証ではない。
- CC別周辺平均はCUBIC 0.731 Mbps、BBR 1.341 Mbps。RTT平均はそれぞれ164.805 ms、92.471 ms。単発・netem周辺化値なのでCCの優劣とは結論できない。
- netem別の周辺平均はstable 1.406 Mbps / 起動0.495秒、constrained 0.912 Mbps / 起動0.923秒、high-rtt-loss 0.790 Mbps / 起動1.444秒。条件変更に沿う記述的傾向だが統計的主張ではない。
- signal noneの周辺平均は1.151 Mbps、8.833品質切替、Guardrail 0回。信号あり条件は信号組合せにより差があり、単純平均で0.950–1.089 Mbps、13.3–18.1切替、0.083–7.0 Guardrail適用。信号ありに一律のQoE改善は観測されない。これだけでロジック不具合とは判断できない。
- 品質切替が高いconstrained条件 (平均35.812回)、Guardrailが多い同条件 (平均11.656回) は技術検査を通過している。しきい値や検出/ガードレイルの変更を正当化する根拠にはならない。

## 分析上の限界・修正判断

- 比較CSVは各条件n=1の平均=中央値で、標準偏差と95%信頼区間は空欄。単発ラウンドで有意差や再現性を推定できない。
- README等の旧分析器ではなく今回のJSONイベントログを読む `analyze_matrix.py` を使用。試行一覧と条件指標をCSV、完了状態をSVGに保存。
- 各メトリクスはログ内の定義に基づく。loss_mean_pctはTCP_INFO由来の推定値であり、netemの設定損失率やアプリケーションパケット損失と同一ではない。RTT/CWND/lossはサーバ側で対応付けたTCP socket samplesの記録値。
- 技術検査では96件すべてに異常なし。低いビットレートやGuardrail発動頻度の差だけでは修正根拠にならない。ユーザー指示に従い、検出・欠損判定・Guardrailのロジックは変更しない。今回の分析からコード修正は不要と判断し、比較結果を改善する目的の調整も行わない。
- 次の信頼性向上手段は、同一ソース固定でラウンドを追加して各条件を独立反復し、ばらつきを測ること。各条件1回の今回結果とは別ラウンドとして保存する。

## 成果物

- `pilot-analysis/trials.csv`: 各試行の指標。
- `pilot-analysis/comparison.csv`: 条件別指標、n、失敗率、CI欄。
- `pilot-analysis/completion.svg`: 完了状況。
- `reviews/<condition>/evidence.json` と `review.md`: 96条件の技術検査。
- `plan.json`, `batch.json`, 各manifest: 実験設定・ソース・依存・メディア・seed・qdisc・CC証跡。
