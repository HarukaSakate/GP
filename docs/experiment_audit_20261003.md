# 実行・修正・再検証レポート（2026-10-03）

## 実際に確認した結果

作業対象は `/home/l0gic/GP`。AGENTS.mdは空。README、implementation_status、TCPプロトコル、プレイヤ、collector、Docker、netem、既存分析とテストを調査した。既存未コミット変更は保持し、修正前差分と対象ファイルを `results/audit-20261003/before` に保存した。

- 修正前の単体テスト8件成功。リポジトリの動画はLFSポインタのため、既定の動画ではスモークを開始できなかった。
- `/home/l0gic/abr-pretest/dash/test2` の480個の動画オブジェクトは、リポジトリのLFS SHA256・サイズとすべて一致。明示的な読み取り専用マウントで利用。
- 修正前の実TCP_INFOスモークは45秒で意図的に打ち切り。再生位置43.256秒、動画596.4秒。成功には計上しない。
- 修正後の20秒検証専用MPDでCUBIC/ThroughputとBBR/BOLAが実TCP信号付きで再生完了。BBR/BOLA、高RTT損失条件ではGuardrailルール発動1回、起動1.161秒、停止0秒、平均受信RTT147.36ms。条件・動画が異なるため修正前後のQoE改善の証明には使用しない。
- 実Chromeで欠損・期限切れメトリクスはnull、新鮮なメトリクスは利用可能になることを確認。既存ABRへのフォールバックの入力境界を検証。
- 追加した回帰検証を含む単体テスト10件成功。コンテナ内qdiscと既定CC、受信サンプルの実CC/connection_idを保存・検証。
- ホストは当初reno/cubicのみ。sudoのBBRロードはパスワード要求で失敗したが、DockerのBBR sysctl指定と実受信サンプルのcc=bbrによってBBRが実際に利用できることを確認した。ホストの既定CCやqdiscは変更していない。

## 問題・修正

1. ランナーの固定された旧動画パス → リポジトリ相対既定値と明示的な `--media-dir`。
2. 反復・失敗分離・上書き防止の欠如 → 10回の有効計測を既定とし、毎回専用コンテナと新Chromeプロファイル、新session_idを作る。失敗はattempts、成功はrun-01〜run-10。再利用バッチを拒否。各条件3失敗で停止して調査を要求。
3. 末尾0.25秒到達を完了に見なす処理 → 実際のPLAYBACK_ENDEDのみ有効。TCPサンプルなし・CC不一致も無効。
4. Guardrailイベント名不一致 → 旧名とTCP_GUARDRAIL_RULE_APPLIEDを集計。指標を見せるための閾値調整は行っていない。
5. コンテナにsysctl実行ファイルがない → /proc/sysから実設定を読む。修正途中の3失敗は独立して保存。
6. 一回の結果だけを扱う旧分析 → manifestの失敗も含むtrials.csv、条件別comparison.csvとcompletion.svgを追加。
7. 条件順序とnetemの乱数 → seed付き順序シャッフル、反復ごとのnetem seed、qdisc実出力を保存。

## 指標定義

起動遅延はSTARTから初回playingまでの秒。停止時間はプレイヤのtotalStallMs/1000、停止回数はstallCount、切替はswitchCount。平均ビットレートは再生中HEARTBEATでの算術平均Mbpsと、既存プレイヤが出力する時間加重Mbpsを別々に保存。バッファはHEARTBEATのbufferLevel秒。RTTはTCP_SIGNAL_UPDATEのrtt_us/1000の平均ms、CWNDは平均パケット数、推定損失は再送代理値の平均%。Guardrailはルール判断イベント数であり、実画面切替数とは区別する。

missing_tcp_pctはHEARTBEATで新鮮なtcpMetricsがない割合（欠損と期限切れを合わせた値）。tcp_age_mean_msは新鮮なサンプルの受信経過時間の平均ms。TCP統計はサンプル平均であり送信バイト加重ではない。各条件の成功試行について平均、中央値、標本標準偏差、Student tの95%信頼区間を集計。n=1の標準偏差・CIは空欄。失敗率は失敗/全試行。startup前の失敗にも空ログ相当とエラーを保存し、集計から除外しない。

## 本計測

本計測は2 CC ×2 ABR ×8信号選択 ×3ネットワーク =96条件、各10成功、計960成功を要求する。20秒のスモークは本計測に含めない。元動画596.4秒を使用し、動画再生時間だけで逐次約159時間。ソース・設定のコピー、ハッシュ、イメージ識別、pip freeze、動画ハッシュをバッチに保存する。

