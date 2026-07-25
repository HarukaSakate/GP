# results_NoTC CUBIC・BBR統合分析

## 1. 分析対象

- CUBIC: 16条件
- BBR: 16条件
- 条件構成: Throughput/BOLA × TCP信号8組合せ
- TCP信号: None、RTT、CWND、Loss、およびその組合せ
- 各条件1試行
- 全32条件が約596秒の再生位置まで完走
- 明示的なtc/netem制御を行わないNoTC条件

各条件1試行であるため、条件間の小さな差は統計的効果ではなく試行間変動として扱う。

## 2. 最も重要な結論

1. TCPメトリクスAPIはCUBIC・BBRの両方でブラウザへ情報を配送できている。
2. CUBICでRTTを使用すると、現在のRTTx判定がほぼ常時成立し、過剰な品質変更とQoE低下を起こす。
3. BBRでは全条件でGuardrailが0回であり、TCP信号の選択はABR出力へ実質的に影響していない。
4. LossとCWNDの判定条件はCUBIC・BBRの全条件で成立率0%だった。
5. NoTC実験はAPIの負の対照として有用だが、現状ではCUBICが負の対照を満たしていない。

## 3. CUBICの結果

### RTTを使わない条件

- Guardrail: 全条件0回
- 平均ビットレート: おおむね1.35～1.41 Mbps
- 品質切替: 0～5回
- Loss: 全サンプル0%
- CWND圧迫条件: 全サンプル0%

LossとCWNDは画面へ表示されているが、ABR判定条件を一度も満たしていない。
したがって、これらのON/OFF条件間のQoE差をTCP信号の効果とは解釈できない。

### RTTを使った条件

| 条件 | Guardrail | 品質切替 | Stall (s) | 平均bitrate (Mbps) |
| --- | ---: | ---: | ---: | ---: |
| Throughput / RTT | 206 | 154 | 84.79 | 0.510 |
| Throughput / RTT+CWND | 180 | 140 | 57.51 | 0.476 |
| Throughput / RTT+Loss | 198 | 143 | 75.41 | 0.504 |
| Throughput / RTT+CWND+Loss | 157 | 124 | 33.10 | 0.434 |
| BOLA / RTT | 187 | 143 | 61.98 | 0.490 |
| BOLA / RTT+CWND | 217 | 171 | 105.54 | 0.519 |
| BOLA / RTT+CWND+Loss | 201 | 148 | 72.21 | 0.500 |

RTTを含む条件では、RTTx > 1.5の成立率がほぼ100%だった。絶対RTTのp95は
0.24～0.67 msと小さい一方、RTTxのp95は約60～133倍だった。ローカル低遅延環境では
最小RTTが極端に小さくなるため、比率が輻輳量ではなく微小値同士の変動を増幅している。

CUBICロジックはRTTxだけで輻輳判定できるため、NoTCでも常時輻輳に近い状態となった。
Guardrailが1段階下げた直後に通常ABRが上げ直し、再びGuardrailが下げる発振によって、
品質切替・stallが増え、平均ビットレートが約0.43～0.52 Mbpsまで低下した。

BOLA / RTT+LossはRTTx閾値を満たしながらGuardrailが0回だった。これはバッファ8秒超かつ
stallCountが0の間はWatchingとなる保護条件によると考えられる。一度stallが起きると
累積stallCountが0へ戻らないため、その後は同じ保護が働かないという状態依存性がある。

## 4. BBRの結果

### 全条件でGuardrailが0回

BBRではRTTを含む条件でもGuardrailは一度も適用されなかった。そのため、
全条件の平均ビットレートは約1.367～1.406 Mbps、品質切替は1～5回の範囲に収まり、
TCP信号選択による系統的な差は確認できない。

BBRのRTT判定は、RTTx > 1.4に加えてdelivery rateが現在動画ビットレートの1.15倍未満
であることを要求する。ログのdelivery rateは、p05でも約5.2～52.4 Gbps、
中央値は約29～131 Gbpsに達した。一方、動画は約1.4 Mbpsである。

ローカルの高速TCP接続で得られるカーネルdelivery rateと動画ビットレートを直接比較すると、
前者が常に桁違いに大きくなるため、BBRのRTT条件は実質的に成立しない。
したがって、BBRでGuardrailが0回だったことはBBRが常に健全だった証明ではなく、
比較する尺度が実験環境に適合していない可能性を示している。

### BBR条件間の差

BBRのPlayback excessは約4.1～11.0秒、記録stallは約2.5～8.5秒だった。
Guardrailが全条件0回なので、この範囲の差はTCPメトリクス選択の効果ではなく、
単発試行のばらつきと考えるのが妥当である。

## 5. LossとCWNDについて

### Loss

- 推定loss平均: 全32条件で0%
- loss p95: 全32条件で0%
- 再送増分あり: 全32条件で0%

NoTCではloss信号が発生していないため、APIが0を正しく届ける負の対照にはなるが、
Loss-aware ABRの有効性は評価できない。

### CWND

- CWND圧迫条件成立率: 全32条件で0%
- CWND由来Guardrail: 0回