本計測中の件数はcounts.jsonとmanifest-shard-0.jsonlで確認する。全96条件にvalid=10が揃うまでは完了と宣言せず、効果に関する結論・信頼区間を確定しない。途中停止やタイムアウトも保存する。追加修正が必要なら当該バッチを終了して新しいコード・別バッチで全条件を再実行する。

## 再現コマンド

```bash
python3 -m venv /tmp/gp-audit-venv
/tmp/gp-audit-venv/bin/pip install websocket-client==1.9.2
python3 -m unittest discover -s tests -v
docker build -f Dockerfile.experiment -t gp-audit-final-20261003 .
/tmp/gp-audit-venv/bin/python scripts/run_full_matrix.py \
  --profiles experiments/netem_profiles.json \
  --media-dir /home/l0gic/abr-pretest/dash/test2 \
  --image gp-audit-final-20261003 \
  --results-dir results/production-20261003 \
  --repetitions 10 --max-attempts 15 --seed 20261003 --timeout-sec 1200
python3 scripts/analyze_matrix.py results/production-20261003
```

別環境ではGit LFS実体を復元したdash/test2を指定する。モックを本計測に使用しない。Docker NET_ADMINは専用コンテナのeth0だけに使用する。すでに使われているホスト80/8080などは使用しない。

## 残課題と制限

TCP_INFO collectorの接続選択はclient_ipを基準とする単一クライアント設計。並列クライアントでのセッション分離の保証はないため本計測は逐次実行する。短いスモークの条件間差は因果効果の検証にならない。netem乱数seedを揃えても、TCP/ブラウザのスケジューリングにより各試行の完全一致は期待しない。比較統計は本計測終了後に確定する。eBPFとモックの新規検証、collector資源使用量の測定は未実施。

## 本計測起動の確認

保持実行セッション74726で本計測を開始。最初の条件はBBR / Throughput / RTT / constrained-2mbit。開始約2分で、実TCPサンプル229件、再生位置113.08秒を確認した。初期nohup起動は実行環境によって保持されなかったため、保持セッションで再起動した。初期起動には計測結果がなく、混在はない。

この時点では本計測の完了試行は0、進行中1。全96条件×10成功はまだ揃っていない。10回の集計結果やABR効果を完了成果として報告する段階ではない。進捗は `results/audit-20261003/production-progress.log`、試行記録は `results/production-20261003/manifest-shard-0.jsonl`、中間CSV・グラフは最初の試行終了後から更新される。プロセス終了コードは終了後 `production-exit-code.txt` に保存される。ファイルを編集しても計測にはfrozen配下のソースを使用する。

## 3並列への変更（ユーザー要望）

3個の専用Dockerコンテナ、個別HTTP/WS/CDPポート、Chromeプロファイル、ブラウザCPU affinity、32条件ずつの互いに重複しないshardを使用する。CPU affinityはLinuxの利用可能なCPUを3群に分け、ランナーとそのChrome子プロセスへ適用する。Docker配信サーバのCPUはホストで共有される。netemは各コンテナのeth0に独立して適用。全ワーカーのソース・動画・イメージ一致を実際に検証した。

3並列20秒スモークは3/3有効、失敗0。これらの短い動作検証だけでは逐次と並列のQoEが統計的に同等だとは証明できない。比較条件の計測はすべて同じ3並列バッチから取り、CPU・メモリ等の共有による交絡は残る。CPU/memory pressureの確認では並列スモーク後にCPU some avg10=0.24%、memory some/full avg10=0%を観測した（長期平均の負荷保証ではない）。

逐次バッチは途中で終了してチェックポイントとRUNNER_INTERRUPTEDを保持し、新しい本計測には一切合算しない。シェルのバックグラウンドで起動した逐次ランナーはSIGINTを無視していたため、そのランナーとChrome子プロセスのみをSIGTERMで終了し、対応する専用コンテナを削除した。

新本計測保存先は `results/production-parallel-20261003`。トップ階層のrun-01〜run-10に条件名のログを統合し、worker-0〜worker-2に元ログ・失敗・各試行metadataを保持。ハードリンクによる成功ログ統合なので計測ログの内容は変更しない。5分ごとの履歴はprogress-5min.jsonl、10秒ごとの現在状態はprogress.json、全96条件の有効数/終了試行数/失敗数はcondition-coverage.csv。進行中試行は終了試行数に含めない。途中のCSV/グラフも10秒ごとに更新する。

理想的な動画再生時間下限は約53時間。起動・再試行・停止時間などで増える。ワーカーが異常終了した場合は新バッチを停止して調査する。

```bash
/tmp/gp-audit-venv/bin/python scripts/run_parallel_matrix.py \
  --runner results/audit-20261003/parallel-frozen/scripts/run_full_matrix.py \
  --profiles results/audit-20261003/parallel-frozen/experiments/netem_profiles.json \
  --media-dir /home/l0gic/abr-pretest/dash/test2 \
  --image sha256:7852efd0b2cafb4cb9d5c3c0fd0c3b87d35384edfca8aecd15fe9694da545932 \
  --results-dir results/production-parallel-20261003 --workers 3
```

既存バッチへ再実行しない。再現時は新しい保存先を指定する。実行にはtaskset、Chrome、Dockerとwebsocket-clientを使用。保持実行セッション23183で実際に起動。

## 全長計測で検出した完了検知の不具合と修正

5分ごとのチャット監視中、全3ワーカーが596.4秒で停止したのにランナーが次条件へ進まないことを発見した。ログにはdash.jsのPLAYBACK_ENDEDがある一方で、その後のHEARTBEATのnative video.endedがfalseだった。ランナーはnative video.endedだけでループを抜けていたため、正式な終了イベントを見落としていた。

修正版はブラウザ状態にログのPLAYBACK_ENDED有無を含め、それを完了検知に使用する。末尾到達・native endedだけを成功とする処理は追加しない。RUNNER_COMPLETION_OBSERVEDで実際に検知した状態も記録する。欠損完了イベントは引き続き無効。回帰テストは「native ended=falseでも正式なイベントありなら完了」「時刻だけの末尾到達は未完了」を検証し、全11件成功。

旧production-parallel-20261003はsupersededとして中断し、3件のチェックポイントとinterrupted metadataを保持。旧バッチを新本計測へ混ぜない。修正版20秒スモークは3/3成功、失敗0。全長596.4秒の3並列検証をparallel-full-validation-v2-20261003で開始した。この検証も本計測10回には含めない。ソースはparallel-frozen-v2に固定している。全長検証通過後に別バッチで本計測を再開する。

### 修正版全長検証通過・本計測再開

14:47に全長検証3/3成功、失敗0を確認。BBR/Throughput信号なしではnative ended=false、playbackTime=596.4でも、dash.jsの正式PLAYBACK_ENDEDとRUNNER_COMPLETION_OBSERVEDを認識して終了できた。他2件はnative ended=true、duration/playbackTime=596.458332。すべて同じ判定（正式終了イベント）で処理し、末尾時刻だけを基準に成功扱いしていない。

14:48に新本計測production-parallel-v2-20261003を開始した（保持実行セッション36874）。全3ワーカーのソース・動画・Dockerイメージが一致することを再検証済み。旧バッチ、短時間スモーク、全長検証の結果は各条件10回に含めない。現在のチャット監視の対象もこの新バッチ。

## 条件別の初回考察を先行する方式へ変更

ユーザーの指示により、自動の10回反復を停止し、各条件1試行→実測考察→妥当性判断→独立した10成功、へ変更した。旧v2本計測は6完了/3途中中断を保存し、新本計測には合算しない。

初回6条件の考察はresults/initial-reviews-20261003/initial-review.mdとinitial-comparison.csv。CC・再生セッション・完了は一致したが、collectorは同IP HTTP接続のポーリング時刻で接続を選んでおり、DASHを要求したソケットか裏付ける情報がなかった。全6件を保留した。QoEが悪い結果を選別したためではない。

修正ではHTTP handlerで存在する.mpd/.m4sのGETを記録し、対応IPの最も新しいDASH要求の接続を選ぶ。ポーリングがlast_seen_atを更新して古い接続を選び続ける問題を避け、http_request_pathとmedia_request_timestamp_msをTCPメトリクスに付加する。単一クライアント設計は継続。RTT・配送レートはアイドル中に変わらない場合があり、収集時刻の鮮度とACKされた情報の鮮度は区別する。

テスト19件成功。実TCP_INFO/WS統合でMPDの対象URL、3並列スモークでDASHセグメントの対象URLを確認。段階実行スモークでは初回3成功後にawaiting_reviewになり、本計測の試行0・measurements未作成を確認。検査通過だけでは10回へ進まないことを実動作で検証した。