現在の「観測最大CWNDの60%以下」かつ「未ACKがCWNDの80%以上」という条件は
一度も成立しなかった。特にBBRではCWND単独の意味がCUBICと異なるため、
同一ルールを両CCへ適用することにも注意が必要である。

## 6. 計測上の問題

CUBIC Throughput / NoneはtotalStallMsが0秒だが、最終再生位置と総所要時間の差が
約80秒あった。PLAYBACK_WAITING/STALLEDで捕捉されないスケジューラ停止や待ち時間が
含まれる可能性がある。QoE評価ではtotalStallMsだけでなく、heartbeat間で
playbackTimeが進まない区間を直接積算する必要がある。

また、APIサーバのcc値は起動引数から通知されている。対象HTTPソケットが実際に使う
輻輳制御をgetsockopt(TCP_CONGESTION)で取得し、ログへ記録する方が検証として確実である。

## 7. 改善案

### 7.1 RTT判定

優先度: 高

- RTTxだけで判定せず、RTT - baseline RTTの絶対増加量をAND条件にする
- baseline RTTが1 ms未満など極端に小さい場合はRTTx判定を無効化する
- 連続3～5サンプル、移動中央値、EWMAなどで持続的な増加だけを検出する
- 接続切替時にbaselineをリセットし、接続IDもログへ残す
- NoTC条件ではGuardrailが原則0回になるよう閾値を校正する

例:

    rtt_congested =
        baseline_rtt_ms >= 1.0
        and rttx > 1.5
        and (rtt_ms - baseline_rtt_ms) > 5.0
        and condition_persists_for >= 3 samples

### 7.2 BBRのdelivery rate

優先度: 高

- tcpi_delivery_rateの瞬間値を動画ビットレートと直接比較しない
- セグメント単位の実効goodput、acked bytes差分、または時間窓平均を使用する
- app-limited状態を区別し、アプリが送信していない期間を帯域低下と判定しない
- delivery rateの絶対値ではなく、直近baselineからの低下率を使う
- tc/netemで既知の帯域上限を設定し、取得値が実験条件と整合するか検証する

### 7.3 CWND判定

優先度: 中

- 当面は表示・ログ用途とし、単独でのdownshiftを避ける
- CUBICとBBRで別々の判定ロジックを設計する
- 最大値比ではなく、移動baselineからの低下率と持続時間を使う
- bytes in flight、BDP、delivery rate、RTTとの組合せで解釈する
- 条件成立率を常にログ化し、0%または100%に張り付く閾値を検出する

### 7.4 Loss判定

優先度: 中

- netem lossを0.1%、1%、3%、5%など段階的に設定する
- 再送カウンタ差分が既知のloss条件に追従することを先に検証する
- 単発再送で即downshiftせず、時間窓内の再送率と持続性を使う
- パケットlossと輻輳以外の無線lossを同一視しない

### 7.5 ABR制御構造

優先度: 高

- Guardrailがrepresentationを直接下げ続ける方式を避ける
- dash.jsのcustom ABR ruleとして、一定期間の最大許容品質を返す
- downshift後に数セグメントのhold-down期間を設定する
- downshift閾値と復帰閾値を分け、ヒステリシスを設ける
- 累積stallCountではなく、現在バッファと直近stallからの経過時間で保護する
- 同じTCPサンプルで複数回品質変更しない

### 7.6 APIとセッション対応

優先度: 高

- client IPだけでなくsession ID、HTTP接続ID、対象MPD/segmentを対応付ける
- 複数TCP接続のうち、どの接続を選んだかを各tcp_metricsへ含める
- TCP接続が変わった場合はRTT minimum、CWND peak、再送差分をリセットする
- TCP_CONGESTIONをソケットから読み、実CC名を通知する
- API値の単位、欠損、counter wrap、socket changeを自動テストする

### 7.7 実験設計

優先度: 高

- NoTCを負の対照として残す
- 全条件へ同一の帯域・遅延・lossトレースを適用する
- 条件の実行順をランダム化する
- 各条件を最低5～10回繰り返す
- 平均、標準偏差、95%信頼区間を示す
- TCP信号の条件成立率、Congestion detected回数、Watching回数も記録する
- API評価とABR効果評価を分離する

## 8. 次に行うべき順序

1. NoTCでCUBIC RTT Guardrailが発火しないようRTT判定を修正する。
2. BBR delivery rateをセグメントgoodputまたは時間窓値へ変更する。
3. Guardrailを最大品質制限型のcustom ABR ruleへ変更し、発振を止める。
4. stallをheartbeatの再生位置から再計測する。
5. controlled delay実験でRTT信号を検証する。
6. controlled loss実験でLoss信号を検証する。
7. controlled bandwidth/queue実験でCWND信号を検証する。
8. 各条件を複数回実行して初めてQoE差を比較する。

## 9. 生成物

- CUBIC/analysis_summary.csv
- CUBIC/analysis_comparison.svg
- BBR/analysis_summary.csv
- BBR/analysis_comparison.svg
- analysis_summary_all.csv
- scripts/analyze_results_notc.py

再集計:

    python3 scripts/analyze_results_notc.py