新実験はresults/reviewed-matrix-20261003（保持セッション18558）。新ソースはreviewed-frozenに固定し、イメージはsha256:de50b18d0a82c242944d8dd0b2b1cea1f170063fb065ff2add4da422e6d5d8e2。collectorのイメージ内ファイルSHA256が固定ソースと一致することを確認した。最初の3条件は同じhigh-rtt-lossのCUBIC/Throughput/none、CUBIC/Throughput/loss、BBR/Throughput/none。各条件1回でレビュー待ちに入り、担当者の根拠付き判断後のみ10回へ進む。初回はpilots、本計測はrun-01〜run-10で分離。

新方式の手順と妥当性判断の項目はdocs/reviewed_experiments.md。ユーザーへ逐次許可を求める方式ではなく、Codexがログを考察して判断を記録する方式。定期チャット報告はユーザーの指示により停止している。

### 初回考察で表示ビットレートの測定混同を検出

新collectorで全長3件が完了し、対象DASHソケット、CC/netem/seed、セッション、完了を確認。初回はCUBIC/Throughput/none=約0.177434 Mbps、CUBIC/Throughput/loss=約0.189258 Mbps、BBR/Throughput/none=約1.376768 Mbps（同じhigh-rtt-loss、全件停止0秒）。単独試行なので信号やCCの平均的効果は未確定。

CUBIC/lossのHEARTBEATはcurrentQuality=0なのに品質1のbitrateInfoを6サンプル含み、コードのgetCurrentBitrateInfoSafeがダウンロード予定品質をlastVideoBitrateInfoへ上書きすることを確認した。全3件を保留し、旧reviewed-matrix-20261003を中断・保存。要求品質の読み取りを副作用なしにし、表示品質との整合性チェックを追加。20件のテストと実Chromeによる分離検証を実施。修正後の3並列20秒検証は全件完了・技術検査通過・反復なしでawaiting_review。詳細はdocs/reviewed_experiments.md。

### 修正後の初回考察を経て3条件の10回反復を開始

reviewed-matrix-v2-20261003で修正後の初回3件が完了。全技術検査を通過し、品質とbitrateの不整合0。時間加重MbpsはCUBIC/Throughput/none=0.177434、CUBIC/Throughput/loss=0.179973、BBR/Throughput/none=1.380925、全件停止0秒。CUBIC/lossはGuardrail発動0回、congestionSamples=1/confirming=1。この初回比較では低品質をGuardrailによる品質低下の結果とは言えず、効果の優劣・平均・有意差も未確定。

担当者が観測・仮説と妥当性判断をpilot-review.mdおよび各条件review.mdに保存してから、3条件のdecision.jsonをapprovedにした。条件はhigh-rtt-lossに揃っており、QoEの良し悪しではなく計測系の妥当性で判断した。各条件の初回は1有効/1試行/0失敗。初回は10回の本計測に含めない。

その後、3条件だけが10回反復を開始。measurementsのbatch.jsonでrepetitions=10と初回とのsources/media/image完全一致を確認し、measurement-start-verification.jsonへ保存した。3専用Dockerコンテナの同時稼働、再生約52秒、各105〜107の実TCPサンプルを確認。未考察93条件はqueuedで、判断なく10回へ進めない。10回の本計測はまだ完了していない。

保存先はresults/reviewed-matrix-v2-20261003、固定ソースはresults/audit-20261003/reviewed-frozen-v2、イメージはsha256:eed7db75e99f9277cffe614dbcd1b4d9e1f1bb9f11ac61ef511be7c549d241eb。保持セッション85198。初回CSVとグラフはpilot-comparison.csv/pilot-bitrate.svg、本計測CSVとグラフは試行完了後に生成する。


## 全96条件の初回を優先する順序への変更

最新の指示に従い、先行反復を中断した。旧反復の完了3件・中断3件は別保存し、新本計測へ含めない。全条件の初回完了と全考察を反復開始の必須条件に変更。23テスト通過。2条件の短い実TCPスモークは初回2件、本計測0件で正常終了。results/all-first-20261003を起動し、同一固定ソース・動画・イメージを照合した初回3件を取り込み、残り93件を3並列で実行している。起動確認時点では初回完了3/96、有効3、失敗0、レビュー済み3、本計測0。全条件の初回が完了したとの主張はしていない。
